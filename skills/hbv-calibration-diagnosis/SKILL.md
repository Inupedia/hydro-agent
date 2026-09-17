---
name: hbv-calibration-diagnosis
description: 根据已观测的水文现象和 HBV-light 过程语义建立可证伪诊断假设，说明支持、反证及候选参数组；不输出连续参数值。
metadata:
  title_zh: "HBV 率定诊断"
  purpose_zh: "把现象转成积雪、土壤、地下水或汇流机制假设，并限定下一项实验的参数组。"
  recommended_actions: "A04_DIAGNOSE|A05_OPTIMIZE"
  prompt_references: "references/hbv-parameter-semantics.md"
---

# HBV 率定诊断

先引用水文证据审查的现象、窗口和 Evidence ID，再判断积雪（snow）、土壤（soil）、地下水（groundwater）与汇流（routing）哪一种解释更可能成立。每个假设说明支持证据、可能反证、缺失证据、候选参数组和预期可观测变化；forcing 时间错位须先排除。气温缺失或单位错误时，不得把雪过程当作可调参数去拟合。

参数机制：
- `snow`：TT/CFMAX/CFR/CWH，主导融雪时机、冻融与积雪持水
- `soil`：FC/BETA/LP，主导产流比例、蒸散发与长期水量
- `groundwater`：K0/K1/K2/PERC，主导基流、消退与上下层交换
- `routing`：MAXBAS，主导洪峰相位与过程线展宽

只输出合法的 `snow`、`soil`、`groundwater`、`routing` 等组和实验方向。绝对参数边界、HBV 计算与连续参数向量由确定性 Core/优化器负责；final-test 不能进入诊断。
