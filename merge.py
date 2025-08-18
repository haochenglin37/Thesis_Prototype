import csv
import argparse
from datetime import datetime, timedelta

def read_csv_intervals(filename):
    """讀取CSV檔案中的時間間隔"""
    intervals = []
    try:
        with open(filename, 'r') as csvfile:
            csv_reader = csv.DictReader(csvfile)
            for row in csv_reader:
                intervals.append(float(row['InterArrivalTime']))
        print(f"從 {filename} 讀取了 {len(intervals)} 筆間隔資料")
        return intervals
    except FileNotFoundError:
        print(f"找不到檔案: {filename}")
        return []
    except Exception as e:
        print(f"讀取檔案 {filename} 時發生錯誤: {e}")
        return []

def calculate_cumulative_times(intervals):
    """計算累積時間點"""
    cumulative_times = []
    current_time = 0
    for interval in intervals:
        current_time += interval
        cumulative_times.append(current_time)
    return cumulative_times

def merge_traffic_with_attacks(normal_intervals, flood_intervals, attack_times, output_filename):
    """
    合併正常流量和flood攻擊
    
    Args:
        normal_intervals: 正常流量間隔列表
        flood_intervals: flood攻擊間隔列表
        attack_times: 攻擊開始時間列表 [300, 3000]
        output_filename: 輸出檔案名稱
    """
    
    # 計算正常流量的累積時間
    normal_cumulative = calculate_cumulative_times(normal_intervals)
    
    # 為每個攻擊時間點準備flood事件
    all_events = []
    
    # 添加正常流量事件
    for i, time_point in enumerate(normal_cumulative):
        all_events.append({
            'time': time_point,
            'type': 'normal',
            'message_id': i + 1,
            'source': 'normal_traffic'
        })
    
    # 為每個攻擊時間點添加flood事件
    for attack_start_time in attack_times:
        flood_cumulative_time = attack_start_time
        
        for i, flood_interval in enumerate(flood_intervals):
            flood_cumulative_time += flood_interval
            all_events.append({
                'time': flood_cumulative_time,
                'type': 'flood',
                'message_id': i + 1,
                'source': f'flood_attack_{attack_start_time}s'
            })
    
    # 按時間排序所有事件
    all_events.sort(key=lambda x: x['time'])
    
    # 計算新的間隔時間
    merged_intervals = []
    prev_time = 0
    
    for event in all_events:
        interval = event['time'] - prev_time
        merged_intervals.append({
            'InterArrivalTime': interval,
            'EventType': event['type'],
            'MessageID': event['message_id'],
            'Source': event['source'],
            'AbsoluteTime': event['time']
        })
        prev_time = event['time']
    
    # 寫入CSV檔案
    with open(output_filename, mode='w', newline='') as csvfile:
        fieldnames = ['InterArrivalTime', 'EventType', 'MessageID', 'Source', 'AbsoluteTime']
        csv_writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        csv_writer.writeheader()
        csv_writer.writerows(merged_intervals)
    
    # 統計資訊
    normal_count = sum(1 for event in all_events if event['type'] == 'normal')
    flood_count = sum(1 for event in all_events if event['type'] == 'flood')
    total_time = all_events[-1]['time'] if all_events else 0
    
    print(f"\n=== 合併結果 ===")
    print(f"輸出檔案: {output_filename}")
    print(f"總事件數: {len(all_events)}")
    print(f"正常流量事件: {normal_count}")
    print(f"Flood攻擊事件: {flood_count}")
    print(f"總持續時間: {total_time:.2f} 秒")
    print(f"平均事件頻率: {len(all_events)/total_time:.2f} 事件/秒")
    
    # 顯示攻擊時間點統計
    print(f"\n=== 攻擊時間點統計 ===")
    for attack_time in attack_times:
        attack_events = [e for e in all_events if e['source'] == f'flood_attack_{attack_time}s']
        if attack_events:
            attack_start = min(e['time'] for e in attack_events)
            attack_end = max(e['time'] for e in attack_events)
            attack_duration = attack_end - attack_start
            print(f"攻擊 {attack_time}s: 開始於 {attack_start:.2f}s, 結束於 {attack_end:.2f}s, 持續 {attack_duration:.2f}s, 事件數 {len(attack_events)}")

