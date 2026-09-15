---
name: hydro-data-readiness
description: 在任何预报、诊断或率定之前检查水文数据是否具有可运行、可解释和无泄漏的语义条件。
metadata:
  title_zh: "水文数据准备度"
  purpose_zh: "先确认资料、时间、单位、forcing 与状态语义可信，再允许模型实验。"
  when_to_use_zh: "首次运行前|模型技能为负且怀疑数据问题|数据源或时间窗口变化后"
  required_evidence_zh: "DataSnapshot|forcing/flow 时间范围|单位与 available_at|数据质量结果"
  recommended_actions: "A02_VALIDATE_SCHEME|A03_FORECAST|A04_DIAGNOSE"
  counterexamples_zh: "不能因为 NSE 低就自动认定参数错误|不能读取 final-test 数据帮助率定"
  prompt_references: "references/data-semantics.md|references/leakage-checks.md"
---

# 水文数据准备度

本 Skill 负责回答一个问题：**当前证据是否足以开始一次合法的水文模型实验？**

优先检查：

1. P、蒸散发/蒸发、Q 的物理含义和单位是否与模型适配器一致；
2. `valid_time`、`available_at`、时间步长和站点/流域归属是否一致；
3. warmup、calibration、development 与 final-test 是否严格隔离；
4. 缺测、异常值、重复记录和时间错位是否已被显式记录；
5. 初始状态和 forcing 是否来自当前 DataSnapshot，而不是未来信息。

当整体模型技能很差时，先把“数据/语义/状态问题”作为可证伪假设，而不是立即扩大参数搜索。

## 权限边界

本 Skill 可以建议复核数据和暂停实验；不能修改模型硬边界、Campaign 窗口、objective、Gate 或标准阈值。
