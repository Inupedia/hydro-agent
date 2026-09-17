# 实验策略选择

优先使用当前任务 `model_id` 在运行时注册的 strategy，而不是在 Skill 中创建新的搜索算法配置。最终合法集合只认 `hydro.available_strategies` 与 `CalibrationStrategyRegistry`。

- 水量偏差主导：选当前模型的 water-balance / production 类已注册策略与参数组。
- 汇流、退水或峰现主导：选当前模型的 routing-refine 类策略；先排除 forcing 时间错位。
- 多过程混合且证据不能进一步区分：使用当前模型的 bounded/composite 策略，同时承认归因能力较弱。
- 已有稳定基线的小范围精调：使用当前模型的 local-refine 策略。
- 局部窗口触边界且绝对边界仍有空间：只按当前模型的 broadened-refine 协议扩大。

不得从其他模型照抄 strategy id。`peak` objective 当前只评价峰值量级，不评价峰现时间；峰现问题需要 routing 参数组，并由 development Gate 的 timing evidence 判定。`composite` 当前是 KGE 兼容别名，不是多事件、多季节加权目标。
