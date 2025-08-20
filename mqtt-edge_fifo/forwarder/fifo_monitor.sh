#!/bin/bash

# FIFO 監控程式 - 第一階段測試用

FIFO_PATH="/home/jason/mqtt-edge/forwarder/message_queue.fifo"
LOG_FILE="/home/jason/mqtt-edge/logs/fifo_monitor.log"

echo "FIFO Monitor starting..."
echo "Monitoring: $FIFO_PATH"
echo "Log file: $LOG_FILE"

# 確保目錄存在
mkdir -p /home/jason/mqtt-edge/logs

# 檢查 FIFO 是否存在
if [[ ! -p "$FIFO_PATH" ]]; then
    echo "Creating FIFO: $FIFO_PATH"
    mkfifo "$FIFO_PATH"
fi

# 設定權限
chmod 666 "$FIFO_PATH"

echo "Waiting for messages..."
echo "$(date): FIFO monitor started" >> "$LOG_FILE"

# 讀取 FIFO 訊息
exec 3< "$FIFO_PATH"
message_count=0

while IFS= read -r line <&3; do
    ((message_count++))
    timestamp=$(date '+%Y-%m-%d %H:%M:%S.%3N')
    
    echo "[$timestamp] Message #$message_count: $line"
    echo "[$timestamp] Message #$message_count: $line" >> "$LOG_FILE"
    
    # 檢查 JSON 格式
    if echo "$line" | jq empty 2>/dev/null; then
        ip=$(echo "$line" | jq -r '.ip // "unknown"')
        count=$(echo "$line" | jq -r '.count // "0"')
        echo "  -> Parsed: IP=$ip, Count=$count"
    else
        echo "  -> Warning: Invalid JSON format"
    fi
    
    # 每10條訊息顯示統計
    if (( message_count % 10 == 0 )); then
        echo "=== Processed $message_count messages ==="
    fi
done

echo "FIFO monitor stopped"
