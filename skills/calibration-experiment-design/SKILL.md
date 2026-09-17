---
name: calibration-experiment-design
description: 把有证据的水文假设转成受 Campaign、预算和参数边界约束的率定实验计划，决定测什么与如何证伪；具体参数由优化器搜索。
metadata:
  title_zh: "率定实验设计"
  purpose_zh: "选择合法参数组、目标、策略、搜索范围和预算，并声明预期与证伪条件。"
  recommended_actions: "A05_OPTIMIZE|A07_RESOLVE"
  prompt_references: "references/hydro-experiment-design-experiment-strategies.md|references/hydro-experiment-design-hypothesis-testing.md|references/hydro-experiment-design-budget-allocation.md|references/hydro-campaign-design-period-splitting.md|references/hydro-campaign-design-objective-locking.md|references/hydro-campaign-design-convergence-policy.md"
---

# 率定实验设计

输入包括 DiagnosisHypothesis、上一轮 Gate/Resolve、敏感性证据、合法参数组与边界、已花费的物理模型评估数、剩余预算和搜索历史。输出应明确假设、参数组、合法 strategy/objective、实验窗口、数值预算、预期现象、反证条件与停止或换假设条件。

不要重复同一参数组、目标和 seed 的无信息搜索；不得在 Campaign 内改锁定的目标或数据分区。Morris/DDS/SCE-UA、物理模型运行和具体 XAJ 参数值由 Core/优化器执行。预算耗尽应按 Campaign 的 `BUDGET_EXHAUSTED` 收口，不能称作收敛。

策略和参数组必须属于当前 `model_id`。运行时 `peak` 只表示峰值量级分数，不包含峰现时间；`composite` 当前等价于 KGE。不得根据名称臆造额外指标含义。
