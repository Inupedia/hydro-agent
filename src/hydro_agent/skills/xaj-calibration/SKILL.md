---
name: xaj-calibration
description: Bounded XAJ parameter calibration vs observed Q under GB/T 22482 multi-metric gating. Use when diagnose skill is below min scheme grade, MODEL hypothesis, or after KEEP/ROLLBACK with budget.
metadata:
  title_zh: "有界参数率定"
  purpose_zh: "只允许受约束策略搜索；以 GB/T 22482 方案等级达标为停止条件，并在独立验证窗上 Gate。"
  when_to_use_zh: "诊断指向 MODEL|方案等级低于 min_scheme_grade|仍有优化预算|已有候选或准备产生候选"
  required_evidence_zh: "策略 id|率定 snapshot|独立验证窗|GB/T 指标"
  recommended_actions: "A07_OPTIMIZE,A08_GATE,A09_RESOLVE,A10_FREEZE"
  recommended_strategies: "xaj-bounded-v1,xaj-peak-bias-v1,xaj-local-refine-v1"
  stop_conditions_zh: "方案等级达到 gbt-22482-accuracy.min_scheme_grade|Gate 连续失败|优化预算用尽"
  counterexamples_zh: "不要让 LLM 直接发明连续参数向量|不要在自动回路使用 xaj-hydrologist-manual-v1|不要仅凭 NSE 改善 ACCEPT"
  nse_good_enough: "0.5"
---

# XAJ 有界参数率定

## 停止条件（国标）

率定是否完成以 **`gbt-22482-accuracy`** skill 为准：

- 方案等级（DC 与 QR 综合）≥ `min_scheme_grade`（默认丙）→ 可 `A10_FREEZE`
- `nse_good_enough` 与国标表1 **DC 丙级**对齐（默认 0.50），仅作兼容别名；权威在 `grade_dc_bing`

详见 skill `gbt-22482-accuracy`。

## 率定回路

1. `A05_FORECAST` → `A06_DIAGNOSE`（读 GB/T 指标与误差形态）
2. 方案未达 `min_scheme_grade` → `A07_OPTIMIZE`（有界策略）
3. `A08_GATE`：多指标子图评定；仅国标达标才 ACCEPT
4. `A09_RESOLVE` → `A10_FREEZE` → `A11_REPLAY` → `A12_EVALUATE_REPORT`

## 硬约束

- **禁止**发明连续参数向量
- **禁止**自动回路使用 `xaj-hydrologist-manual-v1`
- **禁止**仅靠 NSE 相对改善 ACCEPT
- `KG + KI < 1`

## 参考

- [XAJ 参数说明](references/xaj-parameters.md)
- [误差 → 参数组](references/error-to-params.md)
