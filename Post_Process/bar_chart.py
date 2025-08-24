import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# 讀取標準佇列模擬結果 (無優先級)
df_standard = pd.read_csv("merged_performance_att_1hrs_1tm.csv")

# 讀取優先級佇列模擬結果
df_priority = pd.read_csv("merged_performance_att_1hrs_1tm_pq_rev.csv")

print(f"標準佇列數據載入: {len(df_standard)} 筆記錄")
print(f"優先級佇列數據載入: {len(df_priority)} 筆記錄")

# 計算標準佇列的等待時間和系統時間
df_standard['queue_wait'] = df_standard['start_forward_ts'] - df_standard['original_timestamp']
df_standard['service_time'] = df_standard['end_forward_ts'] - df_standard['start_forward_ts']
df_standard['system_time'] = df_standard['queue_wait'] + df_standard['service_time']

# 計算優先級佇列的等待時間和系統時間
df_priority['queue_wait'] = df_priority['start_forward_ts'] - df_priority['original_timestamp']
df_priority['service_time'] = df_priority['end_forward_ts'] - df_priority['start_forward_ts']
df_priority['system_time'] = df_priority['queue_wait'] + df_priority['service_time']

# 清理數據
df_standard['original_ts_numeric'] = pd.to_numeric(df_standard['original_timestamp'], errors='coerce')
df_standard = df_standard.dropna(subset=['original_ts_numeric'])

df_priority['original_ts_numeric'] = pd.to_numeric(df_priority['original_timestamp'], errors='coerce')
df_priority = df_priority.dropna(subset=['original_ts_numeric'])

# 排序
df_standard = df_standard.sort_values("original_ts_numeric").reset_index(drop=True)
df_priority = df_priority.sort_values("original_ts_numeric").reset_index(drop=True)

# 分離高低優先級資料
df_high = df_priority[df_priority["priority"] == "high"].reset_index(drop=True)
df_low = df_priority[df_priority["priority"] == "low"].reset_index(drop=True)

print(f"標準佇列資料點數: {len(df_standard)}")
print(f"優先級佇列高優先資料點數: {len(df_high)}")
print(f"優先級佇列低優先資料點數: {len(df_low)}")

# 計算各自的到達過程變異數
# 標準佇列變異數
diffs_std = np.diff(df_standard["original_ts_numeric"].values)
Ca2_std = np.var(diffs_std) / np.mean(diffs_std)**2

# 優先級佇列整體變異數
diffs_priority = np.diff(df_priority["original_ts_numeric"].values)
Ca2_priority = np.var(diffs_priority) / np.mean(diffs_priority)**2

print(f"\n到達過程變異數分析:")
print(f"標準佇列 CV² = {Ca2_std:.4f}")
print(f"優先級佇列 CV² = {Ca2_priority:.4f}")

# 計算 G/G/1 標準和優先級佇列的理論值
# 標準佇列理論值計算
std_interarrival = diffs_std.mean()
lambda_std = 1.0 / std_interarrival
E_S_std = df_standard['service_time'].mean()
Var_S_std = df_standard['service_time'].var()
Cs2_std = Var_S_std / (E_S_std**2)
rho_std = lambda_std * E_S_std

if rho_std < 1:
    # G/G/1 Kingman's approximation for standard queue
    std_theory_wait = (rho_std / (1 - rho_std)) * ((Ca2_std + Cs2_std) / 2) * E_S_std
    std_theory_system = std_theory_wait + E_S_std
else:
    std_theory_wait = float('inf')
    std_theory_system = float('inf')

# 優先級佇列理論值計算
# 計算總系統參數
all_interarrival = diffs_priority.mean()
lambda_total = 1.0 / all_interarrival
service_time_total = df_priority['service_time'].mean()
rho_total = lambda_total * service_time_total

# 計算系統級變異係數
Cs2_total = df_priority['service_time'].var() / (service_time_total**2)

# 計算高優先級參數
if len(df_high) > 1:
    high_interarrival = df_high.sort_values('original_ts_numeric')['original_ts_numeric'].diff().dropna()
    lambda_high = 1.0 / high_interarrival.mean()
    rho_high = lambda_high * service_time_total
