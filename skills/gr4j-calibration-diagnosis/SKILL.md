---
name: gr4j-calibration-diagnosis
description: 根据已观测的水文现象和 GR4J 过程语义建立可证伪诊断假设，说明支持、反证及候选参数组；不输出连续参数值。
metadata:
  title_zh: "GR4J 率定诊断"
  purpose_zh: "把现象转成产流库、交换或汇流机制假设，并限定下一项实验的参数组。"
  recommended_actions: "A04_DIAGNOSE|A05_OPTIMIZE"
  prompt_references: "references/gr4j-parameter-semantics.md"
---

# GR4J 率定诊断

先引用水文证据审查的现象、窗口和 Evidence ID，再判断产流库（production）、地下水交换（exchange）与汇流（routing）哪一种解释更可能成立。每个假设说明支持证据、可能反证、缺失证据、候选参数组和预期可观测变化；forcing 时间错位须先排除。

参数机制：
- `production`：X1 产流库容量，主导长期水量与蒸散发调节
- `exchange`：X2 地下水交换，主导基流偏高/偏低与水量闭合
- `routing`：X3/X4 汇流库与单位线时间基，主导洪峰相位与退水形态

只输出合法的 `production`、`exchange`、`routing` 等组和实验方向。绝对参数边界、GR4J 计算与连续参数向量由确定性 Core/优化器负责；final-test 不能进入诊断。
