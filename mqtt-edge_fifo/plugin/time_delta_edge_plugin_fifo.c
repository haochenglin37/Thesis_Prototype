// time_delta_edge_plugin_dual_fifo.c
// Mosquitto v5 plugin for Edge Broker with Three-Stage Pipeline:
//  Stage 1: on_message -> receive_queue (minimal processing, record real recv_ts)
//  Stage 2: processor_thread -> call policy API -> HIGH_FIFO or LOW_FIFO (based on action)
//  Stage 3: external forwarder reads respective FIFO and forwards to main broker
//
// Compile with:
// gcc -Wall -fPIC -shared \
//   time_delta_edge_plugin_dual_fifo.c \
//   -o time_delta_edge_plugin.so \
//   $(pkg-config --cflags --libs libmosquitto libcurl json-c) \
//   -lpthread

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/time.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <errno.h>
#include <pthread.h>
#include <curl/curl.h>
#include <json-c/json.h>
#include "uthash.h"
#include <mosquitto.h>
#include <mosquitto_plugin.h>
#include <mosquitto_broker.h>

#define POLICY_URL   "http://192.168.254.191:5000/policy"
#define LOG_PATH     "/home/jason/mqtt-edge/logs/edge_plugin.csv"
#define HIGH_FIFO_PATH "/home/jason/mqtt-edge/forwarder/high_priority_queue.fifo"
#define LOW_FIFO_PATH  "/home/jason/mqtt-edge/forwarder/low_priority_queue.fifo"
#define CLEANUP_INTERVAL 1000000
#define PROCESS_DELAY_MICROSEC 10000
#define COND_WAIT_TIMEOUT_MICROSEC 500000
#define FIXED_SERVICE_TIME_MS 0.0

// per-IP state + packet_count
struct ip_entry {
    char      ip[64];
    double    last_time;
    uint64_t  packet_count;
    UT_hash_handle hh;
};
static struct ip_entry *ip_table = NULL;
static pthread_mutex_t   ip_table_mutex;

// 雙 FIFO 支援
static int high_fifo_fd = -1;
static int low_fifo_fd = -1;

// logging
static FILE *log_file = NULL;
static pthread_mutex_t log_mutex;

// ===== Stage 1: Receive Queue (minimal data, fast enqueue) =====
typedef struct ReceiveNode {
    char                ip[64];
    double              recv_ts;        // 真正的接收時間
    uint64_t            packet_count;   // 在 on_message 中已計算好
    struct ReceiveNode *next;
} ReceiveNode;

static ReceiveNode *receive_head = NULL;
static ReceiveNode *receive_tail = NULL;
static ReceiveNode *receive_current_pos = NULL;
static pthread_mutex_t receive_mutex;
static pthread_cond_t  receive_cond;

// ===== 批次 CSV 寫入機制 =====
typedef struct CSVRecord {
    uint64_t packet_count;
    double recv_ts;
    double service_start_ts;
    double api_start_ts;
    double api_end_ts;
    double service_end_ts;
    char ip[64];
    double delta;
    double p_value;
    double trust;
    char action[16];
    double actual_api_time_ms;
    double wait_time_ms;
    double total_service_time_ms;
    struct CSVRecord *next;
} CSVRecord;

static CSVRecord *csv_queue_head = NULL;
static CSVRecord *csv_queue_tail = NULL;
static pthread_mutex_t csv_queue_mutex;
static pthread_cond_t csv_queue_cond;
static pthread_t csv_writer_thread;
static int csv_writer_running = 0;

// background thread for processing
static pthread_t processor_thread;
static int       threads_running = 0;
static int       process_counter = 0;

// 快速入隊 CSV 記錄（不阻塞處理流程）
static void enqueue_csv_record(uint64_t packet_count, double recv_ts, double service_start_ts,
                               double api_start_ts, double api_end_ts, double service_end_ts,
                               const char *ip, double delta, double p_value, double trust,
                               const char *action, double actual_api_time_ms, double wait_time_ms,
                               double total_service_time_ms) {
    CSVRecord *record = malloc(sizeof(*record));
    if (!record) return;
    
    record->packet_count = packet_count;
    record->recv_ts = recv_ts;
    record->service_start_ts = service_start_ts;
    record->api_start_ts = api_start_ts;
    record->api_end_ts = api_end_ts;
    record->service_end_ts = service_end_ts;
    strncpy(record->ip, ip, sizeof(record->ip)-1);
    record->ip[sizeof(record->ip)-1] = '\0';
    record->delta = delta;
    record->p_value = p_value;
    record->trust = trust;
    strncpy(record->action, action, sizeof(record->action)-1);
    record->action[sizeof(record->action)-1] = '\0';
    record->actual_api_time_ms = actual_api_time_ms;
    record->wait_time_ms = wait_time_ms;
    record->total_service_time_ms = total_service_time_ms;
    record->next = NULL;
    
    pthread_mutex_lock(&csv_queue_mutex);
    if (!csv_queue_tail) {
        csv_queue_head = csv_queue_tail = record;
    } else {
        csv_queue_tail->next = record;
        csv_queue_tail = record;
    }
    pthread_cond_signal(&csv_queue_cond);
    pthread_mutex_unlock(&csv_queue_mutex);
}

