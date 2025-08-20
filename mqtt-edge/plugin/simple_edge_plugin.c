// simple_edge_plugin.c
// 簡化版本的 MQTT 邊緣插件
// 接收訊息 -> 呼叫 API -> 決定 forward/drop -> 寫入 FIFO

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/time.h>
#include <fcntl.h>
#include <errno.h>
#include <pthread.h>
#include <curl/curl.h>
#include <json-c/json.h>
#include "uthash.h"
#include <mosquitto.h>
#include <mosquitto_plugin.h>
#include <mosquitto_broker.h>

// 配置
#define POLICY_URL       "http://192.168.254.139:5000/policy"
#define LOG_PATH         "/var/log/mosquitto/edge_plugin.csv"
#define FIFO_PATH        "/home/jason/mqtt-edge/forwarder/message_queue.fifo"

// IP 狀態表
struct ip_entry {
    char      ip[64];
    double    last_time;
    uint64_t  packet_count;
    UT_hash_handle hh;
};
static struct ip_entry *ip_table = NULL;
static pthread_mutex_t ip_table_mutex;

// FIFO 和日誌
static int fifo_fd = -1;
static FILE *log_file = NULL;
static pthread_mutex_t log_mutex;

// 取得當前時間
static double now_sec() {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec + tv.tv_usec / 1e6;
}

// CURL 回調函數
static size_t curl_callback(char *ptr, size_t size, size_t nmemb, void *userdata) {
    size_t total_size = size * nmemb;
    size_t current_len = strlen((char*)userdata);
    size_t remaining = 255 - current_len;
    
    if (total_size > remaining) {
        total_size = remaining;
    }
    
    strncat((char*)userdata, ptr, total_size);
    return total_size;
}

// 呼叫政策 API
static int call_policy_api(const char *ip, double delta, char *out_action) {
    CURL *curl = curl_easy_init();
    if (!curl) return -1;
    
    // 建立 JSON 請求
    json_object *request = json_object_new_object();
    json_object_object_add(request, "ip", json_object_new_string(ip));
    json_object_object_add(request, "time_delta", json_object_new_double(delta));
    
    const char *json_string = json_object_to_json_string(request);
    char response[256] = {0};
    
    // 設定 CURL 選項
    struct curl_slist *headers = curl_slist_append(NULL, "Content-Type: application/json");
    curl_easy_setopt(curl, CURLOPT_URL, POLICY_URL);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_string);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_callback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, response);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 2);  // 2秒超時
    
    CURLcode res = curl_easy_perform(curl);
    
    // 清理
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    json_object_put(request);
    
    if (res != CURLE_OK) {
        printf("[API] Request failed: %s\n", curl_easy_strerror(res));
        return -1;
    }
    
    // 解析回應
    json_object *response_obj = json_tokener_parse(response);
    if (!response_obj) {
        printf("[API] Invalid JSON response\n");
        return -1;
    }
    
    json_object *action_obj;
    if (json_object_object_get_ex(response_obj, "action", &action_obj)) {
        strncpy(out_action, json_object_get_string(action_obj), 15);
        out_action[15] = '\0';
        json_object_put(response_obj);
        return 0;
    }
    
    json_object_put(response_obj);
    return -1;
}

// 寫入 FIFO
static void write_to_fifo(const char *ip, uint64_t count, double enqueue_ts) {
    if (fifo_fd == -1) return;
    
    char buffer[256];
    int len = snprintf(buffer, sizeof(buffer),
        "{\"ip\":\"%s\",\"count\":%llu,\"timestamp\":%.6f}\n",
        ip, (unsigned long long)count, enqueue_ts);
    
    if (len > 0 && len < sizeof(buffer)) {
        ssize_t written = write(fifo_fd, buffer, len);
        if (written < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                printf("[FIFO] Queue full, message dropped\n");
            } else {
                perror("[FIFO] Write error");
            }
        } else {
            printf("[FIFO] Written: %s", buffer);
        }
    }
}

// 記錄日誌
static void log_message(const char *ip, uint64_t count, double enqueue_ts, 
                       double start_service_ts, double end_service_ts, 
                       double delta, const char *action) {
    pthread_mutex_lock(&log_mutex);
    if (log_file) {
        fprintf(log_file, "%.6f,%.6f,%.6f,%s,%llu,%.6f,%s\n",
                enqueue_ts, start_service_ts, end_service_ts, ip, 
                (unsigned long long)count, delta, action);
        fflush(log_file);
    }
    pthread_mutex_unlock(&log_mutex);
}

