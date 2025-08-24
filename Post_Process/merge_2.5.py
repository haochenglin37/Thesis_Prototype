import pandas as pd
import os

# 1. 確認檔案存在
files = ["edge_plugin_att_1hrs_1tm.csv", "forwarder_performance_att_1hrs_1tm.csv"]
for f in files:
    if not os.path.isfile(f):
        raise FileNotFoundError(f"找不到檔案：{f}")

# 2. 讀 CSV
edge_df = pd.read_csv('edge_plugin_att_1hrs_1tm.csv')
fwd_df  = pd.read_csv('forwarder_performance_att_1hrs_1tm.csv')

# 3. 把 epoch 秒數轉成 datetime
edge_df['recv_ts'] = pd.to_datetime(edge_df['recv_ts'], unit='s', errors='raise')
fwd_df ['read_ts'] = pd.to_datetime(fwd_df ['original_timestamp'], unit='s', errors='raise')

# 4. 依 edge 的範圍計算要排除的前後 2.5 分鐘
start_time   = edge_df['recv_ts'].min()
end_time     = edge_df['recv_ts'].max()
lower_cutoff = start_time + pd.Timedelta(minutes=2.5)
upper_cutoff = end_time   - pd.Timedelta(minutes=2.5)

# 5. 濾出中間區段
edge_filtered = edge_df[
    (edge_df['recv_ts'] > lower_cutoff) &
    (edge_df['recv_ts'] < upper_cutoff)
].copy()

fwd_filtered = fwd_df[
    (fwd_df['read_ts'] > lower_cutoff) &
    (fwd_df['read_ts'] < upper_cutoff)
].copy()

# 6. 改名並合併
fwd_filtered = fwd_filtered.rename(columns={'original_ip': 'ip'})
merged = pd.merge(
    edge_filtered,
    fwd_filtered,
    on=['ip', 'packet_count'],
    how='left',
    suffixes=('', '_fwd')
)

# 7. 存檔
output_path = 'merged_performance_att_1hrs_1tm.csv'
merged.to_csv(output_path, index=False)
print(f"Merged file saved to: {os.path.abspath(output_path)}")
