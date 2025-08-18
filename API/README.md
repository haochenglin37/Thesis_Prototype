# API

1. 基於信任值的回應
   `rule.py`
   - Input：POST `/policy`，JSON 包含 `ip`、`time_delta`
   - Output：`action` (`forward` 或 `drop`)、`trust`、`p_value`【F:API/rule.py†L13-L53】
   - Parameters：`EXPECTED_INTERVAL`、`P_SUCCESS_TH`、`P_TRUST_TH`、`TRUST_THRESHOLD`

2. 前 25% 優先權回應
   `pq.py`
   - Input：POST `/policy`，JSON 包含 `ip`、`time_delta`
   - Output：`action` (`high`、`low` 或 `drop`)、`trust`、`p_value`、`high_threshold` 等【F:API/pq.py†L103-L179】
   - Parameters：與 `rule.py` 相同並新增 `TOP_PERCENT`
   - Extra：提供 `/stats`、`/debug_heap`、`/reset` 端點以查詢與重置狀態【F:API/pq.py†L181-L255】
