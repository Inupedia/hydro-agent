# 误差形态 → 策略与参数组

对齐 `diagnose_forecast_errors` 与有界策略注册表。

| 现象 | 假说 | strategy_id | param_groups | objective |
|---|---|---|---|---|
| 洪峰明显低估 | MODEL | `xaj-peak-bias-v1` | runoff, routing | composite |
| 洪峰明显偏高 | MODEL | `xaj-local-refine-v1` | runoff, routing | nse |
| 偏差不大且 NSE ≥ nse_good_enough | MODEL | — | — | — → `A10_FREEZE` |
| 误差模式不清 | MODEL | `xaj-bounded-v1` | evap, runoff, routing | nse |
| 系统性偏低也可能是降水弱 | FORCING | — | — | — → `A01_CHECK_DATA` |
| 初始土壤偏干 | STATE | — | — | — → 校验/重建状态 |

## 经典率定要点（蒸馏）

- 用独立验证窗 Gate，避免在率定窗上过拟合
- 目标以 NSE（或 peak/composite）对比观测；达标即停，勿无限搜索
- 先动敏感且允许率定的参数组；避免一次扰动全部固定参数
- Gate KEEP/ROLLBACK 后若仍有预算，轮换有界策略再试
