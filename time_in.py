import random
import csv

def generate_time_intervals(lambda_rate=5, total_messages=1000, output_filename="time_intervals.csv", seed=123):
    random.seed(seed)
    intervals = [random.expovariate(lambda_rate) for _ in range(total_messages)]
    with open(output_filename, mode='w', newline='') as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow(["InterArrivalTime"])
        for interval in intervals:
            csv_writer.writerow([interval])
    print(f"已儲存 {total_messages} 筆間隔資料至 {output_filename}")

if __name__ == "__main__":
    generate_time_intervals(lambda_rate=1, total_messages=6000, output_filename="delta_ip5.csv", seed=11111)
