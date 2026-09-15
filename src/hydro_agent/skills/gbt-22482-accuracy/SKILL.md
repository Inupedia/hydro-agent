---
name: gbt-22482-accuracy
description: 说明何时调用 GB/T 22482—2026 的确定性评定能力以及如何解释结果；Skill 本身不保存任何规范阈值。
metadata:
  title_zh: "GB/T 22482 精度评定流程"
  purpose_zh: "把规范评定作为确定性 evaluator 使用，并将标准 provenance 与科研 Gate policy 分离。"
  when_to_use_zh: "候选进入 A08 Gate|冻结后最终评价|需要解释方案精度等级时"
  required_evidence_zh: "观测/模拟过程|流域面积与评定配置|StandardRepository provenance|科研 Gate policy"
  recommended_actions: "A08_GATE|A12_EVALUATE_REPORT"
  counterexamples_zh: "不能在 Skill 中硬写甲乙丙阈值|不能让 LLM 临时解释成新的准入条件"
  prompt_references: "references/evaluation-workflow.md"
---

# GB/T 22482 精度评定流程

本 Skill 只负责“**何时调用、如何理解**”，不拥有规范数值。

运行时必须：

1. 从 `hydro_agent.standards.StandardRepository` 获取当前版本标准配置与 provenance；
2. 由确定性的 GB/T evaluator 计算 DC/QR/许可误差/等级等结果；
3. 将标准评定报告作为 Evidence；
4. 再由版本化科研 Gate policy 决定候选是否满足本课题的采用/资格要求。

GB/T 22482—2026 已发布但实施日期为 2027-02-01；本项目可作为研究目标规范使用，但报告必须保留 published/effective/status provenance。
