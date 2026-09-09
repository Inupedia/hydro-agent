---
name: gbt-22482-accuracy
description: GB/T 22482-2026 section 6.5 flood forecast accuracy grading for discharge Q. Use when gating calibration candidates, diagnosing forecast skill, or writing the final evaluate report.
metadata:
  title_zh: "国标精度评定"
  purpose_zh: "按 GB/T 22482—2026 §6.5 多指标评定洪峰、峰现、洪量、过程、DC、准确率、GRD、时效与方案等级。"
  when_to_use_zh: "A08 Gate|A06 诊断后|A12 终评|率定是否达标"
  required_evidence_zh: "验证窗模拟与观测流量序列|流域面积可选"
  recommended_actions: "A08_GATE,A06_DIAGNOSE,A12_EVALUATE_REPORT,A10_FREEZE"
  stop_conditions_zh: "方案等级达到 min_scheme_grade|预算耗尽"
  counterexamples_zh: "不要仅凭 NSE 相对改善就 ACCEPT|水位缺测时水位项标 not_applicable"
  min_scheme_grade: "丙"
  basin_class: "auto"
  peak_rel_error_large: "0.20"
  peak_rel_error_mid: "0.30"
  peak_timing_frac: "0.30"
  peak_timing_min_hours: "3"
  runoff_rel_error: "0.20"
  process_amp_frac: "0.20"
  grade_dc_jia: "0.90"
  grade_dc_yi: "0.70"
  grade_dc_bing: "0.50"
  grade_qr_jia: "85.0"
  grade_qr_yi: "70.0"
  grade_qr_bing: "60.0"
---

# GB/T 22482—2026 洪水预报精度评定

## 可调参数（改 metadata 即可）

- `min_scheme_grade`：Gate ACCEPT 最低方案等级（甲/乙/丙）
- `basin_class`：`auto` 按面积；或 `gt3000` / `mid` / `plain`
- 表1 DC/QR 分界与洪峰/峰现许可误差比例均可改

## 指标节点（每个独立计算）

1. `peak_flow` — 洪峰流量 vs 许可误差
2. `peak_timing` — 峰现时间 vs 许可误差
3. `runoff_volume` — 洪量相对误差
4. `process` — 过程点许可误差 / 点准确率
5. `dc_nse` — 确定性系数 DC（NSE）→ 甲乙丙
6. `accuracy_rate` — 准确率 QR → 甲乙丙
7. `grd` — 作业预报 GRD（误差/许可误差）
8. `timeliness` — CET / dh（缺发布时间则 pending）
9. `scheme_grade` — 综合 DC 与 QR（取较低档）

## Gate 规则

- 护栏失败 → ROLLBACK
- `scheme_grade ≥ min_scheme_grade` → ACCEPT
- 否则 → KEEP（**禁止**仅因 NSE 相对改善 ACCEPT）
