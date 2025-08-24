import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# 1. Read the CSV file
df = pd.read_csv('merged_performance_att_1hrs_1tm_pq_rev.csv')

# 2. Compute waiting time and service time
df['queue_wait'] = df['start_forward_ts'] - df['original_timestamp']
df['service_time'] = df['end_forward_ts'] - df['start_forward_ts']
df['system_time'] = df['queue_wait'] + df['service_time']

# 3. Convert original_timestamp to numeric and clean data
df['original_ts_numeric'] = pd.to_numeric(df['original_timestamp'], errors='coerce')
df = df.dropna(subset=['original_ts_numeric'])

# 4. Separate high and low priority requests
high_priority = df[df['priority'] == 'high'].copy()
low_priority = df[df['priority'] == 'low'].copy()

def calculate_priority_gg1_metrics(priority_df, priority_name, all_data):
    """Calculate Priority G/G/1 queueing metrics"""
    print(f"\n=== {priority_name.upper()} Priority Analysis ===")
    
    # Sort by original timestamp and calculate interarrival times
    priority_df = priority_df.sort_values('original_ts_numeric').reset_index(drop=True)
    interarrival_times = priority_df['original_ts_numeric'].diff().dropna()
    
    # Calculate arrival rate
    mean_interarrival = interarrival_times.mean()
    lambda_rate = 1.0 / mean_interarrival
    
    print(f"Lambda ({priority_name}): {lambda_rate:.6f} arrivals/sec")
    
    # Service time statistics
    E_S = priority_df['service_time'].mean()
    Var_S = priority_df['service_time'].var()
    
    # Utilization
    rho = lambda_rate * E_S
    
    print(f"Mean Service Time (E[S]): {E_S:.6f}")
    print(f"System Utilization (rho): {rho:.6f}")
    
    # Calculate total system parameters
    all_sorted = all_data.sort_values('original_ts_numeric')
    all_interarrival = all_sorted['original_ts_numeric'].diff().dropna()
    lambda_total = 1.0 / all_interarrival.mean()
    service_time_total = all_data['service_time'].mean()
    rho_total = lambda_total * service_time_total
    
    # Calculate system-wide coefficients of variation
    Ca2_total = all_interarrival.var() / (all_interarrival.mean()**2)
    Cs2_total = all_data['service_time'].var() / (service_time_total**2)
    
    print(f"Total system lambda: {lambda_total:.6f}")
    print(f"Total system rho: {rho_total:.6f}")
    print(f"Total Ca^2: {Ca2_total:.6f}")
    print(f"Total Cs^2: {Cs2_total:.6f}")
    
    # Priority G/G/1 approximation
    W_priority = float('inf')
    T_priority = float('inf')
    
    if priority_name.lower() == 'high':
        if rho_total < 1:
            # High priority approximation
            W_priority = (rho_total / (1 - rho)) * ((Ca2_total + Cs2_total) / 2) * service_time_total
            T_priority = W_priority + service_time_total
    elif priority_name.lower() == 'low':
        # Calculate high priority utilization
        high_df = all_data[all_data['priority'] == 'high']
        if len(high_df) > 0:
            high_interarrival = high_df.sort_values('original_ts_numeric')['original_ts_numeric'].diff().dropna()
            lambda_high = 1.0 / high_interarrival.mean()
            rho_high = lambda_high * service_time_total
            
            if rho_total < 1 and rho_high < 1:
                # Low priority approximation
                W_priority = (rho_total / ((1 - rho_high) * (1 - rho_total))) * \
                            ((Ca2_total + Cs2_total) / 2) * service_time_total
                T_priority = W_priority + service_time_total
                print(f"High priority rho: {rho_high:.6f}")
    
    # Actual averages
    avg_queue = priority_df['queue_wait'].mean()
    avg_system = priority_df['system_time'].mean()
    
    print(f"Actual avg queue wait: {avg_queue:.6f} s")
    print(f"Actual avg system time: {avg_system:.6f} s")
    print(f"Priority G/G/1 queue wait: {W_priority:.6f} s")
    print(f"Priority G/G/1 system time: {T_priority:.6f} s")
    
    return {
        'data': priority_df,
        'W_priority': W_priority,
        'T_priority': T_priority,
        'avg_queue': avg_queue,
        'avg_system': avg_system
    }

