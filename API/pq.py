from flask import Flask, request, jsonify
import threading
import math
import heapq
from collections import defaultdict

app = Flask(__name__)

# 全域狀態
state = {}
# 使用 min heap 維護前 25% 的 IP 信任分數
# heap 中儲存 (trust_value, ip)，自動維護分數最高的前 25% IP
top_ips_heap = []         # min heap，儲存前 25% 的 IP
high_threshold = 0.0      # heap 中的最小值，即進入前 25% 的門檻

lock = threading.Lock()

# 常數設定
EXPECTED_INTERVAL = 1    # 期望間隔 (s)
P_SUCCESS_TH      = 0.005  # p-value 成功閾值
P_TRUST_TH        = 0.005  # p-value 信任更新閾值
TRUST_THRESHOLD   = 0.2    # trust 放行閾值
TOP_PERCENT       = 0.25   # 前 25% 為 high priority

def update_top_ips_heap():
    """重建前 25% IP 的 heap"""
    global top_ips_heap, high_threshold
    
    # 收集所有合格的 IP 及其信任分數
    qualified_ips = []
    for ip, entry in state.items():
        if entry['trust'] > TRUST_THRESHOLD:
            qualified_ips.append((entry['trust'], ip))
    
    # 計算前 25% 的數量
    total_qualified = len(qualified_ips)
    top_count = max(1, int(total_qualified * TOP_PERCENT)) if total_qualified > 0 else 0
    
    if top_count == 0:
        top_ips_heap.clear()
        high_threshold = 0.0
        return
    
    # 找出分數最高的前 25% IP
    # 使用 nlargest 找到前 top_count 個最大值
    top_ips = heapq.nlargest(top_count, qualified_ips, key=lambda x: x[0])
    
    # 重建 min heap（存分數最低的在 heap[0]）
    top_ips_heap = top_ips.copy()
    heapq.heapify(top_ips_heap)
    
    # 更新 high_threshold（前 25% 中分數最低的）
    if top_ips_heap:
        high_threshold = top_ips_heap[0][0]  # heap[0] 是最小值
    else:
        high_threshold = 0.0

def update_single_ip_in_heap(ip, new_trust, old_trust):
    """更新單個 IP 的信任分數（增量更新）"""
    global top_ips_heap, high_threshold
    
    # 獲取所有合格 IP 數量
    qualified_count = sum(1 for entry in state.values() if entry['trust'] > TRUST_THRESHOLD)
    target_heap_size = max(1, int(qualified_count * TOP_PERCENT)) if qualified_count > 0 else 0
    
    if target_heap_size == 0:
        top_ips_heap.clear()
        high_threshold = 0.0
        return
    
    # 檢查該 IP 是否在 heap 中
    ip_in_heap = any(item[1] == ip for item in top_ips_heap)
    
    # 情況 1: IP 原本在 heap 中
    if ip_in_heap:
        if new_trust <= TRUST_THRESHOLD:
            # IP 不再合格，需要重建
            update_top_ips_heap()
        else:
            # IP 仍合格但分數變化，簡單起見重建（可優化）
            update_top_ips_heap()
    
    # 情況 2: IP 原本不在 heap 中
    else:
        if new_trust > TRUST_THRESHOLD:
            if len(top_ips_heap) < target_heap_size:
                # heap 未滿，直接加入
                heapq.heappush(top_ips_heap, (new_trust, ip))
                high_threshold = top_ips_heap[0][0]
            elif new_trust > high_threshold:
                # 新分數比 heap 中最小值大，替換
                heapq.heapreplace(top_ips_heap, (new_trust, ip))
                high_threshold = top_ips_heap[0][0]
    
    # 調整 heap 大小
    while len(top_ips_heap) > target_heap_size:
        heapq.heappop(top_ips_heap)
        if top_ips_heap:
            high_threshold = top_ips_heap[0][0]
        else:
            high_threshold = 0.0

def get_action_from_trust(trust_value, ip):
    """根據 trust 值和 IP 決定 action"""
    if trust_value <= TRUST_THRESHOLD:
        return 'drop'
    
    # 檢查是否在前 25% 中
    is_high_priority = any(item[1] == ip for item in top_ips_heap)
    return 'high' if is_high_priority else 'low'