else:
    lambda_high = 0
    rho_high = 0

# Priority G/G/1 理論值
if rho_total < 1 and rho_high < 1:
    # High priority
    w_high_theory = (rho_total / (1 - rho_high)) * ((Ca2_priority + Cs2_total) / 2) * service_time_total
    sys_high_theory = w_high_theory + service_time_total
    
    # Low priority  
    w_low_theory = (rho_total / ((1 - rho_high) * (1 - rho_total))) * ((Ca2_priority + Cs2_total) / 2) * service_time_total
    sys_low_theory = w_low_theory + service_time_total
else:
    w_high_theory = float('inf')
    w_low_theory = float('inf')
    sys_high_theory = float('inf')
    sys_low_theory = float('inf')

print("\n理論值計算結果 (G/G/1):")
print(f"標準佇列 - 實際到達率: {lambda_std:.6f}, 使用率: {rho_std:.4f}")
if std_theory_wait != float('inf'):
    print(f"標準佇列 G/G/1 理論等待時間: {std_theory_wait:.6f}s, 系統時間: {std_theory_system:.6f}s")
else:
    print("標準佇列系統不穩定，無法計算理論值")

print(f"優先級佇列 - 總使用率: {rho_total:.4f}, 高優先使用率: {rho_high:.4f}")
if w_high_theory != float('inf'):
    print(f"優先級佇列 G/G/1 理論等待時間 - 高優先: {w_high_theory:.6f}s, 低優先: {w_low_theory:.6f}s")
    print(f"優先級佇列 G/G/1 理論系統時間 - 高優先: {sys_high_theory:.6f}s, 低優先: {sys_low_theory:.6f}s")
else:
    print("優先級佇列系統不穩定，無法計算理論值")

# 設定字體大小
plt.rcParams.update({
    'axes.labelsize': 22,
    'legend.fontsize': 22,
    'xtick.labelsize': 22,
    'ytick.labelsize': 22
})

# 計算各佇列的等待時間和系統時間的平均值
std_wait = df_standard["queue_wait"].mean()
std_sys = df_standard["system_time"].mean()

high_wait = df_high["queue_wait"].mean()
high_sys = df_high["system_time"].mean()

low_wait = df_low["queue_wait"].mean()
low_sys = df_low["system_time"].mean()

print("\n實際平均值計算結果:")
print(f"標準佇列等待時間: {std_wait:.6f}s, 系統時間: {std_sys:.6f}s")
print(f"高優先等待時間: {high_wait:.6f}s, 系統時間: {high_sys:.6f}s")
print(f"低優先等待時間: {low_wait:.6f}s, 系統時間: {low_sys:.6f}s")

# 計算理論與實際的差異
print(f"\n理論與實際差異 (G/G/1):")
if std_theory_wait != float('inf'):
    std_wait_diff = abs(std_wait - std_theory_wait) / std_theory_wait * 100
    std_sys_diff = abs(std_sys - std_theory_system) / std_theory_system * 100
    print(f"標準佇列等待時間差異: {std_wait_diff:.2f}%, 系統時間差異: {std_sys_diff:.2f}%")

if w_high_theory != float('inf'):
    high_wait_diff = abs(high_wait - w_high_theory) / w_high_theory * 100
    high_sys_diff = abs(high_sys - sys_high_theory) / sys_high_theory * 100
    low_wait_diff = abs(low_wait - w_low_theory) / w_low_theory * 100
    low_sys_diff = abs(low_sys - sys_low_theory) / sys_low_theory * 100
    print(f"高優先等待時間差異: {high_wait_diff:.2f}%, 系統時間差異: {high_sys_diff:.2f}%")
    print(f"低優先等待時間差異: {low_wait_diff:.2f}%, 系統時間差異: {low_sys_diff:.2f}%")

# 創建綜合長條圖（同時顯示等待時間和系統時間）
plt.figure(figsize=(15, 10))

# 定義資料
x = np.array([0, 1])  # 0=Queue Wait Time, 1=System Time
width = 0.25
labels = ['Queue Waiting Time', 'System Waiting Time']