// CSV 寫入執行緒（背景批次處理）
static void *csv_writer_thread_fn(void *arg) {
    CSVRecord *current_pos = NULL;
    
    while (csv_writer_running) {
        pthread_mutex_lock(&csv_queue_mutex);
        
        int has_new_record = 0;
        if (current_pos == NULL) {
            current_pos = csv_queue_head;
            has_new_record = (current_pos != NULL);
        } else if (current_pos->next) {
            current_pos = current_pos->next;
            has_new_record = 1;
        }
        
        if (has_new_record) {
            CSVRecord record_data = *current_pos;
            pthread_mutex_unlock(&csv_queue_mutex);
            
            pthread_mutex_lock(&log_mutex);
            if (log_file) {
                fprintf(log_file,
                    "%llu,%.6f,%.6f,%.6f,%.6f,%.6f,%s,%.6f,%.4f,%.3f,%llu,%s,%.3f,%.3f,%.3f\n",
                    record_data.packet_count,
                    record_data.recv_ts,
                    record_data.service_start_ts,
                    record_data.api_start_ts,
                    record_data.api_end_ts,
                    record_data.service_end_ts,
                    record_data.ip,
                    record_data.delta,
                    record_data.p_value,
                    record_data.trust,
                    record_data.packet_count,
                    record_data.action,
                    record_data.actual_api_time_ms,
                    record_data.wait_time_ms,
                    record_data.total_service_time_ms
                );
                fflush(log_file);
            }
            pthread_mutex_unlock(&log_mutex);
            
        } else {
            struct timespec timeout;
            struct timeval now;
            gettimeofday(&now, NULL);
            timeout.tv_sec = now.tv_sec;
            timeout.tv_nsec = (now.tv_usec + 100000) * 1000;
            if (timeout.tv_nsec >= 1000000000) {
                timeout.tv_sec++;
                timeout.tv_nsec -= 1000000000;
            }
            pthread_cond_timedwait(&csv_queue_cond, &csv_queue_mutex, &timeout);
            pthread_mutex_unlock(&csv_queue_mutex);
        }
        
        if (has_new_record) {
            usleep(1000);
        }
    }
    return NULL;
}

static double now_sec(){
    struct timeval tv;
    gettimeofday(&tv,NULL);
    return tv.tv_sec + tv.tv_usec/1e6;
}

// curl write callback
static size_t curl_write_cb(char *ptr, size_t size, size_t nmemb, void *ud){
    size_t total_size = size * nmemb;
    size_t current_len = strlen((char*)ud);
    size_t remaining = 255 - current_len;
    
    if (total_size > remaining) {
        total_size = remaining;
    }
    
    strncat((char*)ud, ptr, total_size);
    return total_size;
}

