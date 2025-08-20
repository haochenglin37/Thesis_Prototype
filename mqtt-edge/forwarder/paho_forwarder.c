/*
 * C-based MQTT Forwarder using Paho MQTT C client and json-c
 * Reads JSON lines from a named FIFO, augments payload, publishes via one persistent MQTT connection,
 * and logs timings to CSV.
 *
 * Compile with:
 *   gcc -o forwarder_paho forwarder_paho.c -lpaho-mqtt3c -ljson-c -lpthread
 *
 * Run inside namespace:
 *   sudo ip netns exec ns_forwarder ./forwarder_paho
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
#include <json-c/json.h>
#include "MQTTClient.h"

#define FIFO_PATH        "/home/jason/mqtt-edge/forwarder/message_queue.fifo"
#define MAIN_BROKER_HOST "tcp://192.168.254.139:1884"
#define CLIENT_ID        "forwarder_paho"
#define CSV_PATH         "/home/jason/mqtt-edge/logs/forwarder_performance.csv"
#define TOPIC            "forwarded/data"
#define QOS              1
#define BUF_SIZE         4096

static volatile int running = 1;
static int publish_failures = 0;

// Connection lost callback
void connection_lost(void *context, char *cause) {
    printf("Connection lost: %s\n", cause ? cause : "unknown");
    running = 0;
}

// Message delivery callback for QoS 1
void delivered(void *context, MQTTClient_deliveryToken dt) {
    // Optional: track delivery confirmations
}

// Signal handler for graceful shutdown
static void signal_handler(int signum) {
    printf("\nReceived signal %d, shutting down...\n", signum);
    running = 0;
}

// get current time in seconds with microsecond precision
static double now_sec(){
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec + tv.tv_usec / 1e6;
}

int main(){
    // Setup signal handlers
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    // Ensure log directory exists
    system("mkdir -p /home/jason/mqtt-edge/logs");

    // Open CSV file
    FILE *csv = fopen(CSV_PATH, "w");
    if(!csv){ perror("fopen CSV"); return 1; }
    fprintf(csv, "read_ts,start_forward_ts,end_forward_ts,original_ip,packet_count,original_timestamp,forward_result,forward_duration_ms\n");
    fflush(csv);

    // Initialize Paho MQTT
    MQTTClient client;
    MQTTClient_create(&client, MAIN_BROKER_HOST, CLIENT_ID,
                      MQTTCLIENT_PERSISTENCE_NONE, NULL);
    
    // Set callbacks
    MQTTClient_setCallbacks(client, NULL, connection_lost, NULL, delivered);
    
    MQTTClient_connectOptions conn_opts = MQTTClient_connectOptions_initializer;
    conn_opts.keepAliveInterval = 20;
    conn_opts.cleansession = 1;
    conn_opts.connectTimeout = 10;  // 10 second timeout
    
    printf("Connecting to broker at %s...\n", MAIN_BROKER_HOST);
    int connect_rc = MQTTClient_connect(client, &conn_opts);
    if(connect_rc != MQTTCLIENT_SUCCESS){
        fprintf(stderr, "Failed to connect to broker at %s (code: %d)\n", MAIN_BROKER_HOST, connect_rc);
        fclose(csv);
        return 1;
    }
    printf("Connected to broker successfully\n");

    // Create and open FIFO
    if(access(FIFO_PATH, F_OK) != 0){ 
        if(mkfifo(FIFO_PATH, 0666) != 0) {
            perror("mkfifo");
            fclose(csv);
            return 1;
        }
    }
    
    printf("Opening FIFO at %s...\n", FIFO_PATH);
    int fd = open(FIFO_PATH, O_RDONLY | O_NONBLOCK);
    if(fd < 0){ 
        perror("open FIFO"); 
        fclose(csv);
        return 1; 
    }
    
    // Remove O_NONBLOCK after opening to avoid busy waiting
    int flags = fcntl(fd, F_GETFL);
    fcntl(fd, F_SETFL, flags & ~O_NONBLOCK);
    
    FILE *f = fdopen(fd, "r");
    if(!f){ 
        perror("fdopen"); 
        close(fd);
        fclose(csv);
        return 1; 
    }
    printf("FIFO opened successfully\n");

    char buf[BUF_SIZE];
    size_t count = 0;
    
    while(running && fgets(buf, sizeof(buf), f)){
        double read_ts = now_sec();
        
        // Remove trailing newline
        size_t len = strlen(buf);
        if(len > 0 && buf[len-1] == '\n') {
            buf[len-1] = '\0';
        }
        
        // Skip empty lines
        if(strlen(buf) == 0) continue;
        
        double start_forward_ts = now_sec();
        count++;

        // Parse JSON
        struct json_object *jobj = json_tokener_parse(buf);
        const char *orig_ip = "";
        int packet_count = 0;
        double orig_ts = 0.0;
        const char *payload = buf; // fallback to original buffer
        
        if(jobj){
            struct json_object *tmp;
            if(json_object_object_get_ex(jobj, "ip", &tmp)) {
                orig_ip = json_object_get_string(tmp);
            }
            if(json_object_object_get_ex(jobj, "count", &tmp)) {
                packet_count = json_object_get_int(tmp);
            }
            if(json_object_object_get_ex(jobj, "timestamp", &tmp)) {
                orig_ts = json_object_get_double(tmp);
            }
            
            // Augment JSON
            json_object_object_add(jobj, "forwarder_ip", json_object_new_string("192.168.100.2"));
            json_object_object_add(jobj, "forward_timestamp", json_object_new_double(start_forward_ts));
            
            payload = json_object_to_json_string(jobj);
        } else {
            fprintf(stderr, "Warning: Failed to parse JSON, forwarding raw message\n");
        }

        // Publish via Paho with delivery token for QoS 1
        MQTTClient_message pubmsg = MQTTClient_message_initializer;
        pubmsg.payload = (char *)payload;
        pubmsg.payloadlen = (int)strlen(payload);
        pubmsg.qos = QOS;
        pubmsg.retained = 0;
        
        MQTTClient_deliveryToken token;
        int rc = MQTTClient_publishMessage(client, TOPIC, &pubmsg, &token);
        double end_forward_ts = now_sec();
        
        const char *fwd_res = "FAILED";
        if(rc == MQTTCLIENT_SUCCESS) {
            // For QoS 1, we could wait for delivery confirmation
            // int wait_rc = MQTTClient_waitForCompletion(client, token, 1000);
            // fwd_res = (wait_rc == MQTTCLIENT_SUCCESS) ? "SUCCESS" : "TIMEOUT";
            fwd_res = "SUCCESS";
        } else {
            publish_failures++;
            fprintf(stderr, "MQTT publish failed with code %d (total failures: %d)\n", rc, publish_failures);
            
            // Check if we're still connected
            if(!MQTTClient_isConnected(client)) {
                printf("Connection lost, attempting to reconnect...\n");
                int reconnect_rc = MQTTClient_connect(client, &conn_opts);
                if(reconnect_rc == MQTTCLIENT_SUCCESS) {
                    printf("Reconnected successfully\n");
                } else {
                    fprintf(stderr, "Reconnection failed with code %d\n", reconnect_rc);
                }
            }
        }

        
        double forward_duration_ms = (end_forward_ts - start_forward_ts) * 1000.0;

        // Log to CSV
        fprintf(csv, "%.6f,%.6f,%.6f,%s,%d,%.6f,%s,%.3f\n",
                read_ts, start_forward_ts, end_forward_ts,
                orig_ip, packet_count, orig_ts,
                fwd_res, forward_duration_ms);
        fflush(csv);

        //if(count % 10 == 0){
        //    printf("Processed %zu messages, last forward took %.3f ms (failures: %d)\n", 
        //           count, forward_duration_ms, publish_failures);
        //}
        
        if(jobj) json_object_put(jobj);
        
        // If too many failures, consider exiting
        if(publish_failures > 100) {
            fprintf(stderr, "Too many publish failures (%d), exiting\n", publish_failures);
            break;
        }
    }

    // Cleanup
    printf("Shutting down gracefully...\n");
    fclose(f);
    MQTTClient_disconnect(client, 1000);
    MQTTClient_destroy(&client);
    fclose(csv);
    printf("Shutdown complete\n");
    return 0;
}
