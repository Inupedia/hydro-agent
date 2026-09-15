---
name: xaj-routing-diagnosis
description: 面向新安江模型的峰现时间、过程形状、退水和滞后误差进行汇流诊断。
metadata:
  title_zh: "XAJ 汇流与退水诊断"
  purpose_zh: "区分产流量级问题与汇流记忆/时序问题，为 routing 参数组设计可证伪实验。"
  when_to_use_zh: "峰现提前或滞后|总量接近但过程形状差|退水段系统性过快或过慢|routing 参数组被命中"
  required_evidence_zh: "模拟/观测过程线|峰现时间|峰值误差|退水段|forcing 时间对齐结果"
  recommended_actions: "A04_DIAGNOSE|A05_OPTIMIZE"
  recommended_strategies: "xaj-routing-refine-v1|xaj-hydro-composite-v1"
  counterexamples_zh: "forcing 时间错位必须先排除|总量严重偏差时不能只靠汇流补偿"
  prompt_references: "references/routing.md|references/recession-and-lag.md"
---

# XAJ 汇流与退水诊断

当总体水量基本合理，但峰现、过程展宽或退水形态存在稳定偏差时，优先检验汇流类假设。

诊断顺序：

1. 先排除 forcing 与观测时间错位；
2. 区分峰值量级误差与峰现时间误差；
3. 比较涨水、峰顶、退水段误差是否具有一致方向；
4. 必要时只开放 `routing` 参数组，避免产流/汇流互相补偿；
5. 用 development Gate 检查改善是否可泛化。

本 Skill 不定义 routing 参数的数值上下界。