// call policy API, return action, trust, p_value
static int call_policy_api(const char *ip, double delta,
                           char *out_action,
                           double *out_trust,
                           double *out_pval)
{
    printf("[API] Calling policy API for IP=%s, Delta=%.6f\n", ip, delta);
    
    CURL *curl = curl_easy_init();
    if(!curl) {
        printf("[API] Failed to initialize CURL\n");
        return -1;
    }
    
    json_object *jreq = json_object_new_object();
    json_object_object_add(jreq,"ip",json_object_new_string(ip));
    json_object_object_add(jreq,"time_delta",json_object_new_double(delta));
    const char *body = json_object_to_json_string(jreq);
    
    printf("[API] Request: %s\n", body);

    char response[256] = {0};
    struct curl_slist *hdrs = curl_slist_append(NULL,"Content-Type: application/json");
    curl_easy_setopt(curl, CURLOPT_URL,        POLICY_URL);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA,     response);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT,    2);
    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(hdrs);
    curl_easy_cleanup(curl);
    json_object_put(jreq);
    
    if(res != CURLE_OK) {
        printf("[API] Request failed: %s\n", curl_easy_strerror(res));
        return -1;
    }
    
    printf("[API] Response: %s\n", response);

    json_object *r = json_tokener_parse(response);
    if(!r) {
        printf("[API] Invalid JSON response\n");
        return -1;
    }
    
    json_object *ja, *jt, *jp;
    if(json_object_object_get_ex(r,"action",&ja) &&
       json_object_object_get_ex(r,"trust",&jt)   &&
       json_object_object_get_ex(r,"p_value",&jp))
    {
        const char *action_str = json_object_get_string(ja);
        strncpy(out_action, action_str, 15);
        out_action[15]='\0';
        *out_trust = json_object_get_double(jt);
        *out_pval  = json_object_get_double(jp);
        
        // 可選：讀取 high_threshold (如果存在)
        json_object *jht;
        double high_threshold = 0.0;
        if(json_object_object_get_ex(r,"high_threshold",&jht)) {
            high_threshold = json_object_get_double(jht);
        }
        
        printf("[API] *** DECISION *** Action=%s, Trust=%.3f, P_value=%.6f, High_threshold=%.3f\n", 
               action_str, *out_trust, *out_pval, high_threshold);
        
        json_object_put(r);
        return 0;
    }
    
    printf("[API] No 'action' field in response\n");
    json_object_put(r);
    return -1;
}

// 根據 action 寫入對應的 FIFO，包含錯誤處理和重試
static void write_to_fifo(const char *action, const char *ip, uint64_t count, double enqueue_ts) {
    int target_fd = -1;
    const char *fifo_type = "";
    const char *fifo_path = "";
    
    if (strcmp(action, "high") == 0) {
        target_fd = high_fifo_fd;
        fifo_type = "HIGH";
        fifo_path = HIGH_FIFO_PATH;
    } else if (strcmp(action, "low") == 0) {
        target_fd = low_fifo_fd;
        fifo_type = "LOW";
        fifo_path = LOW_FIFO_PATH;
    } else {
        printf("[FIFO] Unknown action '%s', skipping FIFO write\n", action);
        return;
    }
    
    if (target_fd == -1) {
        printf("[FIFO] %s FIFO not available, skipping write\n", fifo_type);
        return;
    }
    
    char buffer[256];
    int len = snprintf(buffer, sizeof(buffer),
        "{\"ip\":\"%s\",\"count\":%llu,\"timestamp\":%.6f,\"priority\":\"%s\"}\n",
        ip, (unsigned long long)count, enqueue_ts, action);
    
    if (len > 0 && len < sizeof(buffer)) {
        ssize_t written = write(target_fd, buffer, len);
        if (written == len) {
            printf("[FIFO] Written to %s FIFO: %s", fifo_type, buffer);
        } else if (written < 0) {
            if (errno == EPIPE) {
                printf("[FIFO] %s FIFO broken pipe - reader disconnected, attempting to reopen\n", fifo_type);
                // 嘗試重新開啟 FIFO
                close(target_fd);
                int new_fd = open(fifo_path, O_WRONLY | O_NONBLOCK);
                if (new_fd != -1) {
                    if (strcmp(action, "high") == 0) {
                        high_fifo_fd = new_fd;
                    } else {
                        low_fifo_fd = new_fd;
                    }
                    printf("[FIFO] %s FIFO reopened successfully\n", fifo_type);
                } else {
                    printf("[FIFO] %s FIFO reopen failed: %s\n", fifo_type, strerror(errno));
                    if (strcmp(action, "high") == 0) {
                        high_fifo_fd = -1;
                    } else {
                        low_fifo_fd = -1;
                    }
                }
            } else {
                printf("[FIFO] %s FIFO write error: %s\n", fifo_type, strerror(errno));
            }
        } else {
            printf("[FIFO] %s FIFO partial write: %zd/%d bytes\n", fifo_type, written, len);
        }
    }
}

// cleanup old processed nodes
static void cleanup_old_receive_nodes() {
    if(!receive_head || !receive_current_pos) return;
    
    double now = now_sec();
    ReceiveNode *prev = NULL;
    ReceiveNode *curr = receive_head;
    
    while(curr && curr != receive_current_pos) {
        if(now - curr->recv_ts > 300.0) {  // 5分鐘前的節點
            if(prev) {
                prev->next = curr->next;
            } else {
                receive_head = curr->next;
            }
            ReceiveNode *to_free = curr;
            curr = curr->next;
            free(to_free);
            printf("[cleanup] cleaned up old receive node\n");
        } else {
            prev = curr;
            curr = curr->next;
        }
    }
}

