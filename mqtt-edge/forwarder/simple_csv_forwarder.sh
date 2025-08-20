#!/bin/bash
# 睡眠測試版 CSV 記錄轉發器
FIFO_PATH="/home/jason/mqtt-edge/forwarder/message_queue.fifo"
MAIN_BROKER_HOST="192.168.254.139"
MAIN_BROKER_PORT=1884
CSV_FILE="/home/jason/mqtt-edge/logs/forwarder_performance.csv"

echo "Sleep Test CSV Forwarder starting..."

# 檢查是否在 namespace 中
if [[ "$(ip netns identify $$)" != "ns_forwarder" ]]; then
    echo "ERROR: Must run in ns_forwarder namespace"
    echo "Use: sudo ip netns exec ns_forwarder $0"
    exit 1
fi

# 顯示網路資訊
echo "Forwarder IP: $(ip addr show veth_fwd_ns | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)"
echo "Target: $MAIN_BROKER_HOST:$MAIN_BROKER_PORT"
echo "MODE: Sleep Test (5ms fixed delay)"

# 創建 CSV 標題 - 每次啟動都重新創建
mkdir -p /home/jason/mqtt-edge/logs
echo "enqueue_ts,start_forward_ts,end_forward_ts,original_ip,packet_count,original_timestamp,forward_result,forward_duration_ms" > "$CSV_FILE"
echo "Created/Reset CSV file: $CSV_FILE"

# 檢查 FIFO
if [[ ! -p "$FIFO_PATH" ]]; then
    echo "ERROR: FIFO not found: $FIFO_PATH"
    exit 1
fi

echo "Monitoring FIFO for messages..."

# 主循環 - 睡眠測試版本
exec 3< "$FIFO_PATH"
message_count=0

while IFS= read -r line <&3; do
    if [[ -z "$line" ]]; then
        continue
    fi
    
    # 記錄時間戳
    start_forward_ts=$(date +%s.%6N)
    
    ((message_count++))
    echo "[$message_count] Processing: $line"
    
    # 解析 JSON
    if echo "$line" | jq empty 2>/dev/null; then
        enqueue_ts=$(echo "$line" | jq -r '.enqueue_ts // "0"')
        original_ip=$(echo "$line" | jq -r '.ip // "unknown"')
        packet_count=$(echo "$line" | jq -r '.count // "0"')
        original_timestamp=$(echo "$line" | jq -r '.timestamp // "0"')
        
        if [[ "$original_ip" != "unknown" && "$packet_count" != "0" ]]; then
            # ===== 測試用：替換轉發為睡眠 =====
            sleep 0.005  # 5ms 固定延遲
            forward_result="SUCCESS"
            echo "  -> SUCCESS: Simulated 5ms processing"
            # ===== 測試用代碼結束 =====
            
            end_forward_ts=$(date +%s.%6N)
            
            # 計算持續時間
            forward_duration_ms=$(awk "BEGIN {printf \"%.3f\", ($end_forward_ts - $start_forward_ts) * 1000}")
            
            # 寫入 CSV
            echo "$enqueue_ts,$start_forward_ts,$end_forward_ts,$original_ip,$packet_count,$original_timestamp,$forward_result,$forward_duration_ms" >> "$CSV_FILE"
            
            echo "  -> Logged to CSV: Duration=${forward_duration_ms}ms"
        else
            echo "  -> ERROR: Missing required fields"
        fi
    else
        echo "  -> ERROR: Invalid JSON"
    fi
    
    # 每10條訊息顯示統計
    if (( message_count % 10 == 0 )); then
        echo "=== Processed $message_count messages ==="
    fi
done

echo "Sleep test completed. Results in: $CSV_FILE"
