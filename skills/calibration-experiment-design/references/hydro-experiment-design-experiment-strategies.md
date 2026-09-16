# 实验策略选择

优先使用运行时已注册 strategy，而不是在 Skill 中创建新的搜索算法配置。

- 水量偏差主导：可考虑 `xaj-water-balance-v1`。
- 汇流/退水主导：可考虑 `xaj-routing-refine-v1`。
- 多过程混合：可考虑 `xaj-hydro-composite-v1`。
- 已有稳定基线的小范围精调：可考虑 `xaj-local-refine-v1`。
- 局部窗口触边界且绝对边界仍有空间：按运行时协议进入 `xaj-broadened-refine-v1`。

最终可用 strategy 以 `CalibrationStrategyRegistry` 为准。