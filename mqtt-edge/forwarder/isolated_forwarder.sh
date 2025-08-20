#!/bin/bash

# 隔離 IP 的 MQTT 轉發器
# 從 FIFO 讀取訊息，使用 192.168.100.2 轉發到主 broker

FIFO_PATH="/home/jason/mqtt-edge/forwarder/message_queue.fifo"
MAIN_BROKER_HOST="192.168.254.139"
MAIN_BROKER_PORT=1884
TOPIC_PREFIX="forwarded"
LOG_FILE="/home/jason/mqtt-edge/logs/forwarder.log"
CSV_FILE="/home/jason/mqtt-edge/logs/forwarder_performance.csv"

# 統計變數
TOTAL_FORWARDED=0
TOTAL_ERRORS=0
START_TIME=$(date +%s)

# 顏色輸出
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $1"
    echo -e "${GREEN}${msg}${NC}"
    echo "$msg" >> "$LOG_FILE"
}

log_error() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1"
    echo -e "${RED}${msg}${NC}"
    echo "$msg" >> "$LOG_FILE"
}

log_warn() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $1"
    echo -e "${YELLOW}${msg}${NC}"
    echo "$msg" >> "$LOG_FILE"
}

# 檢查是否在正確的 namespace 中運行
check_namespace() {
    local current_ns=$(ip netns identify $$)
    if [[ "$current_ns" != "ns_forwarder" ]]; then
        log_error "This forwarder must run in ns_forwarder namespace"
        log_error "Use: sudo ip netns exec ns_forwarder $0"
        exit 1
    fi
    
    local forwarder_ip=$(ip addr show veth_fwd_ns | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
    log_info "Running in namespace with IP: $forwarder_ip"
}

# 檢查依賴
check_dependencies() {
    log_info "Checking dependencies..."
    
    if ! command -v mosquitto_pub &> /dev/null; then
        log_error "mosquitto_pub not found"
        exit 1
    fi
    
    if ! command -v jq &> /dev/null; then
        log_error "jq not found"
        exit 1
    fi
    
    log_info "Dependencies OK"
}

# 測試 MQTT 連接
test_mqtt_connection() {
    log_info "Testing MQTT broker connection..."
    
    if mosquitto_pub -h "$MAIN_BROKER_HOST" -p "$MAIN_BROKER_PORT" \
        -t "$TOPIC_PREFIX/test" -m "forwarder_start_$(date +%s)" 2>/dev/null; then
        log_info "MQTT broker connection successful"
    else
        log_error "Cannot connect to MQTT broker at $MAIN_BROKER_HOST:$MAIN_BROKER_PORT"
        exit 1
    fi
}

# 初始化日誌文件
init_logs() {
    mkdir -p /home/jason/mqtt-edge/logs
    
    # 創建 CSV 標題（如果文件不存在）
    if [[ ! -f "$CSV_FILE" ]]; then
        echo "enqueue_ts,start_forward_ts,end_forward_ts,original_ip,packet_count,original_timestamp,forward_result,forward_duration_ms,api_to_forward_delay_ms" > "$CSV_FILE"
        log_info "Created CSV file: $CSV_FILE"
    fi
}
    log_info "Initializing FIFO: $FIFO_PATH"
    
    if [[ ! -p "$FIFO_PATH" ]]; then
        log_error "FIFO not found: $FIFO_PATH"
        exit 1
    fi
    
    log_info "FIFO ready"
}

