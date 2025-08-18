import random
import csv
import argparse

def generate_flood_intervals(rate_per_second, duration_seconds, output_filename="flood_intervals.csv", seed=None):
    """
    生成flood攻擊的時間間隔
    
    Args:
        rate_per_second: 每秒幾次訊息
        duration_seconds: 持續多少秒
        output_filename: 輸出檔案名稱
        seed: 隨機種子
    """
    if seed is not None:
        random.seed(seed)
    
    # 計算總訊息數量
    total_messages = int(rate_per_second * duration_seconds)
    
    # 計算lambda參數（每秒事件數）
    lambda_rate = rate_per_second
    
    # 生成指數分佈的時間間隔
    intervals = [random.expovariate(lambda_rate) for _ in range(total_messages)]
    
    # 寫入CSV檔案
    with open(output_filename, mode='w', newline='') as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(["InterArrivalTime"])
        for interval in intervals:
            csv_writer.writerow([interval])
    
    # 計算統計資訊
    total_time = sum(intervals)
    average_interval = total_time / len(intervals) if intervals else 0
    actual_rate = len(intervals) / total_time if total_time > 0 else 0
    
    print(f"Flood攻擊時間間隔檔案已生成: {output_filename}")
    print(f"目標速率: {rate_per_second} 則/秒")
    print(f"目標持續時間: {duration_seconds} 秒")
    print(f"總訊息數: {total_messages}")
    print(f"實際總時間: {total_time:.2f} 秒")
    print(f"平均間隔: {average_interval:.4f} 秒")
    print(f"實際速率: {actual_rate:.2f} 則/秒")

def generate_burst_flood_intervals(burst_config, output_filename="burst_flood_intervals.csv", seed=None):
    """
    生成突發式flood攻擊（短時間內極高頻率）
    
    Args:
        burst_config: 突發設定 [(rate1, duration1), (rate2, duration2), ...]
        output_filename: 輸出檔案名稱
        seed: 隨機種子
    """
    if seed is not None:
        random.seed(seed)
    
    all_intervals = []
    total_messages = 0
    
    print("突發模式設定:")
    for i, (rate, duration) in enumerate(burst_config):
        print(f"  階段 {i+1}: {rate} 則/秒, 持續 {duration} 秒")
        
        # 計算這個階段的訊息數量
        stage_messages = int(rate * duration)
        lambda_rate = rate
        
        # 生成這個階段的間隔
        stage_intervals = [random.expovariate(lambda_rate) for _ in range(stage_messages)]
        all_intervals.extend(stage_intervals)
        total_messages += stage_messages
    
    # 寫入CSV檔案
    with open(output_filename, mode='w', newline='') as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(["InterArrivalTime"])
        for interval in all_intervals:
            csv_writer.writerow([interval])
    
    # 計算統計資訊
    total_time = sum(all_intervals)
    average_interval = total_time / len(all_intervals) if all_intervals else 0
    actual_rate = len(all_intervals) / total_time if total_time > 0 else 0
    
    print(f"\n突發Flood攻擊檔案已生成: {output_filename}")
    print(f"總訊息數: {total_messages}")
    print(f"實際總時間: {total_time:.2f} 秒")
    print(f"平均間隔: {average_interval:.4f} 秒")
    print(f"實際平均速率: {actual_rate:.2f} 則/秒")

def main():
    parser = argparse.ArgumentParser(description='生成Flood攻擊時間間隔CSV檔案')
    parser.add_argument('--rate', '-r', type=float, required=True,
                       help='每秒訊息數量 (例如: 100)')
    parser.add_argument('--duration', '-d', type=float, required=True,
                       help='持續時間(秒) (例如: 10)')
    parser.add_argument('--output', '-o', default='flood_intervals.csv',
                       help='輸出檔案名稱 (預設: flood_intervals.csv)')
    parser.add_argument('--seed', '-s', type=int,
                       help='隨機種子 (可選)')
    parser.add_argument('--mode', '-m', choices=['simple', 'burst'], default='simple',
                       help='模式: simple(固定速率) 或 burst(突發模式)')
    parser.add_argument('--burst-config', 
                       help='突發模式設定，格式: "rate1:duration1,rate2:duration2" (例如: "500:2,200:5,1000:3")')
    
    args = parser.parse_args()
    
    print("=== Flood時間間隔生成器 ===")
    
    if args.mode == 'simple':
        print(f"模式: 固定速率")
        print(f"速率: {args.rate} 則/秒")
        print(f"持續時間: {args.duration} 秒")
        print(f"輸出檔案: {args.output}")
        if args.seed:
            print(f"隨機種子: {args.seed}")
        print("==========================\n")
        
        generate_flood_intervals(
            rate_per_second=args.rate,
            duration_seconds=args.duration,
            output_filename=args.output,
            seed=args.seed
        )
    
    elif args.mode == 'burst':
        if not args.burst_config:
            print("錯誤: 突發模式需要提供 --burst-config 參數")
            return
        
        # 解析突發設定
        burst_config = []
        try:
            for item in args.burst_config.split(','):
                rate, duration = item.strip().split(':')
                burst_config.append((float(rate), float(duration)))
        except ValueError:
            print("錯誤: burst-config 格式不正確，應為 'rate1:duration1,rate2:duration2'")
            return
        
        print(f"模式: 突發式")
        print(f"輸出檔案: {args.output}")
        if args.seed:
            print(f"隨機種子: {args.seed}")
        print("==========================\n")
        
        generate_burst_flood_intervals(
            burst_config=burst_config,
            output_filename=args.output,
            seed=args.seed
        )

if __name__ == "__main__":
    main()
