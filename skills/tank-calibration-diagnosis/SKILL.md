---
name: tank-calibration-diagnosis
description: 根据已观测的水文现象和水箱模型过程语义建立可证伪诊断假设，说明支持、反证及候选参数组；不输出连续参数值。
metadata:
  title_zh: "水箱模型率定诊断"
  purpose_zh: "把现象转成表层、中层、基流或汇流机制假设，并限定下一项实验的参数组。"
  recommended_actions: "A04_DIAGNOSE|A05_OPTIMIZE"
  prompt_references: "references/tank-parameter-semantics.md"
---

# 水箱模型率定诊断

先引用水文证据审查的现象、窗口和 Evidence ID，再判断表层水箱（surface）、中间水箱（intermediate）、基流水箱（base）与汇流（routing）哪一种解释更可能成立。每个假设说明支持证据、可能反证、缺失证据、候选参数组和预期可观测变化；forcing 时间错位须先排除。

参数机制：
- `surface`：H1/A11/A12/B1，主导超渗与表层出流、下渗
- `intermediate`：H2/A2/B2，主导壤中流与向深层补给
- `base`：A3，主导基流强度
- `routing`：K/N，主导 Nash 线性水库滞时与展宽

只输出合法的 `surface`、`intermediate`、`base`、`routing` 等组和实验方向。绝对参数边界、水箱计算与连续参数向量由确定性 Core/优化器负责；final-test 不能进入诊断。
