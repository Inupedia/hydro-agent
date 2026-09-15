---
name: xaj-calibration
description: 协调 XAJ 诊断、假设、实验设计、数值优化与独立 Gate 的总编排 Skill；不直接生成参数值或定义硬规则。
metadata:
  title_zh: "XAJ 率定实验编排"
  purpose_zh: "把多个专业诊断 Skill 组织成可解释、可验证、可追溯的一轮轮 XAJ 科学实验。"
  when_to_use_zh: "A06 已形成模型假设后|准备 A07 参数实验|Gate 后需要组织下一轮 XAJ 实验"
  required_evidence_zh: "hydro diagnosis|Campaign locks|当前基线|专业诊断 Skill 输出|上一轮 Gate"
  recommended_actions: "A06_DIAGNOSE|A07_OPTIMIZE|A08_GATE|A09_RESOLVE"
  recommended_strategies: "xaj-water-balance-v1|xaj-routing-refine-v1|xaj-hydro-composite-v1|xaj-local-refine-v1"
  counterexamples_zh: "不直接输出原始参数向量|不定义硬边界|不以单一 NSE 阈值结束 Campaign|不改 final-test"
  prompt_references: "references/workflow.md|references/parameter-semantics.md|references/parameter-relations.md|references/escalation.md"
---

# XAJ 率定实验编排

本 Skill 是**协调器**，不是一个把所有水文知识塞在一起的“大 Skill”。

标准流程：

1. `hydro-data-readiness` 确认实验合法；
2. `hydro-error-diagnosis` 形成现象和候选假设；
3. 按证据调用 `xaj-water-balance`、`xaj-runoff-generation`、`xaj-routing-diagnosis`；
4. `hydro-experiment-design` 把主要假设转换为 ExperimentPlan；
5. optimizer 在 Validator 给出的合法空间内搜索具体参数值；
6. A08 在 development 数据上独立比较候选与当前基线；
7. A09 执行 ADOPT/KEEP/ROLLBACK；
8. 继续循环，直到 **Campaign 自身**给出 `stop_reason`；
9. A10 冻结后才允许 final-test/replay 和最终报告。

## 三条硬原则

- Agent 决定 **WHAT / WHY**，optimizer 决定具体参数值。
- Skill 是 advisory knowledge；Model Validator、Protocol、Standard、Gate 才拥有硬执行权。
- “一次指标很好”不等于“研究收敛”，停止只认预注册 Campaign 证据。