// ===== Stage 2: Processor Thread (receive_queue -> policy API -> fixed service time -> dual FIFO) =====
static void *processor_thread_fn(void *arg) {
    while(threads_running) {
        pthread_mutex_lock(&receive_mutex);
        
        int has_new_data = 0;
        if (receive_current_pos == NULL) {
            receive_current_pos = receive_head;
            has_new_data = (receive_current_pos != NULL);
        } else if (receive_current_pos->next) {
            receive_current_pos = receive_current_pos->next;
            has_new_data = 1;
        }
        
        if (has_new_data) {
            ReceiveNode current_data = *receive_current_pos;
            pthread_mutex_unlock(&receive_mutex);
            
            // M/D/1 服務開始
            double service_start_ts = now_sec();
            
            // 計算 delta
            double delta = 0.0;
            pthread_mutex_lock(&ip_table_mutex);
            struct ip_entry *e = NULL;
            HASH_FIND_STR(ip_table, current_data.ip, e);
            if (e) {
                delta = current_data.recv_ts - e->last_time;
                e->last_time = current_data.recv_ts;
            }
            pthread_mutex_unlock(&ip_table_mutex);
            
            // 調用 policy API
            double api_start_ts = now_sec();
            char action[16] = {0};
            double trust = 0, p_val = 0;
            if (call_policy_api(current_data.ip, delta, action, &trust, &p_val) != 0) {
                printf("[API] Failed to get policy, using default: low\n");
                strcpy(action, "low");
                trust = 1.0;
                p_val = 0.0;
            }
            double api_end_ts = now_sec();
            
            // 計算實際 API 處理時間
            double actual_api_time_ms = (api_end_ts - api_start_ts) * 1000.0;
            
            // 計算還需要等待多久才能達到固定服務時間
            double elapsed_time_ms = (api_end_ts - service_start_ts) * 1000.0;
            double wait_time_ms = 0.0;
            
            if (elapsed_time_ms < FIXED_SERVICE_TIME_MS) {
                wait_time_ms = FIXED_SERVICE_TIME_MS - elapsed_time_ms;
                usleep((useconds_t)(wait_time_ms * 1000));
            }
            
            // M/D/1 服務結束
            double service_end_ts = now_sec();
            double actual_service_time_ms = (service_end_ts - service_start_ts) * 1000.0;
            
            printf("[POLICY] *** SUMMARY *** IP=%s, Delta=%.6f, Action=%s, Service_Time=%.3fms\n", 
                   current_data.ip, delta, action, actual_service_time_ms);
            
            // 根據 action 決定處理方式
            if (strcmp(action, "drop") == 0) {
                printf("[DROP] *** MESSAGE DROPPED *** IP=%s will not be forwarded\n", current_data.ip);
            } else if (strcmp(action, "high") == 0) {
                printf("[HIGH] *** HIGH PRIORITY *** IP=%s -> HIGH FIFO\n", current_data.ip);
                write_to_fifo(action, current_data.ip, current_data.packet_count, service_end_ts);
            } else if (strcmp(action, "low") == 0) {
                printf("[LOW] *** LOW PRIORITY *** IP=%s -> LOW FIFO\n", current_data.ip);
                write_to_fifo(action, current_data.ip, current_data.packet_count, service_end_ts);
            } else {
                printf("[UNKNOWN] *** UNKNOWN ACTION '%s' *** IP=%s, treating as LOW priority\n", 
                       action, current_data.ip);
                write_to_fifo("low", current_data.ip, current_data.packet_count, service_end_ts);
            }
            
            // 記錄到主要 CSV 日誌
            enqueue_csv_record(current_data.packet_count, current_data.recv_ts, service_start_ts,
                              api_start_ts, api_end_ts, service_end_ts, current_data.ip, delta,
                              p_val, trust, action, actual_api_time_ms, wait_time_ms, actual_service_time_ms);
            
            // 定期清理
            if (++process_counter % CLEANUP_INTERVAL == 0) {
                pthread_mutex_lock(&receive_mutex);
                cleanup_old_receive_nodes();
                pthread_mutex_unlock(&receive_mutex);
            }
            
        } else {
            struct timespec timeout;
            struct timeval now;
            gettimeofday(&now, NULL);
            timeout.tv_sec = now.tv_sec;
            timeout.tv_nsec = (now.tv_usec + COND_WAIT_TIMEOUT_MICROSEC) * 1000;
            if (timeout.tv_nsec >= 1000000000) {
                timeout.tv_sec++;
                timeout.tv_nsec -= 1000000000;
            }
            pthread_cond_timedwait(&receive_cond, &receive_mutex, &timeout);
            pthread_mutex_unlock(&receive_mutex);
        }
    }
    return NULL;
}

