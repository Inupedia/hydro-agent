---
name: hydrology-data-review
description: 审查水文资料、DEM 与模型准备证据，解释资料问题的水文风险并提出补充检查；Data Gate 仍由确定性程序执行。
metadata:
  title_zh: "水文资料审查"
  purpose_zh: "把资料质量和建模准备证据转成可核对的风险与检查建议。"
  recommended_actions: "M01_CHECK_MATERIALS|A01_CHECK_DATA|A02_VALIDATE_SCHEME"
  prompt_references: "references/hydro-data-readiness-data-semantics.md|references/hydro-data-readiness-leakage-checks.md|references/hydro-modeling-prep-modeling-checklist.md"
---

# 水文资料审查

先读取 DataSnapshot、质量掩码、时间范围、单位、available_at、预热长度和 DEM/单元方案状态。分别说明已证实的问题、可能的水文影响、需要补充的检查和反证；不要由低 NSE 倒推资料必然错误。

资料的 PASS/BLOCK、可用样本、时间隔离和建模 ready 状态只引用 Data Gate 与 ModelPlan 的确定性结果。本 Skill 不修改资料、不跳过建模边界复核，也不读取封存的 final-test 帮助率定。
