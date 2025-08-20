#!/bin/bash
# 簡化版雙 FIFO 轉發器 - 用阻塞讀取但輪詢檢查

HIGH_FIFO_PATH="/home/jason/mqtt-edge/forwarder/high_priority_queue.fifo"
LOW_FIFO_PATH="/home/jason/mqtt-edge/forwarder/low_priority_queue.fifo"
MAIN_BROKER_HOST="192.168.254.139"
MAIN_BROKER_PORT=1884
CSV_FILE="/home/jason/mqtt-edge/logs/forwarder_performance.csv"

echo "Simple Dual FIFO Forwarder starting..."

# 檢查是否在 namespace 中
if [[ "$(ip netns identify $$)" != "ns_forwarder" ]]; then
    echo "ERROR: Must run in ns_forwarder namespace"
    echo "Use: sudo ip netns exec ns_forwarder $0"
    exit 1
fi

# 顯示網路資訊
echo "Forwarder IP: $(ip addr show veth_fwd_ns | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)"
echo "Target: $MAIN_BROKER_HOST:$MAIN_BROKER_PORT"

# 創建 CSV 標題
mkdir -p /home/jason/mqtt-edge/logs
echo "enqueue_ts,start_forward_ts,end_forward_ts,original_ip,packet_count,original_timestamp,forward_result,forward_duration_ms,priority" > "$CSV_FILE"
echo "Created/Reset CSV file: $CSV_FILE"

# 檢查 FIFO
if [[ ! -p "$HIGH_FIFO_PATH" ]]; then
    echo "ERROR: HIGH FIFO not found: $HIGH_FIFO_PATH"
    exit 1
fi

if [[ ! -p "$LOW_FIFO_PATH" ]]; then
    echo "ERROR: LOW FIFO not found: $LOW_FIFO_PATH"
    exit 1
fi

echo "Monitoring dual FIFO for messages..."
echo "HIGH Priority: $HIGH_FIFO_PATH"
echo "LOW Priority: $LOW_FIFO_PATH"

# 處理單個訊息的函數
process_message() {
    local line="$1"
    local priority="$2"
    
    if [[ -z "$line" ]]; then
        return 1
    fi
    
    # 記錄時間戳
    local enqueue_ts=$(date +%s.%6N)
    local start_forward_ts=$(date +%s.%6N)
    
    echo "[$(date '+%H:%M:%S')] Processing $priority: $line"
    
    # 解析 JSON
    if echo "$line" | jq empty 2>/dev/null; then
        local original_ip=$(echo "$line" | jq -r '.ip // "unknown"')
        local packet_count=$(echo "$line" | jq -r '.count // "0"')
        local original_timestamp=$(echo "$line" | jq -r '.timestamp // "0"')
        local msg_priority=$(echo "$line" | jq -r '.priority // "unknown"')
        
        if [[ "$original_ip" != "unknown" && "$packet_count" != "0" ]]; then
            # 構建轉發訊息
            local forward_data=$(echo "$line" | jq --arg fwd_ip "192.168.100.2" --arg fwd_ts "$start_forward_ts" '. + {forwarder_ip: $fwd_ip, forward_timestamp: ($fwd_ts | tonumber)}')
            
            # 轉發
            local forward_result="FAILED"
            if mosquitto_pub -h "$MAIN_BROKER_HOST" -p "$MAIN_BROKER_PORT" -t "forwarded/data" -m "$forward_data" 2>/dev/null; then
                forward_result="SUCCESS"
                echo "  -> SUCCESS: Forwarded $priority priority to main broker"
            else
                echo "  -> FAILED: Could not forward $priority priority"
            fi
            
            local end_forward_ts=$(date +%s.%6N)
            
            # 計算持續時間
            local forward_duration_ms=$(awk "BEGIN {printf \"%.3f\", ($end_forward_ts - $start_forward_ts) * 1000}")
            
            # 寫入 CSV
            echo "$enqueue_ts,$start_forward_ts,$end_forward_ts,$original_ip,$packet_count,$original_timestamp,$forward_result,$forward_duration_ms,$msg_priority" >> "$CSV_FILE"
            
            echo "  -> Logged to CSV: Duration=${forward_duration_ms}ms, Priority=$msg_priority"
        else
            echo "  -> ERROR: Missing required fields in $priority message"
        fi
    else
        echo "  -> ERROR: Invalid JSON in $priority message"
    fi
}

# 檢查 FIFO 是否有資料的函數（使用 test 命令）
has_data() {
    local fifo="$1"
    # 使用 test 命令檢查 FIFO 是否有資料可讀
    test -r "$fifo"
}

# 非阻塞讀取函數 - 使用 dd 方式
read_nonblock() {
    local fifo="$1"
    local line
    
    # 嘗試讀取一行，如果沒有資料則立即返回
    if IFS= read -r -t 0.01 line < "$fifo" 2>/dev/null; then
        echo "$line"
        return 0
    else
        return 1
    fi
}

message_count=0
high_processed=0
low_processed=0

echo "Starting priority processing loop..."

exec 3< "$HIGH_FIFO_PATH"
exec 4< "$LOW_FIFO_PATH"

# 主循環中不要關閉連接，只是輪流檢查
while true; do
    # 檢查 HIGH FIFO（不關閉連接）
    if read -t 0.01 -u 3 high_line 2>/dev/null; then
        process_message "$high_line" "HIGH"
        continue
    fi
    
    # 檢查 LOW FIFO（不關閉連接）
    if read -t 0.01 -u 4 low_line 2>/dev/null; then
        process_message "$low_line" "LOW"
        continue
    fi
    
    sleep 0.1
done
