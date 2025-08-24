# Thesis Prototype Overview

此專案整合 MQTT 邊緣節點的雙 FIFO 轉發系統、政策 API、五個感測器模擬，以及後處理工具，用於評估攻擊情境下的優先權機制。

## 目錄結構
- `mqtt-edge_fifo/`：Mosquitto 插件與雙 FIFO 轉發器。
- `API/`：政策 API，回傳 accept/reject 或 high/low/drop。
- `Normal_Sensor/`、`Mali_Sensor/`：正常感測器與洪水攻擊感測器。
- `Post_Process/`：整理日誌並產生圖表的腳本。

## 操作步驟
1. **編譯插件並建立隔離網路**
   ```bash
   cd mqtt-edge_fifo/plugin
   make
   cd ..
   sudo ./setup_ip_isolation.sh
   ```
2. **啟動邊緣 broker（載入插件）**
   ```bash
   mosquitto -c mqtt-edge_fifo/config/mosquitto.conf
   ```
3. **編譯並啟動轉發器讀取 FIFO**
   ```bash
   cd mqtt-edge_fifo/forwarder
   gcc -o dual_fifo_forwarder pq_forwarder.c -lpaho-mqtt3c -ljson-c -lpthread
   sudo ip netns exec ns_forwarder ./dual_fifo_forwarder
   ```
4. **啟動政策 API**
   ```bash
   cd API
   python pq.py        # 或 rule.py
   ```
5. **設定五個感測器發送訊息**
   - 四個正常感測器：
     ```bash
     python Normal_Sensor/sent.py --start "YYYY-MM-DD HH:MM:SS"
     ```
   - 一個惡意感測器進行洪水攻擊：
     ```bash
     python Mali_Sensor/sent.py --csv flood_intervals.csv --start "YYYY-MM-DD HH:MM:SS"
     ```
   所有感測器需連到邊緣 broker（可透過 `--broker`、`--port` 調整）。
6. **收集日誌**
   - 插件：`mqtt-edge_fifo/logs/edge_plugin.csv`
   - 轉發器：`mqtt-edge_fifo/logs/forwarder_performance.csv`
7. **後處理並產生圖表**
   ```bash
   cd Post_Process
   python merge_2.5.py    # 合併 CSV
   python bar_chart.py    # 生成圖表
   ```
   結果會輸出到 `Post_Process/Result/`。

## 備註
- 啟動感測器前請確保 broker、轉發器與 API 均已啟動。
- 依系統環境可能需要安裝 `libmosquitto-dev`、`libjson-c-dev` 等套件以編譯插件與轉發器。
