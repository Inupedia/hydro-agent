---
name: hydro-error-diagnosis
description: 将模型输出与观测差异整理成可证伪的水文误差模式，并路由到更具体的 XAJ 过程诊断 Skill。
metadata:
  title_zh: "水文误差诊断"
  purpose_zh: "先解释误差模式，再决定应该检查数据、产流、蒸散发还是汇流。"
  when_to_use_zh: "已有基线预报后|每轮 Gate/Resolve 后重新诊断|候选没有稳定改进时"
  required_evidence_zh: "观测与模拟过程|NSE/KGE/PBIAS 等指标|峰值/时序/水量特征|上一轮实验结果"
  recommended_actions: "A04_DIAGNOSE|A05_OPTIMIZE"
  counterexamples_zh: "单一指标不能直接推出具体参数|诊断结论不能替代独立验证"
  prompt_references: "references/metric-patterns.md|references/diagnosis-routing.md"
---

# 水文误差诊断

诊断输出应是“**现象 → 假设 → 需要的证据 → 下一项实验**”，而不是“指标差 → 调参数”。

优先区分：

- 数据/forcing/初始状态问题；
- 长期水量或总体偏差问题；
- 产流响应强弱、阈值或源分配问题；
- 洪峰时序、过程形态、退水与汇流问题；
- 多过程耦合导致的混合误差。

每个主要假设都应说明什么结果会支持它、什么结果会推翻它。若证据不足，返回 UNKNOWN 并设计诊断实验，而不是扩大搜索空间。

## 停止规则

本 Skill **不依据 NSE/KGE/PBIAS 的单点阈值宣布率定结束**。是否停止由 Campaign 的预注册 `ConvergencePolicy` 和 `stop_reason` 决定。