# 每個佇列類型的數據
std_values = [std_wait, std_sys]
high_values = [high_wait, high_sys]
low_values = [low_wait, low_sys]

# 設定顏色和填充樣式
colors = ['#90EE90', '#ADD8E6', '#FFCC99']  # 淺綠、淺藍、淺橘
hatches = ['/', '-', '.']     # 斜線、橫線、點點

# 繪製長條圖
plt.bar(x - width, std_values, width, color=colors[0], hatch=hatches[0], 
        label='Standard Queue', edgecolor='black', linewidth=1.5)
plt.bar(x, high_values, width, color=colors[1], hatch=hatches[1], 
        label='Priority - High', edgecolor='black', linewidth=1.5)
plt.bar(x + width, low_values, width, color=colors[2], hatch=hatches[2], 
        label='Priority - Low', edgecolor='black', linewidth=1.5)

# 添加 G/G/1 理論值為橫線
if std_theory_wait != float('inf'):
    # 標準佇列理論值
    plt.plot([x[0] - width - width/2, x[0] - width + width/2], 
             [std_theory_wait, std_theory_wait], 'k--', linewidth=2)
    plt.plot([x[1] - width - width/2, x[1] - width + width/2], 
             [std_theory_system, std_theory_system], 'k--', linewidth=2)

if w_high_theory != float('inf') and w_low_theory != float('inf'):
    # 高優先級理論值
    plt.plot([x[0] - width/2, x[0] + width/2], 
             [w_high_theory, w_high_theory], 'k--', linewidth=2)
    plt.plot([x[1] - width/2, x[1] + width/2], 
             [sys_high_theory, sys_high_theory], 'k--', linewidth=2)
    
    # 低優先級理論值
    plt.plot([x[0] + width - width/2, x[0] + width + width/2], 
             [w_low_theory, w_low_theory], 'k--', linewidth=2)
    plt.plot([x[1] + width - width/2, x[1] + width + width/2], 
             [sys_low_theory, sys_low_theory], 'k--', linewidth=2)

# 在每個長條上顯示數值 (放大字體並設為粗體)
for i, v in enumerate(std_values):
    plt.text(i - width, v + max(std_values + high_values + low_values) * 0.02, f"{v:.6f}", 
             ha='center', fontsize=16, fontweight='bold')
    
for i, v in enumerate(high_values):
    plt.text(i, v + max(std_values + high_values + low_values) * 0.02, f"{v:.6f}", 
             ha='center', fontsize=16, fontweight='bold')
    
for i, v in enumerate(low_values):
    plt.text(i + width, v + max(std_values + high_values + low_values) * 0.02, f"{v:.6f}", 
             ha='center', fontsize=16, fontweight='bold')

# 設定X軸標籤
plt.xticks(x, labels)

# 設定Y軸範圍和標籤
plt.ylabel("Time (seconds)")
max_val = max(std_values + high_values + low_values)
plt.ylim(0, max_val * 1.2)  # 動態調整Y軸範圍

# 添加網格線
plt.grid(True, alpha=0.3, axis='y')

# 添加圖例（包含理論值說明）- 移到左上角
legend_elements = [
    plt.Rectangle((0,0),1,1, facecolor=colors[0], hatch=hatches[0], edgecolor='black', label='Standard Queue'),
    plt.Rectangle((0,0),1,1, facecolor=colors[1], hatch=hatches[1], edgecolor='black', label='Priority - High'),
    plt.Rectangle((0,0),1,1, facecolor=colors[2], hatch=hatches[2], edgecolor='black', label='Priority - Low'),
    plt.Line2D([0], [0], color='black', linestyle='--', linewidth=2, label='G/G/1 Theory')
]
plt.legend(handles=legend_elements, loc='upper left')

plt.tight_layout()
plt.savefig("queue_comparison_bar_chart_gg1.svg", format='svg', dpi=300, bbox_inches="tight")
plt.show()

print("\n分析完成! 包含 G/G/1 理論值的長條圖已生成。")
print("生成的檔案:")
print("- queue_comparison_bar_chart_gg1.svg")