# 處理轉發訊息
forward_message() {
    local raw_message="$1"
    local enqueue_ts=$(date +%s.%6N)  # 從 FIFO 讀取的時間
    
    # 跳過空訊息
    if [[ -z "$raw_message" ]]; then
        return
    fi
    
    # 驗證 JSON 格式
    if ! echo "$raw_message" | jq empty 2>/dev/null; then
        log_warn "Invalid JSON: $raw_message"
        ((TOTAL_ERRORS++))
        return
    fi
    
    # 提取原始資料
    local original_ip=$(echo "$raw_message" | jq -r '.ip // "unknown"')
    local packet_count=$(echo "$raw_message" | jq -r '.count // "0"')
    local original_timestamp=$(echo "$raw_message" | jq -r '.timestamp // "0"')
    
    # 檢查必要欄位
    if [[ "$original_ip" == "unknown" || "$packet_count" == "0" ]]; then
        log_warn "Missing required fields: $raw_message"
        ((TOTAL_ERRORS++))
        return
    fi
    
    # 開始轉發時間戳
    local start_forward_ts=$(date +%s.%6N)
    
    # 構建轉發訊息
    local forward_data=$(jq -n \
        --arg orig_ip "$original_ip" \
        --arg count "$packet_count" \
        --arg orig_ts "$original_timestamp" \
        --arg fwd_ts "$start_forward_ts" \
        --arg fwd_ip "192.168.100.2" \
        --arg enq_ts "$enqueue_ts" \
        '{
            original_ip: $orig_ip,
            packet_count: ($count | tonumber),
            original_timestamp: ($orig_ts | tonumber),
            forward_timestamp: ($fwd_ts | tonumber),
            forwarder_ip: $fwd_ip,
            enqueue_timestamp: ($enq_ts | tonumber)
        }')
    
    # 轉發到主 broker
    local topic="$TOPIC_PREFIX/data"
    local forward_result="FAILED"
    
    if mosquitto_pub -h "$MAIN_BROKER_HOST" -p "$MAIN_BROKER_PORT" \
        -t "$topic" -m "$forward_data" 2>/dev/null; then
        
        forward_result="SUCCESS"
        ((TOTAL_FORWARDED++))
        
    else
        ((TOTAL_ERRORS++))
        log_error "Failed to forward: IP=$original_ip, Count=$packet_count"
    fi
    
    # 結束轉發時間戳
    local end_forward_ts=$(date +%s.%6N)
    
    # 記錄到 CSV
    log_csv_record "$enqueue_ts" "$start_forward_ts" "$end_forward_ts" \
                   "$original_ip" "$packet_count" "$original_timestamp" "$forward_result"
    
    # 控制台輸出
    local duration_ms=$(echo "($end_forward_ts - $start_forward_ts) * 1000" | bc -l)
    log_info "Forwarded #$TOTAL_FORWARDED: IP=$original_ip, Count=$packet_count, Duration=${duration_ms}ms, Result=$forward_result"
    
    # 統計輸出
    if (( TOTAL_FORWARDED % 50 == 0 )); then
        local runtime=$(($(date +%s) - START_TIME))
        local rate=$(echo "scale=2; $TOTAL_FORWARDED / $runtime" | bc -l 2>/dev/null || echo "0")
        log_info "Stats: Forwarded=$TOTAL_FORWARDED, Errors=$TOTAL_ERRORS, Rate=${rate}/s"
    fi
}

# 主程式
main() {
    log_info "MQTT Isolated Forwarder starting..."
    
    # 初始化檢查
    check_namespace
    check_dependencies
    init_logs
    test_mqtt_connection
    init_fifo
    
    log_info "Forwarder ready - monitoring FIFO for messages..."
    log_info "Source: Edge Broker (192.168.254.191)"
    log_info "Target: Main Broker ($MAIN_BROKER_HOST:$MAIN_BROKER_PORT)"
    log_info "Forwarder IP: 192.168.100.2 (isolated)"
    
    # 主循環：讀取 FIFO
    exec 3< "$FIFO_PATH"
    while IFS= read -r line <&3; do
        forward_message "$line"
    done
    
    log_info "Forwarder stopped"
}

# 信號處理
cleanup() {
    local runtime=$(($(date +%s) - START_TIME))
    log_info "Shutting down..."
    log_info "Final stats: Forwarded=$TOTAL_FORWARDED, Errors=$TOTAL_ERRORS, Runtime=${runtime}s"
    exit 0
}

trap cleanup SIGTERM SIGINT

# 執行主程式
main "$@"