@app.route('/policy', methods=['POST'])
def policy():
    data = request.get_json(force=True)
    ip = data.get('ip')
    delta = data.get('time_delta', 0.0)
    
    with lock:
        # 獲取或創建 IP 狀態
        entry = state.get(ip, {'success_count': 0, 'trust': 0.0})
        old_trust = entry['trust']
        
        # 計算雙尾 p-value (指數分布)
        cdf_fast = 1.0 - math.exp(-delta / EXPECTED_INTERVAL)
        cdf_slow = 1.0 - cdf_fast
        p_val = min(cdf_fast, cdf_slow) * 2.0
        
        # 更新連續成功計數
        if p_val > P_SUCCESS_TH:
            entry['success_count'] += 1
        else:
            entry['success_count'] = 0
        
        # 計算 logistic 因子 y
        x = entry['success_count']
        y = 100.0 / (1.0 + math.exp(-0.5 * (x - 50.0)))
        
        # 更新 trust 分數
        if p_val > P_TRUST_TH:
            entry['trust'] += y * 0.05
            if entry['trust'] > 1.0:
                entry['trust'] = 1.0
        else:
            entry['trust'] *= 0.2
        
        # 儲存狀態
        state[ip] = entry
        new_trust = entry['trust']
        
        # 更新 heap（增量更新 vs 重建）
        significant_change = abs(new_trust - old_trust) > 0.1
        crossed_threshold = (old_trust <= TRUST_THRESHOLD) != (new_trust <= TRUST_THRESHOLD)
        
        if significant_change or crossed_threshold:
            # 重大變化，完全重建確保準確
            update_top_ips_heap()
        else:
            # 小幅變化，增量更新
            update_single_ip_in_heap(ip, new_trust, old_trust)
        
        # 決定 action
        action = get_action_from_trust(new_trust, ip)
        
        # 統計資訊
        qualified_count = sum(1 for entry in state.values() if entry['trust'] > TRUST_THRESHOLD)
        high_count = len(top_ips_heap)
        
        print(f"[policy] IP: {ip}, trust: {new_trust:.4f} → {action}")
        print(f"         qualified: {qualified_count}, high: {high_count}, threshold: {high_threshold:.4f}")
    
    return jsonify({
        'action': action,
        'trust': new_trust,
        'p_value': p_val,
        'high_threshold': high_threshold,
        'qualified_count': qualified_count,
        'high_count': len(top_ips_heap),
        'is_in_top_25': action == 'high'
    })

@app.route('/stats', methods=['GET'])
def stats():
    """提供統計資訊的端點"""
    with lock:
        # 統計各種 action 的 IP 數量
        action_counts = defaultdict(int)
        trust_distribution = []
        
        for ip, entry in state.items():
            trust = entry['trust']
            action = get_action_from_trust(trust, ip)
            action_counts[action] += 1
            trust_distribution.append(trust)
        
        # 前 25% IP 的詳細資訊
        top_ips_info = []
        for trust_score, ip in sorted(top_ips_heap, reverse=True):  # 按分數降序
            top_ips_info.append({'ip': ip, 'trust': trust_score})
        
        qualified_count = sum(1 for entry in state.values() if entry['trust'] > TRUST_THRESHOLD)
        
        return jsonify({
            'total_ips': len(state),
            'action_counts': dict(action_counts),
            'qualified_count': qualified_count,
            'high_count': len(top_ips_heap),
            'high_threshold': high_threshold,
            'top_25_percent_ips': top_ips_info,
            'trust_distribution': {
                'min': min(trust_distribution) if trust_distribution else 0,
                'max': max(trust_distribution) if trust_distribution else 0,
                'avg': sum(trust_distribution) / len(trust_distribution) if trust_distribution else 0
            },
            'percentage_calculation': {
                'qualified_ips': qualified_count,
                'target_top_count': max(1, int(qualified_count * TOP_PERCENT)) if qualified_count > 0 else 0,
                'actual_top_count': len(top_ips_heap),
                'top_percentage': TOP_PERCENT * 100
            }
        })

@app.route('/debug_heap', methods=['GET'])
def debug_heap():
    """除錯端點，顯示前 25% IP 的詳細資訊"""
    with lock:
        # 將 heap 內容按分數排序（降序）
        sorted_top_ips = sorted(top_ips_heap, key=lambda x: x[0], reverse=True)
        
        qualified_ips = []
        for ip, entry in state.items():
            if entry['trust'] > TRUST_THRESHOLD:
                qualified_ips.append({'ip': ip, 'trust': entry['trust']})
        
        qualified_ips.sort(key=lambda x: x['trust'], reverse=True)
        
        return jsonify({
            'top_25_percent_heap': [{'ip': ip, 'trust': trust} for trust, ip in sorted_top_ips],
            'all_qualified_ips': qualified_ips,
            'heap_threshold': high_threshold,
            'total_qualified': len(qualified_ips),
            'target_top_count': max(1, int(len(qualified_ips) * TOP_PERCENT)) if qualified_ips else 0,
            'actual_top_count': len(top_ips_heap)
        })

@app.route('/reset', methods=['POST'])
def reset():
    """重置所有狀態（測試用）"""
    global state, top_ips_heap, high_threshold
    with lock:
        state.clear()
        top_ips_heap.clear()
        high_threshold = 0.0
        print("[policy] All state reset")
    return jsonify({'status': 'reset_complete'})

if __name__ == '__main__':
    print(f"[policy] Starting policy server with top 25% IP tracking:")
    print(f"  - TRUST_THRESHOLD: {TRUST_THRESHOLD}")
    print(f"  - TOP_PERCENT: {TOP_PERCENT * 100}%")
    print(f"  - Logic: Top 25% of qualified IPs → HIGH, rest → LOW")
    print(f"  - Example: 4 qualified IPs → top 1 is HIGH, other 3 are LOW")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
