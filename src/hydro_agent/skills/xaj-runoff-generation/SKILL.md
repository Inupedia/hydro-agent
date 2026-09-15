---
name: xaj-runoff-generation
description: 面向新安江模型产流形成与水源划分的诊断 Skill，用于解释洪水响应量级和产流过程误差。
metadata:
  title_zh: "XAJ 产流诊断"
  purpose_zh: "判断问题是否来自蓄水容量、产流非线性或水源划分，而不是把所有峰值误差归给汇流。"
  when_to_use_zh: "总量基本合理但洪水响应强弱异常|降雨响应阈值或产流形态异常|runoff 参数组被诊断命中"
  required_evidence_zh: "降雨-径流过程|事件量级与峰值|当前 diagnosis|模型状态/水源分量（若可用）"
  recommended_actions: "A04_DIAGNOSE|A05_OPTIMIZE"
  recommended_strategies: "xaj-peak-bias-v1|xaj-hydro-composite-v1"
  counterexamples_zh: "不能把峰现时间问题直接判成产流问题|不能直接生成参数值"
  prompt_references: "references/runoff-generation.md|references/source-partition.md"
---

# XAJ 产流诊断

本 Skill 聚焦“降雨进入模型后形成多少径流、以什么过程形成径流”。

诊断时同时看事件量级和时序：峰值偏差可能来自产流，也可能来自汇流；只有在水量、响应强弱和过程证据共同支持时，才把 `runoff` 参数组作为主要实验对象。

优先形成机制假设，再通过小范围、可归因的实验比较候选。具体参数边界、结构性只读参数和联合约束必须由模型注册表/Validator 决定。