# Calculate Priority G/G/1 metrics for both priorities
high_metrics = calculate_priority_gg1_metrics(high_priority, 'high', df)
low_metrics = calculate_priority_gg1_metrics(low_priority, 'low', df)

# Build time series for high priority
high_priority['timestamp'] = pd.to_datetime(high_priority['start_forward_ts'], unit='s')
high_ts = high_priority.set_index('timestamp')

# Build time series for low priority  
low_priority['timestamp'] = pd.to_datetime(low_priority['start_forward_ts'], unit='s')
low_ts = low_priority.set_index('timestamp')

# Compute rolling window (10s) averages
high_window_avg = high_ts[['queue_wait', 'system_time']].rolling('30S').mean()
high_cum_avg = high_ts[['queue_wait', 'system_time']].expanding().mean()

low_window_avg = low_ts[['queue_wait', 'system_time']].rolling('30S').mean()
low_cum_avg = low_ts[['queue_wait', 'system_time']].expanding().mean()

# Convert to relative time (starting from 0)
high_start_time = high_ts.index[0].timestamp()
high_window_time = (high_window_avg.index.astype(np.int64) / 1e9) - high_start_time
high_cum_time = (high_cum_avg.index.astype(np.int64) / 1e9) - high_start_time

low_start_time = low_ts.index[0].timestamp()
low_window_time = (low_window_avg.index.astype(np.int64) / 1e9) - low_start_time
low_cum_time = (low_cum_avg.index.astype(np.int64) / 1e9) - low_start_time

# Set font sizes
plt.rcParams.update({
    'axes.labelsize': 20,
    'legend.fontsize': 18,
    'xtick.labelsize': 18,
    'ytick.labelsize': 18
})

# Plot 1: System Time Only 
plt.figure(figsize=(15, 8))

# Plot sliding window averages for system time (High=red, Low=orange)
plt.plot(high_window_time, high_window_avg['system_time'], 
         label=f"High Priority Window Avg", 
         linewidth=1.5, color='#ffaaaa')  # Light red for High
plt.plot(low_window_time, low_window_avg['system_time'], 
         label=f"Low Priority Window Avg", 
         linewidth=1.5, color='#ffcc99')  # Light orange for Low

# Plot cumulative averages for system time (High=red, Low=orange, dashed)
plt.plot(high_cum_time, high_cum_avg['system_time'], 
         label=f"High Priority Cumulative Avg ({high_metrics['avg_system']:.6f}s)", 
         linewidth=2.0, color='#cc0000', linestyle='--')  # Medium red for High
plt.plot(low_cum_time, low_cum_avg['system_time'], 
         label=f"Low Priority Cumulative Avg ({low_metrics['avg_system']:.6f}s)", 
         linewidth=2.0, color='#ff9933', linestyle='--')  # Medium orange for Low

# Add theoretical Priority G/G/1 reference lines for system time (High=red, Low=orange, dash-dot)
if not np.isinf(high_metrics['T_priority']):
    plt.axhline(y=high_metrics['T_priority'], color='#880000', linestyle='-.', 
                linewidth=2.0, label=f"Theoretical G/G/1 High Priority ({high_metrics['T_priority']:.6f}s)")  # Dark red for High
if not np.isinf(low_metrics['T_priority']):
    plt.axhline(y=low_metrics['T_priority'], color='#cc6600', linestyle='-.', 
                linewidth=2.0, label=f"Theoretical G/G/1 Low Priority ({low_metrics['T_priority']:.6f}s)")  # Dark orange for Low

plt.xlabel("Time (s)")
plt.ylabel("Average System Time (s)")
plt.legend(loc='upper right')
plt.grid(True, alpha=0.3)

plt.tight_layout()
plt.ylim(0, 0.3)
plt.savefig("priority_system_time_analysis_gg1.svg", format='svg', bbox_inches="tight")
plt.show()

# Plot 2: Queue Waiting Time Only 
plt.figure(figsize=(15, 8))

