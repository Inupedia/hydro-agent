# Hydro-Agent Agent Skills 与规则架构

> 当前实现把 Hydro-Agent 的可编辑水文专业方法收敛成六个 agentskills.io 风格 Package。XAJ、指标、优化器、Validator、Gate、Campaign 和 final-test 隔离仍属于确定性 Core。

## 1. 唯一 Skill 目录

仓库顶层 `skills/` 是内置 Skill 的源码 SSOT；构建 Wheel 时复制到 `hydro_agent/skills/data`。`.agents/skills/` 或 `HYDRO_AGENT_SKILLS_DIR` 是用户完整覆盖目录。`src/hydro_agent/skills/` 只保存 Registry、Loader、Snapshot、Binding、治理与审计代码，不再存放内置 Package。

```text
skills/
├── .bindings/
├── hydrology-data-review/
├── hydrologic-evidence-review/
├── xaj-calibration-diagnosis/
├── calibration-experiment-design/
├── calibration-result-review/
└── hydrology-reporting/
```

Workflow Binding 位于 `.bindings/*.json`，不写入便携的 `SKILL.md`。

## 2. 六个任务型 Skill

| Skill | 输入与职责 | 明确边界 |
| --- | --- | --- |
| `hydrology-data-review` | DataQualityEvidence、资料语义、DEM/ModelPlan；解释风险和补充检查 | 不执行清洗，不决定 Data Gate |
| `hydrologic-evidence-review` | 指标、过程线、季节、高低流量、洪水、退水；只描述现象 | 不直接解释 XAJ 参数 |
| `xaj-calibration-diagnosis` | 根据现象和按需 Reference 建立机制假设、支持/反证、参数组 | 不输出连续参数值或硬边界 |
| `calibration-experiment-design` | 假设、历史实验、预算、合法策略；形成受限实验计划 | 不运行优化器，不修改 Campaign lock |
| `calibration-result-review` | 候选、基线、多指标、Gate、预算；复盘假设与正式采纳 | 不覆盖 Gate，不释放 final-test |
| `hydrology-reporting` | Freeze 后组织开发与封存测试证据 | 不重算指标，不把候选冒充最终方案 |

原来分散在水量、产流、汇流、Campaign、建模和 GB/T 等 Package 中的资料已迁入这六个 Package 的 `references/` 或 `assets/`。XAJ 参数知识是诊断任务的 Reference，不再作为独立 Skill。

## 3. 运行链路

```text
Data/Model Evidence
  → hydrology-data-review
  → deterministic Data Gate / ModelPlan

HydrologicEvidence
  → hydrologic-evidence-review
  → EvidenceInterpretation
  → xaj-calibration-diagnosis
  → DiagnosisHypothesis
  → calibration-experiment-design
  → CalibrationPlan（参数组、策略、目标、预算，无参数向量）
  → DDS / SCE-UA / Morris + XAJ
  → deterministic metrics + Gate
  → calibration-result-review
  → Resolve / Freeze
  → sealed final-test
  → hydrology-reporting
```

当前 `AgentDecision` 和 `CalibrationPlan` 已保持“Agent 选实验，优化器搜参数”的边界。独立的 typed `EvidenceInterpretation`、`DiagnosisHypothesis`、`ExperimentReview` 仍是下一批实现，不能因为目录完成迁移就声称专业推理链已经验收。

## 4. Progressive Disclosure 与审计

Registry 启动时只读 Frontmatter；激活后才读取 `SKILL.md`。`xaj-calibration-diagnosis` 根据推荐参数组与 Resolve/边界证据选择水量、产流、汇流、参数关系或升级 Reference。其他 Package 目前按声明读取 Reference。

每个任务创建时冻结有效 Package、Binding、Reference 和 Asset 字节；每次调用记录 Skill、Snapshot、Binding、SKILL.md、Reference 哈希以及输入 Evidence ID。修改当前 Skill 不会改变已冻结任务。

## 5. 权威边界

Skill 可以解释证据、提出可证伪假设、选择合法参数组和已注册策略、组织结果。以下内容只能来自确定性 Core：

- XAJ 正演与状态；
- NSE/KGE/PBIAS、事件和 GB/T 指标；
- 参数范围、联合约束与只读项；
- DDS/SCE-UA/Morris 的连续数值搜索；
- ACCEPT/KEEP/ROLLBACK 与方案采纳；
- Campaign 预算、停止原因和 final-test 隔离。

## 6. Builtin、Override 与 Binding

Builtin Package 只读。复制为 User Override 后，用户保存的是完整 Package，不做 Markdown 行级合并。Resolver 优先采用同名用户 Package。保存内容不会自动激活；只有外部 Binding 匹配当前 stage/model 后才进入 Prompt。

现有历史用户目录若仍使用旧的十二个 ID，不会作为新六个内置 Skill 的别名自动混入；需要显式迁移内容和 Binding，避免两个分类体系同时生效。

## 7. 当前完成边界

已经实现：顶层六 Package、metadata-only discovery、lazy load、按证据读取部分 Reference、外部 Binding、Builtin/User 覆盖、任务 Snapshot、调用审计、本地 Package/领域校验、`skills-ref` 0.1.1 官方校验及 CI Gate、确定性 Core 边界。

仍需完成：用户 Revision/Pin/Usage/Test 界面、三类专业 typed 输出、所有 Package 的按证据 Reference Policy、历史用户 Skill 迁移工具，以及瑶沟/Leaf River 同预算 old-agent 与 skills-agent 的真实 A/B 运行。
