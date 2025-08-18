# Mali Sensor

1. 產生封包到達間隔  
   `time_in.py`
   - Input：無
   - Output：`delta_ip5.csv`，產生封包到達間隔【F:Mali_Sensor/time_in.py†L4-L15】
   - Parameters：`lambda_rate`（到達率）、`total_messages`（封包數量）、`seed`（隨機種子）、`output_filename`

2. 產生洪水攻擊間隔  
   `flood.py`
   - Input：無
   - Output：`flood_intervals.csv` 或 `burst_flood_intervals.csv`，模擬洪水攻擊【F:Mali_Sensor/flood.py†L5-L91】
   - Parameters：`rate_per_second`（速率）、`duration_seconds`（持續時間）、`output_filename`、`seed`、`mode`、`burst_config`【F:Mali_Sensor/flood.py†L93-L106】

3. 合併正常流量與攻擊  
   `merge.py`
   - Input：正常流量CSV、Flood攻擊CSV、攻擊時間點
   - Output：`merged_traffic.csv`，整合事件與統計資料【F:Mali_Sensor/merge.py†L31-L116】【F:Mali_Sensor/merge.py†L163-L174】
   - Parameters：`normal`、`flood`、`attack-times`、`output`、`simple`

4. 發送攻擊流量  
   `sent.py`
   - Input：CSV間隔檔案
   - Output：無，依間隔發送MQTT訊息【F:Mali_Sensor/sent.py†L18-L106】
   - Parameters：`csv`、`broker`、`port`、`topic`、`start`【F:Mali_Sensor/sent.py†L107-L133】