# Plot sliding window averages for queue wait time (High=red, Low=orange)
plt.plot(high_window_time, high_window_avg['queue_wait'], 
         label=f"High Priority Window Avg", 
         linewidth=1.5, color='#ffaaaa')  # Light red for High
plt.plot(low_window_time, low_window_avg['queue_wait'], 
         label=f"Low Priority Window Avg", 
         linewidth=1.5, color='#ffcc99')  # Light orange for Low

# Plot cumulative averages for queue wait time (High=red, Low=orange, dashed)
plt.plot(high_cum_time, high_cum_avg['queue_wait'], 
         label=f"High Priority Cumulative Avg ({high_metrics['avg_queue']:.6f}s)", 
         linewidth=2.0, color='#cc0000', linestyle='--')  # Medium red for High
plt.plot(low_cum_time, low_cum_avg['queue_wait'], 
         label=f"Low Priority Cumulative Avg ({low_metrics['avg_queue']:.6f}s)", 
         linewidth=2.0, color='#ff9933', linestyle='--')  # Medium orange for Low

# Add theoretical Priority G/G/1 reference lines for queue wait time (High=red, Low=orange, dash-dot)
if not np.isinf(high_metrics['W_priority']):
    plt.axhline(y=high_metrics['W_priority'], color='#880000', linestyle='-.', 
                linewidth=2.0, label=f"Theoretical G/G/1 High Priority ({high_metrics['W_priority']:.6f}s)")  # Dark red for High
if not np.isinf(low_metrics['W_priority']):
    plt.axhline(y=low_metrics['W_priority'], color='#cc6600', linestyle='-.', 
                linewidth=2.0, label=f"Theoretical G/G/1 Low Priority ({low_metrics['W_priority']:.6f}s)")  # Dark orange for Low

plt.xlabel("Time (s)")
plt.ylabel("Average Queue Wait Time (s)")
plt.legend(loc='upper right')
plt.grid(True, alpha=0.3)

plt.tight_layout()
plt.ylim(0, 0.2)
plt.savefig("priority_queue_wait_time_analysis_gg1.svg", format='svg', bbox_inches="tight")
plt.show()

# Summary comparison
print("\n" + "="*60)
print("PRIORITY G/G/1 ANALYSIS SUMMARY")
print("="*60)

print(f"\nSystem Time Comparison:")
print(f"High Priority - Actual: {high_metrics['avg_system']:.6f} s")
print(f"High Priority - Theory: {high_metrics['T_priority']:.6f} s")
if not np.isinf(high_metrics['T_priority']):
    high_system_diff = abs(high_metrics['avg_system'] - high_metrics['T_priority']) / high_metrics['T_priority'] * 100
    print(f"High Priority - Difference: {high_system_diff:.2f}%")

print(f"Low Priority - Actual: {low_metrics['avg_system']:.6f} s")
print(f"Low Priority - Theory: {low_metrics['T_priority']:.6f} s")
if not np.isinf(low_metrics['T_priority']):
    low_system_diff = abs(low_metrics['avg_system'] - low_metrics['T_priority']) / low_metrics['T_priority'] * 100
    print(f"Low Priority - Difference: {low_system_diff:.2f}%")

print(f"\nQueue Waiting Time Comparison:")
print(f"High Priority - Actual: {high_metrics['avg_queue']:.6f} s")
print(f"High Priority - Theory: {high_metrics['W_priority']:.6f} s")
if not np.isinf(high_metrics['W_priority']):
    high_queue_diff = abs(high_metrics['avg_queue'] - high_metrics['W_priority']) / high_metrics['W_priority'] * 100
    print(f"High Priority - Difference: {high_queue_diff:.2f}%")

print(f"Low Priority - Actual: {low_metrics['avg_queue']:.6f} s")
print(f"Low Priority - Theory: {low_metrics['W_priority']:.6f} s")
if not np.isinf(low_metrics['W_priority']):
    low_queue_diff = abs(low_metrics['avg_queue'] - low_metrics['W_priority']) / low_metrics['W_priority'] * 100
    print(f"Low Priority - Difference: {low_queue_diff:.2f}%")

print("\n分析完成！")
print("圖表已保存為: priority_system_time_analysis_gg1_att.svg")
print("圖表已保存為: priority_queue_wait_time_analysis_gg1_att.svg")