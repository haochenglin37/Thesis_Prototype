from flask import Flask, request, jsonify
import threading, math

app = Flask(__name__)
state = {}
lock  = threading.Lock()

EXPECTED_INTERVAL = 1    # 期望间隔 (s)
P_SUCCESS_TH      = 0.005   # p-value 成功阈值
P_TRUST_TH        = 0.005   # p-value 信任更新阈值
TRUST_THRESHOLD   = 0.2    # trust 放行阈值

@app.route('/policy', methods=['POST'])
def policy():
    data = request.get_json(force=True)
    ip    = data.get('ip')
    delta = data.get('time_delta', 0.0)

    with lock:
        entry = state.get(ip, {'success_count': 0, 'trust': 0.0})

        # 计算双尾 p-value (指数分布)
        cdf_fast = 1.0 - math.exp(-delta / EXPECTED_INTERVAL)
        cdf_slow = 1.0 - cdf_fast
        p_val    = min(cdf_fast, cdf_slow) * 2.0

        # 更新连续成功计数
        if p_val > P_SUCCESS_TH:
            entry['success_count'] += 1
        else:
            entry['success_count'] = 0

        # 计算 logistic 因子 y
        x = entry['success_count']
        y = 100.0 / (1.0 + math.exp(-0.5 * (x - 50.0)))

        # 更新 trust 分数
        if p_val > P_TRUST_TH:
            entry['trust'] += y * 0.05
            if entry['trust'] > 1.0:
                entry['trust'] = 1.0
        else:
            entry['trust'] *= 0.2

        state[ip] = entry
        action = 'forward' if entry['trust'] > TRUST_THRESHOLD else 'drop'
        trust  = entry['trust']

    return jsonify({
        'action' : action,
        'trust'  : trust,
        'p_value': p_val
    })

if __name__ == '__main__':
    # 安装依赖： pip3 install flask
    app.run(host='0.0.0.0', port=5000)
