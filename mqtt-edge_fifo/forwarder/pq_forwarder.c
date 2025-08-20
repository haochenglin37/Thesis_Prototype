/*
 * 雙 FIFO 優先級 MQTT 轉發器 - 使用 Paho MQTT C 客戶端
 * 優先處理 HIGH priority FIFO，然後處理 LOW priority FIFO
 *
 * 編譯:
 *   gcc -o dual_fifo_forwarder dual_fifo_forwarder.c -lpaho-mqtt3c -ljson-c -lpthread
 *
 * 執行:
 *   sudo ip netns exec ns_forwarder ./dual_fifo_forwarder
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/time.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <sys/select.h>
#include <json-c/json.h>
#include "MQTTClient.h"

#define HIGH_FIFO_PATH   "/home/jason/mqtt-edge/forwarder/high_priority_queue.fifo"
#define LOW_FIFO_PATH    "/home/jason/mqtt-edge/forwarder/low_priority_queue.fifo"
#define MAIN_BROKER_HOST "tcp://192.168.254.139:1884"
#define CLIENT_ID        "dual_fifo_forwarder"
#define CSV_PATH         "/home/jason/mqtt-edge/logs/forwarder_performance.csv"
#define TOPIC            "forwarded/data"
#define QOS              1
#define BUF_SIZE         4096

static volatile int running = 1;
static int publish_failures = 0;
static size_t high_processed = 0;
static size_t low_processed = 0;

// 連線丟失回調
void connection_lost(void *context, char *cause) {
    printf("Connection lost: %s\n", cause ? cause : "unknown");
    // 不立即退出，嘗試重連
}

// 訊息傳遞回調
void delivered(void *context, MQTTClient_deliveryToken dt) {
    // QoS 1 傳遞確認
}

// 信號處理器
static void signal_handler(int signum) {
    printf("\nReceived signal %d, shutting down...\n", signum);
    running = 0;
}

// 取得當前時間（秒，微秒精度）
static double now_sec() {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec + tv.tv_usec / 1e6;
}

// 檢查是否在正確的 namespace 中
int check_namespace() {
    FILE *f = popen("ip netns identify $$", "r");
    if (!f) return 0;
    
    char ns[256] = {0};
    fgets(ns, sizeof(ns), f);
    pclose(f);
    
    // 移除換行符
    char *newline = strchr(ns, '\n');
    if (newline) *newline = '\0';
    
    return strcmp(ns, "ns_forwarder") == 0;
}

// 取得網路介面 IP
void get_forwarder_ip(char *ip_buf, size_t buf_size) {
    FILE *f = popen("ip addr show veth_fwd_ns | grep 'inet ' | awk '{print $2}' | cut -d/ -f1", "r");
    if (f) {
        fgets(ip_buf, buf_size, f);
        pclose(f);
        // 移除換行符
        char *newline = strchr(ip_buf, '\n');
        if (newline) *newline = '\0';
    } else {
        strcpy(ip_buf, "192.168.100.2");
    }
}

// 處理單個訊息
int process_message(MQTTClient client, const char *line, const char *priority, FILE *csv) {
    if (!line || strlen(line) == 0) return 0;
    
    double enqueue_ts = now_sec();
    double start_forward_ts = now_sec();
    
    printf("[%s] Processing %s priority message\n", 
           priority, strcmp(priority, "HIGH") == 0 ? "HIGH" : "LOW");
    
    // 解析 JSON
    struct json_object *jobj = json_tokener_parse(line);
    const char *orig_ip = "unknown";
    int packet_count = 0;
    double orig_ts = 0.0;
    const char *msg_priority = "unknown";
    const char *payload = line;
    
    if (jobj) {
        struct json_object *tmp;
        if (json_object_object_get_ex(jobj, "ip", &tmp)) {
            orig_ip = json_object_get_string(tmp);
        }
        if (json_object_object_get_ex(jobj, "count", &tmp)) {
            packet_count = json_object_get_int(tmp);
        }
        if (json_object_object_get_ex(jobj, "timestamp", &tmp)) {
            orig_ts = json_object_get_double(tmp);
        }
        if (json_object_object_get_ex(jobj, "priority", &tmp)) {
            msg_priority = json_object_get_string(tmp);
        }
        
        // 增強 JSON（添加轉發器資訊）
        json_object_object_add(jobj, "forwarder_ip", json_object_new_string("192.168.100.2"));
        json_object_object_add(jobj, "forward_timestamp", json_object_new_double(start_forward_ts));
        
        payload = json_object_to_json_string(jobj);
    } else {
        printf("  -> WARNING: Invalid JSON, forwarding raw message\n");
    }
    
    // 使用 Paho 發布訊息
    MQTTClient_message pubmsg = MQTTClient_message_initializer;
    pubmsg.payload = (char *)payload;
    pubmsg.payloadlen = (int)strlen(payload);
    pubmsg.qos = QOS;
    pubmsg.retained = 0;
    
    MQTTClient_deliveryToken token;
    int rc = MQTTClient_publishMessage(client, TOPIC, &pubmsg, &token);
    double end_forward_ts = now_sec();
    
    const char *fwd_res = "FAILED";
    if (rc == MQTTCLIENT_SUCCESS) {
        fwd_res = "SUCCESS";
        printf("  -> SUCCESS: Forwarded %s priority to main broker\n", priority);
        
        if (strcmp(priority, "HIGH") == 0) {
            high_processed++;
        } else {
            low_processed++;
        }
    } else {
        publish_failures++;
        printf("  -> FAILED: Could not forward %s priority (code: %d)\n", priority, rc);
        
        // 檢查連線狀態
        if (!MQTTClient_isConnected(client)) {
            printf("  -> Connection lost, will attempt reconnect\n");
        }
    }
    
    double forward_duration_ms = (end_forward_ts - start_forward_ts) * 1000.0;
    
    // 寫入 CSV
    fprintf(csv, "%.6f,%.6f,%.6f,%s,%d,%.6f,%s,%.3f,%s\n",
            enqueue_ts, start_forward_ts, end_forward_ts,
            orig_ip, packet_count, orig_ts,
            fwd_res, forward_duration_ms, msg_priority);
    fflush(csv);
    
    printf("  -> Logged to CSV: Duration=%.3fms, Priority=%s\n", 
           forward_duration_ms, msg_priority);
    
    if (jobj) json_object_put(jobj);
    return (rc == MQTTCLIENT_SUCCESS) ? 1 : 0;
}

int main() {
    // 設定信號處理器
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    
    printf("Dual FIFO Priority Forwarder starting...\n");
    
    // 檢查 namespace
    if (!check_namespace()) {
        fprintf(stderr, "ERROR: Must run in ns_forwarder namespace\n");
        fprintf(stderr, "Use: sudo ip netns exec ns_forwarder %s\n", "dual_fifo_forwarder");
        return 1;
    }
    
    // 顯示網路資訊
    char forwarder_ip[64];
    get_forwarder_ip(forwarder_ip, sizeof(forwarder_ip));
    printf("Forwarder IP: %s\n", forwarder_ip);
    printf("Target: %s\n", MAIN_BROKER_HOST);
    
    // 準備日誌目錄和 CSV 檔案
    system("mkdir -p /home/jason/mqtt-edge/logs");
    FILE *csv = fopen(CSV_PATH, "w");
    if (!csv) {
        perror("fopen CSV");
        return 1;
    }
    fprintf(csv, "enqueue_ts,start_forward_ts,end_forward_ts,original_ip,packet_count,original_timestamp,forward_result,forward_duration_ms,priority\n");
    fflush(csv);
    printf("Created/Reset CSV file: %s\n", CSV_PATH);
    
    // 檢查 FIFO 檔案
    if (access(HIGH_FIFO_PATH, F_OK) != 0) {
        fprintf(stderr, "ERROR: HIGH FIFO not found: %s\n", HIGH_FIFO_PATH);
        fclose(csv);
        return 1;
    }
    if (access(LOW_FIFO_PATH, F_OK) != 0) {
        fprintf(stderr, "ERROR: LOW FIFO not found: %s\n", LOW_FIFO_PATH);
        fclose(csv);
        return 1;
    }
    
    printf("Monitoring dual FIFO for messages...\n");
    printf("HIGH Priority: %s\n", HIGH_FIFO_PATH);
    printf("LOW Priority: %s\n", LOW_FIFO_PATH);
    
    // 初始化 Paho MQTT
    MQTTClient client;
    MQTTClient_create(&client, MAIN_BROKER_HOST, CLIENT_ID,
                      MQTTCLIENT_PERSISTENCE_NONE, NULL);
    MQTTClient_setCallbacks(client, NULL, connection_lost, NULL, delivered);
    
    MQTTClient_connectOptions conn_opts = MQTTClient_connectOptions_initializer;
    conn_opts.keepAliveInterval = 20;
    conn_opts.cleansession = 1;
    conn_opts.connectTimeout = 10;
    
    printf("Connecting to broker...\n");
    int connect_rc = MQTTClient_connect(client, &conn_opts);
    if (connect_rc != MQTTCLIENT_SUCCESS) {
        fprintf(stderr, "Failed to connect to broker (code: %d)\n", connect_rc);
        fclose(csv);
        return 1;
    }
    printf("Connected to broker successfully\n");
    
    // 開啟 FIFO 檔案 - 使用阻塞模式避免 EOF 問題
    printf("Opening FIFO files...\n");
    int high_fd = open(HIGH_FIFO_PATH, O_RDONLY);  // 移除 O_NONBLOCK
    int low_fd = open(LOW_FIFO_PATH, O_RDONLY);    // 移除 O_NONBLOCK
    
    if (high_fd < 0 || low_fd < 0) {
        perror("open FIFO");
        fclose(csv);
        return 1;
    }
    
    // 設為非阻塞模式用於 select
    int flags_high = fcntl(high_fd, F_GETFL);
    int flags_low = fcntl(low_fd, F_GETFL);
    fcntl(high_fd, F_SETFL, flags_high | O_NONBLOCK);
    fcntl(low_fd, F_SETFL, flags_low | O_NONBLOCK);
    
    FILE *high_file = fdopen(high_fd, "r");
    FILE *low_file = fdopen(low_fd, "r");
    
    if (!high_file || !low_file) {
        perror("fdopen");
        fclose(csv);
        return 1;
    }
    
    printf("FIFO files opened successfully\n");
    
    printf("Starting priority processing loop...\n");
    
    char high_buf[BUF_SIZE];
    char low_buf[BUF_SIZE];
    size_t total_messages = 0;
    
    // 主要處理迴圈
    size_t debug_cycle = 0;
    while (running) {
        int processed_this_cycle = 0;
        debug_cycle++;
        
        // 首先檢查 HIGH priority FIFO
        errno = 0;
        if (fgets(high_buf, sizeof(high_buf), high_file)) {
            // 移除換行符
            size_t len = strlen(high_buf);
            if (len > 0 && high_buf[len-1] == '\n') {
                high_buf[len-1] = '\0';
            }
            
            if (strlen(high_buf) > 0) {
                process_message(client, high_buf, "HIGH", csv);
                total_messages++;
                processed_this_cycle = 1;
            }
        } else {
            // 偵錯：記錄 HIGH FIFO 讀取失敗
            if (debug_cycle % 1000 == 0) {  // 每1000個週期記錄一次
                if (errno != 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
                    printf("[DEBUG] HIGH FIFO read error: %s\n", strerror(errno));
                }
            }
        }
        
        // 檢查 LOW priority FIFO（無論 HIGH 是否有資料都檢查）
        errno = 0;
        if (fgets(low_buf, sizeof(low_buf), low_file)) {
            // 移除換行符
            size_t len = strlen(low_buf);
            if (len > 0 && low_buf[len-1] == '\n') {
                low_buf[len-1] = '\0';
            }
            
            if (strlen(low_buf) > 0) {
                process_message(client, low_buf, "LOW", csv);
                total_messages++;
                processed_this_cycle = 1;
            }
        } else {
            // 偵錯：記錄 LOW FIFO 讀取失敗
            if (debug_cycle % 1000 == 0) {  // 每1000個週期記錄一次
                if (errno != 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
                    printf("[DEBUG] LOW FIFO read error: %s\n", strerror(errno));
                }
            }
        }
        
        // 檢查連線狀態和重連
        if (!MQTTClient_isConnected(client)) {
            printf("Connection lost, attempting to reconnect...\n");
            int reconnect_rc = MQTTClient_connect(client, &conn_opts);
            if (reconnect_rc == MQTTCLIENT_SUCCESS) {
                printf("Reconnected successfully\n");
            } else {
                fprintf(stderr, "Reconnection failed (code: %d)\n", reconnect_rc);
            }
        }
        
        // 定期顯示統計資訊
        if (total_messages % 50 == 0 && total_messages > 0) {
            printf("Processed %zu total messages (HIGH: %zu, LOW: %zu, Failures: %d)\n",
                   total_messages, high_processed, low_processed, publish_failures);
        }
        
        // 如果這個週期沒有處理任何訊息，稍微暫停避免 CPU 忙碌等待
        //if (!processed_this_cycle) {
        //    usleep(1000); // 1ms（select 已經有超時，這裡可以更短）
        //}
        
        // 失敗保護
        if (publish_failures > 100) {
            fprintf(stderr, "Too many publish failures (%d), exiting\n", publish_failures);
            break;
        }
    }
    
    // 清理資源
    printf("Shutting down gracefully...\n");
    printf("Final statistics: Total=%zu, HIGH=%zu, LOW=%zu, Failures=%d\n",
           total_messages, high_processed, low_processed, publish_failures);
    
    fclose(high_file);
    fclose(low_file);
    MQTTClient_disconnect(client, 1000);
    MQTTClient_destroy(&client);
    fclose(csv);
    
    printf("Shutdown complete\n");
    return 0;
}
