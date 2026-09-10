---
name: xaj-calibration-protocol
description: Stage XAJ calibration like a hydrologist: water balance first, then source/recession, routing/events, joint refinement, development validation, and one final holdout.
metadata:
  title_zh: "新安江模型分阶段率定协议"
  purpose_zh: "负责率定阶段顺序与阶段切换，不直接替代各阶段的专业 Skill。"
  when_to_use_zh: "进入XAJ率定|阶段Gate通过|阶段平台失败需要归因"
  required_evidence_zh: "calibration_phase|phase_history|独立calibration/development/final时段"
  recommended_actions: "A06_DIAGNOSE,A07_OPTIMIZE,A08_GATE,A09_RESOLVE,A10_FREEZE"
  stop_conditions_zh: "P6开发验证通过|DATA/FORCING/STRUCTURAL_LIMIT|硬预算"
  counterexamples_zh: "不要一开始全参数追NSE|不要把平台收敛等同于率定成功|不要读取最终holdout参与调参"
---

# 新安江模型分阶段率定协议

核心原则：**先水量、后过程；先分解、后整体；先模块、后系统。**

阶段顺序：

1. `P0_DATA_REGIME`：资料完整性、代表性、强迫与模型适用性。
2. `P1_PARAMETER_PRIOR`：参数经验初值、物理边界与可率定标记。
3. `P2_WATER_BALANCE`：多年/年际/季节水量平衡。
4. `P3_SOURCE_RECESSION`：快流、壤中流、地下水与退水结构。
5. `P4_ROUTING_EVENT`：洪峰、峰现、洪量和过程形态。
6. `P5_JOINT_REFINE`：在前述物理约束内整体提高 NSE/KGE。
7. `P6_DEVELOPMENT_VALIDATION`：独立开发集做最终可迭代验收。
8. `P7_FINAL_HOLDOUT`：Freeze 后只运行一次，禁止再调参。

`20` 次优化只能是 hard ceiling。每个阶段是否继续由 HydrologicPhaseGate 与 SearchConvergenceController 共同决定。

阶段 `PHASE_PASS` 才允许进入下一阶段；`PLATEAU_FAIL` 说明本阶段搜索已没有明显收益但水文目标仍未达标，应归因到资料、强迫、模型结构或参数边界，而不是直接 Freeze 成“成功方案”。