// 訊息處理回調
static int on_message_callback(int event, void *event_data, void *userdata) {
    struct mosquitto_evt_message *msg = event_data;
    if (!msg || !msg->client) return MOSQ_ERR_INVAL;
    
    double enqueue_ts = now_sec();  // 訊息進入處理佇列的時間
    const char *client_ip = mosquitto_client_address(msg->client);
    if (!client_ip) return MOSQ_ERR_INVAL;
    
    printf("[MSG] Received from %s: %.*s\n", 
           client_ip, msg->payloadlen, (char*)msg->payload);
    
    // 更新 IP 狀態
    pthread_mutex_lock(&ip_table_mutex);
    struct ip_entry *entry;
    HASH_FIND_STR(ip_table, client_ip, entry);
    
    double delta = 0.0;
    if (!entry) {
        entry = calloc(1, sizeof(*entry));
        strncpy(entry->ip, client_ip, sizeof(entry->ip) - 1);
        entry->last_time = enqueue_ts;
        entry->packet_count = 1;
        HASH_ADD_STR(ip_table, ip, entry);
    } else {
        delta = enqueue_ts - entry->last_time;
        entry->last_time = enqueue_ts;
        entry->packet_count++;
    }
    
    uint64_t count = entry->packet_count;
    pthread_mutex_unlock(&ip_table_mutex);
    
    // 開始服務時間（開始計算 delta 和呼叫 API）
    double start_service_ts = now_sec();
    
    // 呼叫政策 API
    char action[16] = "forward";  // 預設動作
    if (call_policy_api(client_ip, delta, action) != 0) {
        printf("[API] Failed to get policy, using default: forward\n");
        strcpy(action, "forward");
    }
    
    // 結束服務時間（完成 API 呼叫和決策）
    double end_service_ts = now_sec();
    
    printf("[POLICY] IP=%s, Delta=%.3f, Action=%s, Service_Time=%.3fms\n", 
           client_ip, delta, action, (end_service_ts - start_service_ts) * 1000);
    
    // 記錄詳細日誌
    log_message(client_ip, count, enqueue_ts, start_service_ts, end_service_ts, delta, action);
    
    // 如果決定轉發，寫入 FIFO
    if (strcmp(action, "forward") == 0) {
        write_to_fifo(client_ip, count, enqueue_ts);
    }
    
    // 拒絕訊息（不讓它繼續傳播）
    return MOSQ_ERR_ACL_DENIED;
}

// 插件版本
int mosquitto_plugin_version(int supported_version_count, const int *supported_versions) {
    for (int i = 0; i < supported_version_count; i++) {
        if (supported_versions[i] == MOSQ_PLUGIN_VERSION) {
            return MOSQ_PLUGIN_VERSION;
        }
    }
    return -1;
}

// 插件初始化
int mosquitto_plugin_init(mosquitto_plugin_id_t *identifier,
                          void **user_data,
                          struct mosquitto_opt *opts,
                          int opt_count) {
    
    printf("[PLUGIN] Initializing simple edge plugin...\n");
    
    // 初始化互斥鎖
    pthread_mutex_init(&ip_table_mutex, NULL);
    pthread_mutex_init(&log_mutex, NULL);
    
    // 初始化 curl
    curl_global_init(CURL_GLOBAL_DEFAULT);
    
    // 確保目錄存在
    system("mkdir -p /var/log/mosquitto");
    system("mkdir -p /home/jason/mqtt-edge/logs");
    system("mkdir -p /home/jason/mqtt-edge/forwarder");
    
    // 開啟日誌文件
    log_file = fopen(LOG_PATH, "w");
    if (log_file) {
        fprintf(log_file, "enqueue_ts,start_service_ts,end_service_ts,ip,packet_count,delta,action\n");
        fflush(log_file);
        printf("[PLUGIN] Log file opened: %s\n", LOG_PATH);
    }
    
    // 建立 FIFO
    if (mkfifo(FIFO_PATH, 0666) == -1 && errno != EEXIST) {
        perror("[PLUGIN] mkfifo");
    }
    
    // 開啟 FIFO（非阻塞模式）
    fifo_fd = open(FIFO_PATH, O_WRONLY | O_NONBLOCK);
    if (fifo_fd == -1) {
        perror("[PLUGIN] open fifo");
        printf("[PLUGIN] Warning: FIFO not available\n");
    } else {
        printf("[PLUGIN] FIFO opened: %s\n", FIFO_PATH);
    }
    
    // 註冊回調
    mosquitto_callback_register(identifier, MOSQ_EVT_MESSAGE, on_message_callback, NULL, NULL);
    
    printf("[PLUGIN] Initialization complete\n");
    return MOSQ_ERR_SUCCESS;
}

// 插件清理
int mosquitto_plugin_cleanup(void *user_data,
                            struct mosquitto_opt *opts,
                            int opt_count) {
    
    printf("[PLUGIN] Cleaning up...\n");
    
    // 關閉 FIFO
    if (fifo_fd != -1) {
        close(fifo_fd);
    }
    
    // 關閉日誌
    if (log_file) {
        fclose(log_file);
    }
    
    // 清理 IP 表
    struct ip_entry *entry, *tmp;
    HASH_ITER(hh, ip_table, entry, tmp) {
        HASH_DEL(ip_table, entry);
        free(entry);
    }
    
    // 清理互斥鎖
    pthread_mutex_destroy(&ip_table_mutex);
    pthread_mutex_destroy(&log_mutex);
    
    // 清理 curl
    curl_global_cleanup();
    
    printf("[PLUGIN] Cleanup complete\n");
    return MOSQ_ERR_SUCCESS;
}
