---
name: hydro-report-closeout
description: 冻结后组织可复现结论、对照表与失败案例，避免把过程日志当成研究报告。
metadata:
  title_zh: "结果冻结与报告收口"
  purpose_zh: "把 Gate/Resolve 之后的证据整理成可复核报告，而不是堆砌中间日志。"
  when_to_use_zh: "候选冻结后|最终评价后|需要复盘失败实验时"
  required_evidence_zh: "最终方案|Gate 结论|校准/检验过程|Campaign 停止原因|报告产物"
  recommended_actions: "A08_FREEZE|A09_REPLAY|A10_EVALUATE_REPORT"
  activation_stages: "report|gate"
  counterexamples_zh: "报告阶段不能再改 locked objective|不能用未隔离的 final-test 宣称达标"
  prompt_references: "references/report-checklist.md"
---

# 结果冻结与报告收口

报告阶段只回答：结论是否可复核、可复现、可解释。

必须交代：

1. Campaign 停止原因与是否触及 final-test；
2. 校准期 / 发展期 / 检验期指标对照；
3. 采用或回退候选的证据链；
4. 失败假设与未验证边界，避免只写成功路径。

若证据不足，明确写“未证明”，而不是用过程忙碌感替代结论。