def create_simple_merged_csv(normal_intervals, flood_intervals, attack_times, output_filename):
    """
    創建簡化版本的合併CSV（只有InterArrivalTime欄位，便於現有程式使用）
    """
    # 計算正常流量的累積時間
    normal_cumulative = calculate_cumulative_times(normal_intervals)
    
    # 為每個攻擊時間點準備flood事件
    all_events = []
    
    # 添加正常流量事件
    for time_point in normal_cumulative:
        all_events.append({'time': time_point, 'type': 'normal'})
    
    # 為每個攻擊時間點添加flood事件
    for attack_start_time in attack_times:
        flood_cumulative_time = attack_start_time
        
        for flood_interval in flood_intervals:
            flood_cumulative_time += flood_interval
            all_events.append({'time': flood_cumulative_time, 'type': 'flood'})
    
    # 按時間排序所有事件
    all_events.sort(key=lambda x: x['time'])
    
    # 計算新的間隔時間
    intervals_only = []
    prev_time = 0
    
    for event in all_events:
        interval = event['time'] - prev_time
        intervals_only.append(interval)
        prev_time = event['time']
    
    # 寫入簡化版CSV檔案
    simple_filename = output_filename.replace('.csv', '_simple.csv')
    with open(simple_filename, mode='w', newline='') as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(["InterArrivalTime"])
        for interval in intervals_only:
            csv_writer.writerow([interval])
    
    print(f"簡化版檔案: {simple_filename} (僅包含InterArrivalTime，可直接用於現有MQTT程式)")

def main():
    parser = argparse.ArgumentParser(description='合併正常流量和Flood攻擊CSV檔案')
    parser.add_argument('--normal', '-n', required=True,
                       help='正常流量CSV檔案 (例如: delta_ip5.csv)')
    parser.add_argument('--flood', '-f', required=True,
                       help='Flood攻擊CSV檔案 (例如: ddos_flood.csv)')
    parser.add_argument('--attack-times', '-t', required=True,
                       help='攻擊開始時間，用逗號分隔 (例如: "300,3000")')
    parser.add_argument('--output', '-o', default='merged_traffic.csv',
                       help='輸出檔案名稱 (預設: merged_traffic.csv)')
    parser.add_argument('--simple', action='store_true',
                       help='同時生成簡化版CSV檔案（僅InterArrivalTime欄位）')
    
    args = parser.parse_args()
    
    # 解析攻擊時間
    try:
        attack_times = [float(t.strip()) for t in args.attack_times.split(',')]
    except ValueError:
        print("錯誤: 攻擊時間格式不正確，請使用逗號分隔的數字")
        return
    
    print("=== 流量合併器 ===")
    print(f"正常流量檔案: {args.normal}")
    print(f"Flood攻擊檔案: {args.flood}")
    print(f"攻擊時間點: {attack_times} 秒")
    print(f"輸出檔案: {args.output}")
    print("==================\n")
    
    # 讀取CSV檔案
    normal_intervals = read_csv_intervals(args.normal)
    flood_intervals = read_csv_intervals(args.flood)
    
    if not normal_intervals or not flood_intervals:
        print("無法讀取必要的CSV檔案，程式結束")
        return
    
    # 檢查正常流量是否足夠長
    normal_total_time = sum(normal_intervals)
    max_attack_time = max(attack_times)
    
    if normal_total_time < max_attack_time:
        print(f"警告: 正常流量總時間 ({normal_total_time:.2f}s) 小於最大攻擊時間 ({max_attack_time}s)")
        print("建議增加正常流量的持續時間或調整攻擊時間點")
    
    # 合併流量
    merge_traffic_with_attacks(normal_intervals, flood_intervals, attack_times, args.output)
    
    # 如果需要，生成簡化版本
    if args.simple:
        create_simple_merged_csv(normal_intervals, flood_intervals, attack_times, args.output)

if __name__ == "__main__":
    main()
