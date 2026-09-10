---
name: xaj-flood-routing
description: Calibrate XAJ flood peak, timing, volume, and routing shape using an event bank after water balance and recession behaviour are controlled.
metadata:
  title_zh: "新安江洪水事件与汇流率定"
  purpose_zh: "P4阶段逐场检查洪峰、峰现、洪量和过程形态，而不是只看多年NSE。"
  when_to_use_zh: "P4_ROUTING_EVENT|洪峰偏高偏低|峰现提前滞后|洪水过程过尖过平"
  required_evidence_zh: "event_peak_rel_error_median|event_peak_timing_steps_median|event_volume_rel_error_median|large_event_*"
  recommended_actions: "A06_DIAGNOSE,A07_OPTIMIZE,A08_GATE,A09_RESOLVE"
  recommended_strategies: "xaj-peak-bias-v1,xaj-local-refine-v1"
  stop_conditions_zh: "代表性洪水的峰值/峰现/洪量约束通过且水量不显著回退|本阶段平台化"
  counterexamples_zh: "不要用全序列最大峰替代多场洪水|不要用一个加权总分掩盖严重峰现或洪量失败"
---

# P4 洪水事件与汇流

先从历史连续序列建立 Flood Event Bank，再按流域自身的洪峰分位把事件相对分成 small / medium / large。分级阈值必须 basin-adaptive，不能把某一篇论文的固定雨量阈值写死到通用 Skill。

每次候选至少检查：

- 事件洪峰相对误差；
- 事件峰现误差（用计算时段数表达）；
- 事件洪量相对误差；
- 大洪水子集表现；
- 已通过的 P2 水量约束不能显著退化。

若峰值量级已接近而峰现仍错，优先 routing；若洪量也错，先回到对应上游物理阶段，禁止用汇流参数补偿产流错误。
