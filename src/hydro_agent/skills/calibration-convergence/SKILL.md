---
name: calibration-convergence
description: Stop hydrologic calibration from unique-experiment progress curves instead of fixed loop counts or repeated Gate calls.
metadata:
  title_zh: "率定搜索收敛控制"
  purpose_zh: "判断在当前水文阶段继续做一次新实验是否仍有信息增益。"
  when_to_use_zh: "A08 Gate|已有多个同阶段unique experiment|候选反复回滚"
  required_evidence_zh: "experiment_id|calibration_phase|phase progress value|最近unique experiments"
  recommended_actions: "A08_GATE,A09_RESOLVE,A06_DIAGNOSE,A10_FREEZE"
  stop_conditions_zh: "best-so-far阶段进度的窗口增益/斜率/跨度均趋平|硬预算"
  counterexamples_zh: "不要把Gate调用次数当实验次数|不要把同一candidate重复验证写进收敛曲线|不要把PLATEAU等同于质量达标"
---

# 率定搜索收敛

收敛曲线横轴必须是 **unique calibration experiment**，每个点至少绑定 `action_run_id + candidate_scheme_id + validation window`。重复 Gate 只能复用旧结论，不能新增曲线点。

收敛控制器不负责判断水文学上是否合格。它只判断当前阶段继续搜索是否值得：观察最近若干个 best-so-far 进度点的累计增益、斜率和跨度。

平台化后必须结合 HydrologicPhaseGate：

- 阶段目标已经通过 → `PLATEAU_PASS` / 进入下一阶段；
- 阶段目标仍未通过 → `PLATEAU_FAIL`，要求资料/强迫/结构/参数边界归因；
- 明确存在 forcing/model 缺项 → `FORCING_LIMIT` 或 `STRUCTURAL_LIMIT`。

剩余优化轮数永远不是继续搜索的理由。
