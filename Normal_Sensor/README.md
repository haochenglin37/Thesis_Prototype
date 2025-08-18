# Normal Sensor

1. 產生封包到達間隔  
   `time_in.py`
   - Input：無
   - Output：`delta_ip5.csv`，產生封包到達間隔【F:Normal_Sensor/time_in.py†L4-L15】
   - Parameters：`lambda_rate`（到達率）、`total_messages`（封包數量）、`seed`（隨機種子）、`output_filename`

2. 發送正常流量  
   `sent.py`
   - Input：CSV間隔檔案
   - Output：無，依間隔發送MQTT訊息【F:Normal_Sensor/sent.py†L18-L106】
   - Parameters：`csv`、`broker`、`port`、`topic`、`start`【F:Normal_Sensor/sent.py†L107-L133】
