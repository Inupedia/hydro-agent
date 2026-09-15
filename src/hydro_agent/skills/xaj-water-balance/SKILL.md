---
name: xaj-water-balance
description: 面向新安江模型的长期水量、蒸散发与径流总量诊断，为率定提出可证伪的水量平衡假设。
metadata:
  title_zh: "XAJ 水量平衡诊断"
  purpose_zh: "区分蒸散发、蓄水与产流总量问题，避免用汇流参数补偿水量偏差。"
  when_to_use_zh: "PBIAS 或总径流量异常|模拟长期偏湿/偏旱|流域画像与模拟水量不一致"
  required_evidence_zh: "P/PET或蒸发语义/Q|PBIAS与总量比|流域面积|预热后水量统计"
  recommended_actions: "A06_DIAGNOSE|A07_OPTIMIZE"
  recommended_strategies: "xaj-water-balance-v1|xaj-hydro-composite-v1"
  counterexamples_zh: "不能用本 Skill 覆盖 Validator 参数边界|不能把流域画像当作真值"
  prompt_references: "references/water-balance.md|references/evap-runoff-semantics.md"
---

# XAJ 水量平衡诊断

先判断偏差是否来自长期水量收支，再决定是否值得开放 `evap`、`runoff` 参数组。

推荐顺序：

1. 排除 P/Q/蒸发语义和时间对齐问题；
2. 比较降水、模拟/实测径流总量和蒸散发相关证据；
3. 判断是系统性总量偏差，还是仅洪峰/过程形态偏差；
4. 形成可证伪假设，例如“蒸散发能力不足导致长期偏湿”；
5. 交给 `hydro-experiment-design` 设计受限实验。

本 Skill 可以建议参数**组**，不直接提供参数值。硬边界和联合约束只由 XAJ Validator/Protocol 提供。
