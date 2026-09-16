---
name: xaj-calibration-diagnosis
description: 根据已观测的水文现象和 XAJ 过程语义建立可证伪诊断假设，说明支持、反证及候选参数组；不输出连续参数值。
metadata:
  title_zh: "XAJ 率定诊断"
  purpose_zh: "把现象转成蒸散发、产流或汇流机制假设，并限定下一项实验的参数组。"
  recommended_actions: "A04_DIAGNOSE|A05_OPTIMIZE"
  prompt_references: "references/xaj-calibration-workflow.md|references/xaj-calibration-parameter-semantics.md|references/xaj-calibration-parameter-relations.md|references/xaj-calibration-escalation.md|references/xaj-water-balance-water-balance.md|references/xaj-water-balance-evap-runoff-semantics.md|references/xaj-runoff-generation-runoff-generation.md|references/xaj-runoff-generation-source-partition.md|references/xaj-routing-diagnosis-routing.md|references/xaj-routing-diagnosis-recession-and-lag.md"
---

# XAJ 率定诊断

先引用水文证据审查的现象、窗口和 Evidence ID，再判断水量、产流与汇流哪一种解释更可能成立。每个假设说明支持证据、可能反证、缺失证据、候选参数组和预期可观测变化；forcing 时间错位须先排除。洪量接近而洪峰提前时优先检查汇流，长期水量偏差不能只靠汇流补偿。

参数机制详见 references/，按当前现象选择读取。只输出合法的 `evap`、`runoff`、`routing` 等组和实验方向。绝对参数边界、XAJ 计算与连续参数向量由确定性 Core/优化器负责；final-test 不能进入诊断。
