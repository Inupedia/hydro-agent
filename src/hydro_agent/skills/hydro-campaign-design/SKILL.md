---
name: hydro-campaign-design
description: 在研究任务开始前设计可复现的率定 Campaign，包括数据分区、主目标、预算、停止策略和 final-test 隔离。
metadata:
  title_zh: "水文率定 Campaign 设计"
  purpose_zh: "把一次率定任务预注册成可比较、可复现、不会边跑边改规则的研究协议。"
  when_to_use_zh: "创建新 Campaign|变更研究目标需开启新 Campaign|设计 O/P/A 对照实验"
  required_evidence_zh: "可用历史时段|研究目标|模型与数据版本|计算预算|评价需求"
  recommended_actions: "M01_CHECK_MATERIALS|A02_VALIDATE_SCHEME"
  activation_stages: "data"
  counterexamples_zh: "运行中不能用 Skill 改 locked objective|不能把已暴露数据改成 final-test"
  prompt_references: "references/period-splitting.md|references/objective-locking.md|references/convergence-policy.md"
---

# 水文率定 Campaign 设计

Campaign 是整个研究运行的**预注册实验协议**，与单轮参数实验不同。

创建时应固定：

- calibration / development / final-test 的角色和时间边界；
- campaign objective 与指标语义；
- 模型、adapter、数据 snapshot、随机种子与预算；
- ConvergencePolicy、重启/plateau 规则和最大安全预算；
- 哪些 Skill prior 允许使用、哪些数据来源必须禁止。

一旦 Campaign 开始，上述 locked 字段不能由 Skill 或 LLM 临时修改。需要改变研究目标时应创建新的 Campaign，而不是修改正在运行的实验协议。
