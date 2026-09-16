---
name: calibration-result-review
description: 复盘候选实验的多指标表现、假设证伪与预算消耗，解释确定性 Gate/GB/T 结果；不自行决定 ACCEPT 或释放 final-test。
metadata:
  title_zh: "率定结果复盘"
  purpose_zh: "区分候选改进、正式采纳、绝对达标与下一轮研究问题。"
  recommended_actions: "A06_GATE|A07_RESOLVE|A10_EVALUATE_REPORT"
  prompt_references: "references/gbt-22482-accuracy-evaluation-workflow.md"
---

# 率定结果复盘

读取基线与候选的完整窗口、多指标、洪水事件/季节/峰值/退水/水量证据、参数变动、物理模型评估数以及 Gate 结论。分别说明候选是否改变参数、是否改善目标、是否被正式采纳、是否绝对达标，及原假设受到哪些支持或反证。

Gate 的 ACCEPT/KEEP/ROLLBACK、规范精度评定和绝对边界均以确定性结果为准。本 Skill 不把候选改善等同达标，不覆盖 Gate，不在开发选择阶段读取封存 final-test。
