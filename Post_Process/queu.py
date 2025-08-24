import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# 1. Read the merged CSV containing service_end_ts, start_forward_ts, end_forward_ts
df = pd.read_csv('merged_performance_att_1hrs_1tm.csv')

print(f"讀入 {len(df)} 筆排隊數據")

# 2. Compute waiting time and service time
df['queue_wait'] = df['start_forward_ts'] - df['service_end_ts']
df['service_time'] = df['end_forward_ts'] - df['start_forward_ts']
df['system_time'] = df['queue_wait'] + df['service_time']

# 3. Compute interarrival times based on plugin service_end_ts
df = df.sort_values('service_end_ts').reset_index(drop=True)
df['interarrival'] = df['service_end_ts'].diff()

# Drop the first row (no interarrival)
df = df.iloc[1:].copy()

# --- Calculate lambda from 'original_timestamp' ---
df['original_ts_numeric'] = pd.to_numeric(df['original_timestamp'], errors='coerce')
valid_arrivals_df = df.dropna(subset=['original_ts_numeric'])
valid_arrivals_df = valid_arrivals_df.sort_values('original_ts_numeric')
interarrival_from_original = valid_arrivals_df['original_ts_numeric'].diff()
mean_interarrival_original = interarrival_from_original.mean()
lambda_from_original = 1.0 / mean_interarrival_original

print(f"Lambda calculated from 'original_timestamp': {lambda_from_original:.6f} arrivals/sec")

# Calculate arrival process variance
Ca2 = interarrival_from_original.var() / (interarrival_from_original.mean()**2)
print(f"到達流程 CV² = {Ca2:.4f}")

# Service time statistics
E_S = df['service_time'].mean()
Var_S = df['service_time'].var()
Cs2 = Var_S / (E_S**2)  # Service CV²

# System parameters
lambda_theoretical = lambda_from_original
rho = lambda_theoretical * E_S

print(f"\n系統參數分析:")
print(f"實際到達率 (λ): {lambda_theoretical:.6f} events/second")
print(f"平均服務時間 (E[S]): {E_S:.6f} seconds")
print(f"流量強度 (ρ): {rho:.6f}")
print(f"服務流程 CV² = {Cs2:.4f}")

# Check system stability
if rho >= 1:
    print("警告: 系統不穩定 (ρ ≥ 1)！")
else:
    print("系統穩定 (ρ < 1)")

# Calculate G/G/1 theoretical values using Kingman's approximation
if rho < 1:
    # G/G/1 Kingman's approximation with both Ca² and Cs²
    W_GG1 = (rho / (1 - rho)) * ((Ca2 + Cs2) / 2) * E_S
    T_GG1 = W_GG1 + E_S
else:
    W_GG1 = float('inf')
    T_GG1 = float('inf')

print(f"\nG/G/1 理論值 (Kingman 近似):")
print(f"G/G/1 理論排隊等待時間: {W_GG1:.6f} 秒")
print(f"G/G/1 理論系統時間: {T_GG1:.6f} 秒")

# Build a time series indexed by service_end_ts
df['timestamp'] = pd.to_datetime(df['service_end_ts'], unit='s')
ts = df.set_index('timestamp')

# Compute rolling window (10 s) averages
window_avg = ts[['queue_wait', 'system_time']].rolling('10S').mean()
cum_avg = ts[['queue_wait', 'system_time']].expanding().mean()

# Calculate actual averages
actual_avg_wait = df['queue_wait'].mean()
actual_avg_system = df['system_time'].mean()

print(f"\n實際模擬值:")
print(f"實際平均排隊等待時間: {actual_avg_wait:.6f} 秒")
print(f"實際平均系統時間: {actual_avg_system:.6f} 秒")

print(f"\n理論與實際差異:")
if W_GG1 != float('inf'):
    wait_diff_gg1 = abs(actual_avg_wait - W_GG1) / W_GG1 * 100
    system_diff_gg1 = abs(actual_avg_system - T_GG1) / T_GG1 * 100
    print(f"G/G/1 排隊等待時間差異: {wait_diff_gg1:.2f}%")
    print(f"G/G/1 系統時間差異: {system_diff_gg1:.2f}%")

# Set font sizes
plt.rcParams.update({
    'axes.labelsize': 20,
    'legend.fontsize': 18,
    'xtick.labelsize': 18,
    'ytick.labelsize': 18
})

# Plot with same style as second code
plt.figure(figsize=(15, 8))

# Convert to relative time (starting from 0)
start_time = ts.index[0].timestamp()
relative_time_window = (window_avg.index.astype(np.int64) / 1e9) - start_time
relative_time_cum = (cum_avg.index.astype(np.int64) / 1e9) - start_time

# Plot sliding window averages (light colors)
plt.plot(relative_time_window, window_avg['queue_wait'], 
         label=f"Window Avg Queue Wait (10s window)", 
         linewidth=1.5, color='#ffaaaa')  # Light red
plt.plot(relative_time_window, window_avg['system_time'], 
         label=f"Window Avg System Time (10s window)", 
         linewidth=1.5, color='#ffcc99')  # Light orange

# Plot cumulative averages (medium colors, dashed)
plt.plot(relative_time_cum, cum_avg['queue_wait'], 
         label=f"Cumulative Avg Queue Wait ({actual_avg_wait:.6f}s)", 
         linewidth=2.0, color='#cc0000', linestyle='--')  # Medium red
plt.plot(relative_time_cum, cum_avg['system_time'], 
         label=f"Cumulative Avg System Time ({actual_avg_system:.6f}s)", 
         linewidth=2.0, color='#ff9933', linestyle='--')  # Medium orange

# Add theoretical G/G/1 reference lines (dark colors, dash-dot)
if rho < 1 and W_GG1 != float('inf'):
    plt.axhline(y=W_GG1, color='#880000', linestyle='-.', 
                linewidth=2.0, label=f"Theoretical G/G/1 Queue Wait ({W_GG1:.6f}s)")  # Dark red
    plt.axhline(y=T_GG1, color='#cc6600', linestyle='-.', 
                linewidth=2.0, label=f"Theoretical G/G/1 System Time ({T_GG1:.6f}s)")  # Dark orange

# Set Y-axis range to 0.4
plt.ylim(0, 0.5)

plt.xlabel("Time (s)")
plt.ylabel("Average Time (s)")
plt.legend(loc='upper right')
plt.grid(True, alpha=0.3)

plt.tight_layout()

# Save chart as SVG
plt.savefig("queue_time_analysis_gg1_theoretical.svg", format='svg', bbox_inches="tight")
plt.show()

print("\n分析完成！")
print("圖表已保存為: queue_time_analysis_gg1_theoretical_att_normal.svg")