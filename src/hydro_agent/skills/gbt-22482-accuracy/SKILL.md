---
name: gbt-22482-accuracy
description: Version-aware GB/T 22482 flood forecast accuracy grading for discharge Q. Use for development validation and final evaluation, not as a universal calibration objective.
metadata:
  title_zh: "国标精度评定"
  purpose_zh: "按配置的 GB/T 22482 标准画像评定洪峰、峰现、洪量、过程、DC、准确率、GRD与时效。"
  when_to_use_zh: "P6开发验证|A12最终评定|工程方案验收"
  required_evidence_zh: "验证窗模拟与观测流量序列|流域面积|标准版本配置"
  recommended_actions: "A08_GATE,A12_EVALUATE_REPORT,A10_FREEZE"
  stop_conditions_zh: "开发验证达到配置的最低方案等级|最终holdout只评一次"
  counterexamples_zh: "不要仅凭NSE相对改善就通过|不要把已发布但尚未实施的新标准冒充现行标准|不要把国标终评阈值当P2-P4阶段优化目标"
  effective_standard: "GB/T 22482-2008"
  next_standard: "GB/T 22482-2026"
  next_effective_date: "2027-02-01"
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

# GB/T 22482 洪水预报精度评定

## 标准版本

评价器必须显式记录采用的标准画像。当前项目日期下现行标准是 `GB/T 22482-2008`；`GB/T 22482-2026` 已发布但从 `2027-02-01` 起实施。切换标准时，应更新/审查阈值配置与测试，而不是只改标题。

本 Skill 中的数值阈值是当前工程评价器的**可配置画像**。它们必须由项目采用的标准版本或业主要求审定，不能被当成跨版本永久常量。

## 指标节点

1. `peak_flow` — 洪峰流量误差；
2. `peak_timing` — 峰现时间误差；
3. `runoff_volume` — 洪量相对误差；
4. `process` — 过程点准确率；
5. `dc_nse` — 确定性系数 DC/NSE；
6. `accuracy_rate` — 准确率 QR；
7. `grd` — 误差/许可误差；
8. `timeliness` — 时效；
9. `scheme_grade` — 按配置规则综合方案等级。

## 在率定协议中的位置

P2-P4 使用各自的水文 Phase Gate，不使用国标总等级驱动参数搜索。P5完成整体收口后，P6 Development Validation 才用完整国标画像做可迭代验收；最终 holdout 在 Freeze 后只评价一次。
