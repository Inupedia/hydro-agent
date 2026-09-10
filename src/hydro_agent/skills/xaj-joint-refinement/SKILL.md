---
name: xaj-joint-refinement
description: Jointly refine only high-value XAJ parameters after phase constraints pass; maximize overall skill without breaking water-balance and flood signatures.
metadata:
  title_zh: "新安江整体收口与联合优化"
  purpose_zh: "P5阶段在已通过的水文约束内提高NSE/KGE，不重新无约束放开全参数。"
  when_to_use_zh: "P5_JOINT_REFINE|P2-P4已通过|整体过程仍有改善空间"
  required_evidence_zh: "nse|kge|volume_rel_error|event_peak_rel_error_median|event_peak_timing_steps_median|event_volume_rel_error_median"
  recommended_actions: "A06_DIAGNOSE,A07_OPTIMIZE,A08_GATE,A09_RESOLVE"
  recommended_strategies: "xaj-local-refine-v1,xaj-bounded-v1"
  stop_conditions_zh: "NSE/KGE达到目标且全部物理guardrail通过|联合搜索平台化"
  counterexamples_zh: "不要把全部指标线性加权成一个可互相抵消的分数|不要重新释放低敏感或teacher冻结参数"
---

# P5 整体收口

P5 才把 NSE/KGE 作为主要优化方向。前提是 P2 水量、P3 退水、P4 洪水事件约束已经基本成立。

采用“硬水文约束 + 软统计目标”：候选只有在水量、洪峰、峰现、洪量 guardrail 不被破坏时，NSE/KGE 的提升才有意义。

优先进行局部、小自由度联合优化；若后续接入 SCE-UA、DE、CMA-ES 或 NSGA-II，它们仍只是数值工具，Agent 负责决定当前允许开放哪些参数和为什么。