// ===== Stage 1: on_message callback (minimal processing, fast enqueue) =====
static int on_message_callback(int event, void *event_data, void *userdata){
    struct mosquitto_evt_message *msg = event_data;
    if (!msg || !msg->client) return MOSQ_ERR_INVAL;
    
    double recv_ts = now_sec();
    const char *ip = mosquitto_client_address(msg->client);
    if (!ip) return MOSQ_ERR_INVAL;

    printf("[MSG] Received from %s: %.*s\n", 
           ip, msg->payloadlen, (char*)msg->payload);

    // 快速更新 IP 表並獲取 packet_count
    pthread_mutex_lock(&ip_table_mutex);
    struct ip_entry *e = NULL;
    HASH_FIND_STR(ip_table, ip, e);
    if (!e) {
        e = calloc(1, sizeof(*e));
        if (!e) {
            pthread_mutex_unlock(&ip_table_mutex);
            return MOSQ_ERR_NOMEM;
        }
        strncpy(e->ip, ip, sizeof(e->ip)-1);
        e->last_time = recv_ts;
        e->packet_count = 0;
        HASH_ADD_STR(ip_table, ip, e);
    }
    e->packet_count++;
    uint64_t seq = e->packet_count;
    pthread_mutex_unlock(&ip_table_mutex);

    // 立即入隊到接收隊列
    ReceiveNode *rn = malloc(sizeof(*rn));
    if (!rn) return MOSQ_ERR_NOMEM;
    
    strncpy(rn->ip, ip, sizeof(rn->ip)-1);
    rn->ip[sizeof(rn->ip)-1] = '\0';
    rn->recv_ts = recv_ts;
    rn->packet_count = seq;
    rn->next = NULL;
    
    pthread_mutex_lock(&receive_mutex);
    if (!receive_tail) {
        receive_head = receive_tail = rn;
    } else {
        receive_tail->next = rn;
        receive_tail = rn;
    }
    pthread_cond_signal(&receive_cond);
    pthread_mutex_unlock(&receive_mutex);

    printf("[receive] enqueued: ip=%s, packet_count=%llu, recv_ts=%.6f\n",
           ip, (unsigned long long)seq, recv_ts);

    return MOSQ_ERR_ACL_DENIED;
}

int mosquitto_plugin_version(int count, const int *vers){
    for(int i=0;i<count;i++){
        if(vers[i]==MOSQ_PLUGIN_VERSION) return MOSQ_PLUGIN_VERSION;
    }
    return -1;
}

