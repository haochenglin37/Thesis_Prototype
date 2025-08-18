from flask import Flask, request, jsonify
import threading
import math
import time
from collections import defaultdict
import bisect

app = Flask(__name__)

# 全域狀態
state = {}
# 使用有序列表維護 trust 分數，支援快速插入和分位數查詢
qualified_trust_scores = []  # 保持排序的列表，儲存所有 > TRUST_THRESHOLD 的分數
high_threshold = 0.8   # 動態的 high/low 分界線（前25%）

lock = threading.Lock()

# 常數設定
EXPECTED_INTERVAL = 1    # 期望間隔 (s)
P_SUCCESS_TH      = 0.005  # p-value 成功閾值
P_TRUST_TH        = 0.005  # p-value 信任更新閾值
TRUST_THRESHOLD   = 0.2    # trust 放行閾值
MAX_SAMPLES       = 1000   # 最多保留1000個樣本
MIN_SAMPLES       = 20     # 至少需要20個樣本才計算分位數

def insert_trust_score(trust_value):
    """使用二分搜尋插入 trust 分數，維持排序"""
    global qualified_trust_scores
    
    if trust_value > TRUST_THRESHOLD:
        # 使用 bisect 進行 O(log n) 插入，保持排序
        bisect.insort(qualified_trust_scores, trust_value)
        
        # 限制最大樣本數，移除最小的值
        if len(qualified_trust_scores) > MAX_SAMPLES:
            qualified_trust_scores.pop(0)  # 移除最小值

def update_high_threshold():
    """即時更新 high/low 分界線（前25%閾值）"""
    global qualified_trust_scores, high_threshold
    
    if len(qualified_trust_scores) >= MIN_SAMPLES:
        # 計算75分位數作為 high 的閾值（前25%）
        # 因為 qualified_trust_scores 已經排序，直接計算索引
        percentile_75_index = int(len(qualified_trust_scores) * 0.75)
        high_threshold = qualified_trust_scores[percentile_75_index]
        return True
    return False

def get_action_from_trust(trust_value):
    """根據 trust 值決定 action"""
    if trust_value <= TRUST_THRESHOLD:
        return 'drop'
    elif trust_value >= high_threshold:
        return 'high'
    else:
        return 'low'

@app.route('/policy', methods=['POST'])
def policy():
    global qualified_trust_scores, high_threshold
    
    data = request.get_json(force=True)
    ip = data.get('ip')
    delta = data.get('time_delta', 0.0)
    
    with lock:
        # 獲取或創建 IP 狀態
        entry = state.get(ip, {'success_count': 0, 'trust': 0.0})
        old_trust = entry['trust']  # 記錄舊的 trust 值
        
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
        
        # 更新 trust 分數列表
        # 如果舊分數 > TRUST_THRESHOLD，需要移除
        if old_trust > TRUST_THRESHOLD and old_trust in qualified_trust_scores:
            qualified_trust_scores.remove(old_trust)  # O(n) 但很少發生
        
        # 插入新分數（如果符合條件）
        insert_trust_score(new_trust)
        
        # 即時更新 high 閾值
        threshold_updated = update_high_threshold()
        
        # 決定 action
        action = get_action_from_trust(new_trust)
        
        # 記錄詳細資訊（顯示閾值更新）
        if threshold_updated:
            print(f"[policy] IP: {ip}, trust: {new_trust:.4f} → {action}, high_threshold updated to: {high_threshold:.4f} (samples: {len(qualified_trust_scores)})")
        else:
            print(f"[policy] IP: {ip}, trust: {new_trust:.4f} → {action}, high_threshold: {high_threshold:.4f}")
    
    return jsonify({
        'action': action,
        'trust': new_trust,
        'p_value': p_val,
        'high_threshold': high_threshold,  # 回傳當前閾值供除錯
        'samples_count': len(qualified_trust_scores)
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
            action = get_action_from_trust(trust)
            action_counts[action] += 1
            trust_distribution.append(trust)
        
        # 計算統計數據
        total_ips = len(state)
        above_threshold_count = len([t for t in trust_distribution if t > TRUST_THRESHOLD])
        
        # 分位數統計
        percentiles = {}
        if len(qualified_trust_scores) > 0:
            percentiles = {
                '25th': qualified_trust_scores[int(len(qualified_trust_scores) * 0.25)] if len(qualified_trust_scores) >= 4 else None,
                '50th': qualified_trust_scores[int(len(qualified_trust_scores) * 0.5)] if len(qualified_trust_scores) >= 2 else None,
                '75th': qualified_trust_scores[int(len(qualified_trust_scores) * 0.75)] if len(qualified_trust_scores) >= 4 else None,
                '95th': qualified_trust_scores[int(len(qualified_trust_scores) * 0.95)] if len(qualified_trust_scores) >= 20 else None,
            }
        
        return jsonify({
            'total_ips': total_ips,
            'action_counts': dict(action_counts),
            'above_threshold_count': above_threshold_count,
            'current_high_threshold': high_threshold,
            'qualified_samples_count': len(qualified_trust_scores),
            'percentiles': percentiles,
            'trust_distribution': {
                'min': min(trust_distribution) if trust_distribution else 0,
                'max': max(trust_distribution) if trust_distribution else 0,
                'avg': sum(trust_distribution) / len(trust_distribution) if trust_distribution else 0
            },
            'qualified_range': {
                'min': min(qualified_trust_scores) if qualified_trust_scores else None,
                'max': max(qualified_trust_scores) if qualified_trust_scores else None
            }
        })

@app.route('/reset', methods=['POST'])
def reset():
    """重置所有狀態（測試用）"""
    global state, qualified_trust_scores, high_threshold
    with lock:
        state.clear()
        qualified_trust_scores.clear()
        high_threshold = 0.8
        print("[policy] All state reset")
    return jsonify({'status': 'reset_complete'})

if __name__ == '__main__':
    print(f"[policy] Starting real-time policy server with:")
    print(f"  - TRUST_THRESHOLD: {TRUST_THRESHOLD}")
    print(f"  - Initial high_threshold: {high_threshold}")
    print(f"  - MAX_SAMPLES: {MAX_SAMPLES}")
    print(f"  - MIN_SAMPLES: {MIN_SAMPLES}")
    print(f"  - Real-time threshold updates: ENABLED")
    
    # 安裝依賴： pip3 install flask
    app.run(host='0.0.0.0', port=5000, debug=True)
