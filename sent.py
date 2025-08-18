import csv
import time
import json
import random
import argparse
from datetime import datetime, timedelta
import paho.mqtt.client as mqtt

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("成功連接到MQTT Broker")
    else:
        print(f"連接失敗，返回碼: {rc}")

def on_publish(client, userdata, mid):
    print(f"訊息已發布，Message ID: {mid}")

def send_mqtt_messages(csv_filename, broker_ip, broker_port, topic, start_time_str=None):
    # 讀取CSV檔案
    intervals = []
    try:
        with open(csv_filename, 'r') as csvfile:
            csv_reader = csv.DictReader(csvfile)
            for row in csv_reader:
                intervals.append(float(row['InterArrivalTime']))
        print(f"已讀取 {len(intervals)} 筆時間間隔資料")
    except FileNotFoundError:
        print(f"找不到檔案: {csv_filename}")
        return
    except Exception as e:
        print(f"讀取檔案時發生錯誤: {e}")
        return

    # 設定開始時間
    if start_time_str:
        try:
            start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            print("時間格式錯誤，請使用 YYYY-MM-DD HH:MM:SS 格式")
            return
    else:
        start_time = datetime.now()
    
    print(f"預定開始時間: {start_time}")
    
    # 等待到開始時間
    current_time = datetime.now()
    if start_time > current_time:
        wait_seconds = (start_time - current_time).total_seconds()
        print(f"等待 {wait_seconds:.2f} 秒後開始發送...")
        time.sleep(wait_seconds)

    # 建立MQTT客戶端
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_publish = on_publish

    try:
        # 連接到MQTT Broker
        print(f"正在連接到 {broker_ip}:{broker_port}")
        client.connect(broker_ip, broker_port, 60)
        client.loop_start()

        # 發送訊息
        message_count = 0
        actual_start_time = time.time()
        
        for interval in intervals:
            # 等待指定的時間間隔
            time.sleep(interval)
            
            # 生成感測器資料
            sensor_data = {
                "timestamp": datetime.now().isoformat(),
                "message_id": message_count + 1,
                "temperature": round(random.uniform(20.0, 30.0), 2),
                "humidity": round(random.uniform(40.0, 80.0), 2),
                "pressure": round(random.uniform(1000.0, 1050.0), 2)
            }
            
            # 發送MQTT訊息
            message = json.dumps(sensor_data)
            result = client.publish(topic, message)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                message_count += 1
                print(f"第 {message_count} 則訊息已發送: {sensor_data['timestamp']}")
            else:
                print(f"發送失敗，錯誤碼: {result.rc}")
        
        # 計算統計資訊
        total_time = time.time() - actual_start_time
        average_rate = message_count / total_time if total_time > 0 else 0
        
        print(f"\n發送完成!")
        print(f"總共發送: {message_count} 則訊息")
        print(f"總耗時: {total_time:.2f} 秒")
        print(f"平均發送率: {average_rate:.2f} 則/秒")
        
    except Exception as e:
        print(f"MQTT連接或發送時發生錯誤: {e}")
    finally:
        client.loop_stop()
        client.disconnect()
        print("已斷開MQTT連接")

def main():
    # 設定命令列參數解析器
    parser = argparse.ArgumentParser(description='從CSV讀取時間間隔並發送MQTT訊息')
    parser.add_argument('--csv', '-c', default='delta_ip5.csv', 
                       help='CSV檔案路徑 (預設: delta_ip5.csv)')
    parser.add_argument('--broker', '-b', default='192.168.254.174', 
                       help='MQTT Broker IP (預設: 192.168.254.174)')
    parser.add_argument('--port', '-p', type=int, default=1883, 
                       help='MQTT Broker Port (預設: 1883)')
    parser.add_argument('--topic', '-t', default='sensor/data', 
                       help='MQTT Topic (預設: sensor/data)')
    parser.add_argument('--start', '-s', 
                       help='開始時間，格式: YYYY-MM-DD HH:MM:SS (不指定則立即開始)')
    
    # 解析命令列參數
    args = parser.parse_args()
    
    # 顯示設定資訊
    print("=== 設定資訊 ===")
    print(f"CSV檔案: {args.csv}")
    print(f"MQTT Broker: {args.broker}:{args.port}")
    print(f"MQTT Topic: {args.topic}")
    print(f"開始時間: {args.start if args.start else '立即開始'}")
    print("================\n")
    
    # 執行發送
    send_mqtt_messages(args.csv, args.broker, args.port, args.topic, args.start)

if __name__ == "__main__":
    main()