int mosquitto_plugin_init(mosquitto_plugin_id_t *identifier,
                          void **userdata,
                          struct mosquitto_opt *options,
                          int option_count)
{
    printf("[PLUGIN] Initializing three-stage DUAL FIFO plugin...\n");
    
    pthread_mutex_init(&ip_table_mutex, NULL);
    pthread_mutex_init(&log_mutex,     NULL);
    pthread_mutex_init(&receive_mutex, NULL);
    pthread_mutex_init(&csv_queue_mutex, NULL);
    pthread_cond_init(&receive_cond,   NULL);
    pthread_cond_init(&csv_queue_cond, NULL);
    curl_global_init(CURL_GLOBAL_ALL);

    // 確保目錄存在
    system("mkdir -p /home/jason/mqtt-edge/logs");
    system("mkdir -p /home/jason/mqtt-edge/forwarder");

    // 開啟日誌文件
    log_file = fopen(LOG_PATH,"w");
    if(log_file){
        fprintf(log_file,
          "packet_count,recv_ts,service_start_ts,api_start_ts,api_end_ts,service_end_ts,ip,delta,p_value,trust,packet_count_dup,action,actual_api_time_ms,wait_time_ms,total_service_time_ms\n");
        fflush(log_file);
        printf("[PLUGIN] Log file opened: %s\n", LOG_PATH);
    }

    // 建立雙 FIFO
    if (mkfifo(HIGH_FIFO_PATH, 0666) == -1 && errno != EEXIST) {
        printf("[PLUGIN] mkfifo HIGH warning: %s\n", strerror(errno));
    }
    if (mkfifo(LOW_FIFO_PATH, 0666) == -1 && errno != EEXIST) {
        printf("[PLUGIN] mkfifo LOW warning: %s\n", strerror(errno));
    }
    
    // 開啟雙 FIFO（先阻塞模式確保連接，再改為非阻塞）
    printf("[PLUGIN] Opening HIGH FIFO: %s\n", HIGH_FIFO_PATH);
    high_fifo_fd = open(HIGH_FIFO_PATH, O_WRONLY);
    if (high_fifo_fd == -1) {
        printf("[PLUGIN] Warning: HIGH FIFO not available: %s\n", strerror(errno));
    } else {
        // 改為非阻塞模式
        int flags = fcntl(high_fifo_fd, F_GETFL);
        fcntl(high_fifo_fd, F_SETFL, flags | O_NONBLOCK);
        printf("[PLUGIN] HIGH FIFO opened: %s\n", HIGH_FIFO_PATH);
    }
    
    printf("[PLUGIN] Opening LOW FIFO: %s\n", LOW_FIFO_PATH);
    low_fifo_fd = open(LOW_FIFO_PATH, O_WRONLY);
    if (low_fifo_fd == -1) {
        printf("[PLUGIN] Warning: LOW FIFO not available: %s\n", strerror(errno));
    } else {
        // 改為非阻塞模式
        int flags = fcntl(low_fifo_fd, F_GETFL);
        fcntl(low_fifo_fd, F_SETFL, flags | O_NONBLOCK);
        printf("[PLUGIN] LOW FIFO opened: %s\n", LOW_FIFO_PATH);
    }

    threads_running = 1;
    csv_writer_running = 1;
    
    if (pthread_create(&processor_thread, NULL, processor_thread_fn, NULL) != 0) {
        printf("[PLUGIN] Error: Failed to create processor thread\n");
        return MOSQ_ERR_UNKNOWN;
    }
    
    if (pthread_create(&csv_writer_thread, NULL, csv_writer_thread_fn, NULL) != 0) {
        printf("[PLUGIN] Error: Failed to create CSV writer thread\n");
        return MOSQ_ERR_UNKNOWN;
    }

    mosquitto_callback_register(identifier,
      MOSQ_EVT_MESSAGE, on_message_callback, NULL, NULL);

    printf("[PLUGIN] initialized with three-stage dual FIFO pipeline (receive -> process -> HIGH/LOW FIFO)\n");
    fflush(stdout);
    return MOSQ_ERR_SUCCESS;
}

int mosquitto_plugin_cleanup(void *userdata,
                             struct mosquitto_opt *options,
                             int option_count)
{
    printf("[PLUGIN] Cleaning up...\n");
    
    threads_running = 0;
    csv_writer_running = 0;
    
    pthread_cond_signal(&receive_cond);
    pthread_cond_signal(&csv_queue_cond);
    
    pthread_join(processor_thread, NULL);
    pthread_join(csv_writer_thread, NULL);

    // 關閉雙 FIFO
    if (high_fifo_fd != -1) {
        close(high_fifo_fd);
        high_fifo_fd = -1;
    }
    if (low_fifo_fd != -1) {
        close(low_fifo_fd);
        low_fifo_fd = -1;
    }

    // free receive queue
    ReceiveNode *rn;
    while((rn=receive_head)){
        receive_head = rn->next;
        free(rn);
    }

    // free csv queue
    CSVRecord *cr;
    while((cr=csv_queue_head)){
        csv_queue_head = cr->next;
        free(cr);
    }

    if(log_file) fclose(log_file);

    // free ip_table
    struct ip_entry *e,*tmp;
    HASH_ITER(hh, ip_table, e, tmp){
        HASH_DEL(ip_table,e);
        free(e);
    }

    pthread_mutex_destroy(&ip_table_mutex);
    pthread_mutex_destroy(&log_mutex);
    pthread_mutex_destroy(&receive_mutex);
    pthread_mutex_destroy(&csv_queue_mutex);
    pthread_cond_destroy(&receive_cond);
    pthread_cond_destroy(&csv_queue_cond);
    
    curl_global_cleanup();
    printf("[PLUGIN] cleanup done\n");
    fflush(stdout);
    return MOSQ_ERR_SUCCESS;
}
