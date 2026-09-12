---
name: gbt-22482-accuracy
description: Apply the structured GB/T 22482-2026 knowledge profile for flood-forecast accuracy evaluation. Use when gating calibration candidates, diagnosing forecast skill, or writing the final evaluate report.
metadata:
  title_zh: "国标精度评定"
  purpose_zh: "调用知识平台中的 GB/T 22482—2026 洪水预报精度规则，对洪峰、峰现、洪量、过程、DC、准确率、GRD、时效与方案等级进行确定性评定。"
  when_to_use_zh: "A08 Gate|A06 诊断后|A12 终评|率定是否达标"
  required_evidence_zh: "验证窗模拟与观测流量序列|流域面积可选"
  recommended_actions: "A08_GATE,A06_DIAGNOSE,A12_EVALUATE_REPORT,A10_FREEZE"
  stop_conditions_zh: "达到项目 Gate policy 要求|预算耗尽"
  counterexamples_zh: "不要仅凭 NSE 相对改善就 ACCEPT|不要在 Skill metadata 中复制标准阈值|水位缺测时水位项标 not_applicable"
  knowledge_refs: "standard:gbt-22482-2026|policy:hydro-agent-research-v1"
---

# GB/T 22482—2026 洪水预报精度评定 Skill

## 角色

本 Skill 只描述**何时、为什么、如何使用规范知识**，不保存规范阈值。

规范版本、条款、许可误差和等级阈值统一来自：

- `hydro_agent.knowledge.KnowledgeRepository`
- `knowledge/data/standards/gbt-22482-2026.json`

Hydro-Agent 自己的科研 Gate 要求来自：

- `knowledge/data/policies/hydro-agent-research-v1.json`

标准知识与科研策略必须分离。

## 指标节点

当前 Q / discharge 评定子图包括：

1. `peak_flow` — 洪峰流量许可误差
2. `peak_timing` — 峰现时间许可误差
3. `runoff_volume` — 洪量误差
4. `process` — 过程评定
5. `dc_nse` — 确定性系数 DC（NSE）等级
6. `accuracy_rate` — 准确率 QR 等级
7. `grd` — 作业预报 GRD
8. `timeliness` — CET / dh
9. `scheme_grade` — 方案精度等级

## Gate 使用原则

- 先由 KnowledgeRepository 取得指定版本的标准评定配置；
- 再由确定性 evaluator 生成 `GbtAccuracyReport`；
- Gate 只消费评定报告和项目 policy，不自行解释标准；
- `require_gbt_grade=true` 时，如果缺少标准评定报告，应 KEEP，而不是用某个写死的 NSE 阈值兜底 ACCEPT；
- 护栏失败仍可 ROLLBACK；
- 标准发布准入与本课题候选方案 ACCEPT 不是同一个概念。

## 版本状态

GB/T 22482—2026 在知识库中记录发布日、实施日和被替代版本。当前课题允许在正式实施前作为研究目标规范使用，但必须保留版本 provenance，不能把研究 Gate 结论表述为正式业务发布许可。
