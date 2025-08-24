# MQTT Edge FIFO

此目錄提供以雙 FIFO 為核心的 MQTT 邊緣處理流程，將邊緣 broker 接收到的訊息依政策分級，透過獨立 namespace 的轉發器送往主 broker。

## 組成

- `plugin/`：Mosquitto v5 插件，採三階段管線設計；Stage 1 先記錄訊息時間戳，Stage 2 呼叫政策 API 後依結果寫入 `high_priority_queue.fifo` 或 `low_priority_queue.fifo`，Stage 3 外部轉發器讀取 FIFO 並發佈。
- `forwarder/`：包含 `pq_forwarder.c`、`new_dual.c` 等程式，優先處理高優先序 FIFO，再處理低優先序 FIFO，並發布到主 broker `tcp://192.168.254.139:1884`。
- `setup_ip_isolation.sh`：建立 `ns_forwarder` network namespace，配置 192.168.100.2 以隔離轉發器。
- `config/mosquitto.conf`：範例設定，載入 `simple_edge_plugin.so` 插件。
- `test_mqtt_connection.sh`：在 namespace 中檢查與主 broker 的連線與發佈功能。

## 編譯插件

```bash
cd plugin
make            # 產生 simple_edge_plugin.so
```

## 建立隔離網路環境

```bash
sudo ./setup_ip_isolation.sh
```

## 執行流程

1. 使用 `config/mosquitto.conf` 啟動邊緣 Broker：
   ```bash
   mosquitto -c config/mosquitto.conf
   ```
2. 在 `forwarder` 內編譯並執行轉發器：
   ```bash
   gcc -o dual_fifo_forwarder forwarder/pq_forwarder.c -lpaho-mqtt3c -ljson-c -lpthread
   sudo ip netns exec ns_forwarder ./dual_fifo_forwarder
   ```
   轉發器優先處理 `high_priority_queue.fifo` 再處理 `low_priority_queue.fifo`，成功轉發會記錄在 `logs/forwarder_performance.csv`。
3. 可執行 `./test_mqtt_connection.sh` 驗證隔離 IP 的連線與發佈能力。

## 日誌

- 插件詳細記錄：`/home/jason/mqtt-edge/logs/edge_plugin.csv`
- 轉發器效能：`/home/jason/mqtt-edge/logs/forwarder_performance.csv`
