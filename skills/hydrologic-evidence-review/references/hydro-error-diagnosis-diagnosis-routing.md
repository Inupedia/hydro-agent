# 诊断路由

诊断后按问题类型激活更窄的 Skill：

- 数据语义或建模准备异常 → `hydrology-data-review`
- 水量、产流、峰现、过程形状或退水需要机制解释 → 当前模型绑定的 `*-calibration-diagnosis`
- 需要把假设变成数值实验 → `calibration-experiment-design`
- 候选实验需要解释 Gate 与证伪结果 → `calibration-result-review`

多个过程同时可疑时允许并列假设，但每轮实验尽量缩小可变参数组，便于归因。

模型诊断 Skill 必须与任务的 `model_id` 一致；不得把 XAJ、GR4J、HBV、Tank 或 SAC-SMA-inspired 的参数组互相套用。
