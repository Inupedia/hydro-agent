---
name: forecast-diagnose
description: Diagnose forecast errors against observed discharge, form constrained hypotheses, and recommend the next experiment. Use after a base forecast, after Gate rejection, or before another calibration cycle.
metadata:
  title_zh: "预报诊断"
  purpose_zh: "根据误差形态提出受约束的原因假说，并指定下一实验。"
  when_to_use_zh: "已有基础预报|Gate 拒绝后需要解释|准备再次优化前"
  required_evidence_zh: "lead 1/2/3 预报|同期观测|偏差/洪峰比"
  recommended_actions: "A06_DIAGNOSE,A07_OPTIMIZE,A10_FREEZE"
  recommended_strategies: "xaj-bounded-v1,xaj-peak-bias-v1,xaj-local-refine-v1"
  stop_conditions_zh: "观测不足以诊断|预算耗尽"
  counterexamples_zh: "没有预报证据时不要空诊断|不要把单次 forcing 分歧直接当成模型缺陷"
---

# 预报诊断

## 目标

对比模拟 lead 与同期观测流量，读取 `hydro.diagnosis.metrics`（尤其 NSE），给出受约束假说与下一动作。

## 步骤

1. 确认已有 `A05_FORECAST` 证据与观测
2. 执行 `A06_DIAGNOSE`
3. 按误差形态推荐策略（详见 [error-to-params](../xaj-calibration/references/error-to-params.md)）：
   - 洪峰低估 → `xaj-peak-bias-v1`，组 `runoff`+`routing`，目标 `composite`
   - 洪峰偏高 → `xaj-local-refine-v1`
   - 模式不清 → `xaj-bounded-v1`
4. 若 NSE 已达到 `xaj-calibration` 的 `nse_good_enough` → 建议 `A10_FREEZE`
5. 否则把下一实验交给 `xaj-calibration`

## 禁止

- 没有预报证据时空诊断
- 把单次 forcing 分歧直接当成模型缺陷
- 自动回路选择 `xaj-hydrologist-manual-v1`
