# Hydro-Agent Experience Skill Evolution 设计规格

**日期：** 2026-09-18  
**状态：** 已确认，可进入实施  
**目标：** 让 Hydro-Agent 通过真实率定实验持续积累可验证经验，并让这些经验反过来改变后续实验组织方式，实现“智能体越用越顺手”。

## 1. 问题定义

当前 Hydro-Agent 已具备任务状态、实验历史、Evidence、AgentDecision、Skills、Skill Snapshot、Replay 等基础能力，但“历史率定经验”主要停留在一次任务内部。相同类型任务再次执行时，Agent 缺少一个跨任务、可验证、可版本化、可回放的经验演进层。

本设计不实现用户画像，也不学习用户偏好。系统只有一个共享的 Agent 经验空间。

“越用越顺手”定义为：

- Agent 会复用过去验证过的率定经验；
- Agent 会记住过去反复失败的实验方向，降低重复无效实验的优先级；
- Agent 仍保留受约束的 Exploration，避免陷入局部经验；
- Experience 状态会持续优化，但只有决策结构发生实质变化时 Experience Skill 才升级版本；
- Experience Skill 的版本变化必须能解释后续 Agent 行为为什么不同；
- 同一数据、模型、配置和 Experience Skill Version 下，核心决策应尽量可复现。

## 2. 非目标

本阶段明确不做：

- 用户偏好或个性化 Memory；
- 聊天记录总结；
- “为了显得智能”而引入随机行为；
- Experience 直接写最终模型参数；
- Experience 绕过参数边界、Validation Gate、阶段权限或 final-test leakage 防护；
- 每个任务都机械生成一个新的 Skill 版本。

## 3. 核心架构

~~~
Calibration Task
      |
      v
Agent Diagnosis
      |
      v
Experience Retrieval
      |
      v
Experience Skill vN
      |
      +------ Exploitation
      |
      +------ Exploration
      |
      v
Experiment Design
      |
      v
Execution + Result Review
      |
      v
Experience Reflection
      |
      v
Experience Diff
  KEEP / REINFORCE / WEAKEN
  CREATE / MERGE / SPLIT / SUPERSEDE / REJECT
      |
      v
Experience State
      |
      +-- 无结构变化 --> Skill 仍为 vN
      |
      +-- 实质变化 --> compile candidate vN+1
                            |
                            v
                     Regression Replay
                      /            \
                  Reject          Promote
                                    |
                                    v
                           Experience Skill vN+1
~~~

## 4. 两层模型：Experience State 与 Experience Skill

### 4.1 Experience State

Experience State 是持续变化的事实层，用于保存：

- 适用模型、流域和执行语义；
- 问题模式；
- 建议优先级与 avoid-first 信息；
- supporting / contradicting Evidence；
- success_count / failure_count；
- confidence；
- 当前状态；
- 来源 Task / Experiment / Evidence。

例如：

~~~yaml
experience_id: EXP-XAJ-0018
revision: 4
scope:
  model_ids: [xaj]
  basin_ids: [basin-a]
pattern:
  peak_bias: negative
  timing_error: small
decision:
  prefer_param_groups: [routing]
  avoid_first: [soil-moisture-capacity]
evidence:
  supporting: 8
  contradicting: 2
confidence: 0.81
status: active
~~~

supporting 从 8 变 9、confidence 从 0.81 变 0.82 都属于 State Optimization，不自动触发 Skill 新版本。

### 4.2 Experience Skill

Experience Skill 是 Agent 真正加载并用于决策的“稳定经验规则集合”。

只有以下结构变化才允许生成 Candidate Version：

- CREATE：出现新的决策规律；
- MERGE：多个经验合并；
- SPLIT：一个过宽规律拆成多个适用条件；
- SUPERSEDE：旧规律被新证据推翻；
- SCOPE CHANGE：适用范围实质改变；
- DECISION PRIORITY CHANGE：优先级发生足以改变 Agent 行为的变化。

## 5. Experience 层级

Experience 是共享 Agent 资产，按以下层级组织：

1. General Calibration Experience
2. Model Experience
3. Basin Experience

检索优先级：

~~~
同流域 + 同模型
    >
同模型、其他可迁移流域
    >
Model Global Experience
    >
General Calibration Experience
~~~

特定流域经验可以作为其他流域的弱先验，但不能无条件迁移。

## 6. Positive 与 Negative Experience

必须同时学习：

- what worked；
- what did not work。

例如一次实验 SM +15% 导致 Peak Error 恶化，这不是“无经验”，而是可以形成“在相似条件下不要优先通过扩大 SM 解决该问题”的 Negative Experience。

Inconclusive Evidence 可以保存，但不能轻易升级为 Active Rule。

## 7. Experience Reflection 与 Diff

每个完整 Calibration Task 结束后运行 Experience Reflection。

Reflection 输入至少包含：

- 当前 Active Experience；
- 初始诊断；
- AgentDecision；
- Hypothesis；
- 全部实验；
- 参数变化；
- 指标变化；
- Result Review；
- Gate Result；
- 最终接受、回退或失败情况。

Reflection 不允许“自由重写经验库”，输出必须是结构化 Diff：

- KEEP
- REINFORCE
- WEAKEN
- CREATE
- MERGE
- SPLIT
- SUPERSEDE
- REJECT

例如：

~~~yaml
operation: REINFORCE
experience_id: EXP-XAJ-0018
evidence_refs:
  - task-32:experiment-7
reason: Similar peak-underestimation case again improved after routing adjustment.
~~~

## 8. Convergence

Experience 状态：

- learning
- converging
- converged
- reopened

最近一段窗口主要发生 KEEP / REINFORCE / WEAKEN 时，说明知识结构趋于稳定；频繁 CREATE / SPLIT / MERGE / SUPERSEDE 时仍处于 learning。

Converged 不等于 Frozen。出现强反例时必须能 reopened。

## 9. Experience Skill 遵循 Agent Skills 规范

Experience Skill 必须遵循 https://agentskills.io/ 的公开规范：

~~~
calibration-experience/
├── SKILL.md
├── references/
│   ├── general.md
│   ├── xaj.md
│   ├── gr4j.md
│   ├── hbv.md
│   ├── sac-sma.md
│   ├── tank.md
│   └── basin-experience.md
└── assets/
    └── experience-schema.json
~~~

要求：

- SKILL.md 使用合法 YAML frontmatter；
- name 与目录名一致；
- description 同时说明“做什么”和“什么时候使用”；
- metadata 只放字符串值；
- 详细经验进入 references/，利用 progressive disclosure；
- SKILL.md 保持精炼，不把整个经验数据库塞入正文；
- 编译后使用现有 Skill loader / validator 验证。

Experience Skill 由 Agent 管理，应新增 source = agent，不复用 user overlay 的语义。

## 10. Skill Version 与冻结

每个 Experience Skill Version 保存：

- version；
- parent_version；
- created_at；
- structural change reason；
- added / modified / merged / split / superseded；
- source_experience_ids；
- skill_hash；
- regression_result；
- promotion_status。

状态至少包括：

- candidate
- promoted
- rejected
- superseded

Task 启动时冻结 Experience Skill Snapshot。一个 Task 从开始到结束必须使用同一 Experience Skill Version 和 hash。

Replay 必须可以加载历史 Experience Skill Version。

## 11. Experience Skill Compiler

正式 Skill 不由 LLM 任意直接写文件。

ExperienceSkillCompiler 输入 Active Experience Entries，输出标准 Agent Skill Package：

- SKILL.md：工作方式与约束；
- references/general.md；
- references/<model>.md；
- references/basin-experience.md；
- assets/experience-schema.json。

结构化 Experience Store 是事实源，Skill 是其可执行视图。

## 12. Exploitation 与 Exploration

Agent 决策同时支持：

- Exploitation：利用高置信经验；
- Exploration：尝试具有水文合理性但经验不足的新方案。

Exploration 不能是纯随机。

候选优先级至少考虑：

~~~
Experience Score
+ Hydrologic Plausibility
+ Uncertainty Bonus
+ Novelty Bonus
- Historical Failure Penalty
~~~

探索率动态取决于 Experience Confidence、Task Novelty、Basin Familiarity、Contradiction Level、Diagnosis Uncertainty。

即使 converged，也保留非零 Exploration。

## 13. Experience 如何影响 Agent

Experience 可以影响：

- Hypothesis Ranking；
- Parameter Group Priority；
- Strategy Ranking；
- Experiment Priority；
- Avoid / Penalize Decisions；
- Exploration Candidate Selection。

Experience 永远只是 advisory decision knowledge，不得直接成为执行权限。

## 14. 与现有模块集成

### Knowledge Governance

复用现有 KnowledgeEntry / applicability / verification / conflicts / supersedes 思想。Experience 作为新的 agent_experience 来源或 calibration_experience category，但 authority 继续保持 advisory_only。

### WorldState

HydroContext 增加 experience_context，至少包括：

- experience_skill_version；
- experience_skill_hash；
- experience_status；
- applicable_experiences；
- confidence_summary；
- exploration_level。

只加载与当前 model / basin / diagnosis 匹配的经验，不把全部 Store 塞入 Prompt。

### SkillOrchestrator

Experience Skill 不替代模型诊断 Skill，而是作为诊断与实验设计之间的经验先验：

~~~
Evidence Review
-> Model Diagnosis
-> Experience Retrieval
-> Experience Influence
-> Experiment Design
-> Execution
-> Result Review
~~~

### AgentDecision 审计

决策至少记录：

- experience_skill_version；
- experience_skill_hash；
- activated_experience_ids；
- experience_refs；
- experience_influence；
- decision_mode = exploitation | exploration。

## 15. Regression 与 Promotion

结构变化产生 vN+1 candidate 后，必须经过 Experience Regression Set。

Regression Set 是代表性历史任务集合，而不是每次全量 Replay。至少覆盖：

- peak underestimated / overestimated；
- timing early / late；
- volume bias；
- low-flow / high-flow；
- 不同流域；
- historical hard cases；
- 过去 Experience 导致错误的任务。

Candidate 只有满足自动 Gate 才能 Promote：

- 不增加明显重复无效实验；
- 不系统性降低最终率定质量；
- 不违反模型约束和 Validation Gate；
- 关键 Hard Case 不退化；
- 结果可追溯。

## 16. Agent Evolution Observatory

前端新增“智能体进化 / Agent Evolution Observatory”。

必须展示：

- Current Experience Skill Version；
- learning / converging / converged / reopened；
- Active Experience 数；
- High-confidence Experience 数；
- Evolution Timeline；
- Version Diff；
- Experience Detail；
- Evidence Provenance；
- Experience Influence；
- Exploitation / Exploration；
- Agent Decision 实际使用的 Experience Skill 与 Experience IDs。

不做人工 CRUD 为主的“记忆管理”。

## 17. 可追溯性

必须可以回答：

1. 这条经验从哪些 Task / Experiment 来？
2. 为什么 v6 升级到 v7？
3. v7 与 v6 的规则差异是什么？
4. 当前 Agent 为什么优先 routing？
5. 为什么本轮是 exploration？
6. 为什么同一类型任务今天和历史运行路径不同？

最后一个问题必须能追溯到 Experience Skill Version 差异，而不是“随机”。

## 18. 验收场景

### 场景 A：只优化状态、不升级版本

~~~
Task A
-> Experience Reflection
-> REINFORCE
-> supporting 8 -> 9
-> confidence 0.81 -> 0.83
-> Experience Skill 仍为 v3
~~~

### 场景 B：结构变化并升级

~~~
Task B
-> 新反例
-> SPLIT existing experience
-> compile v4 candidate
-> regression pass
-> promote v4
~~~

### 场景 C：新版经验改变后续决策

~~~
Task C
-> load Experience Skill v4
-> matching Experience enters ranking
-> routing priority changes
-> AgentDecision records experience refs
-> UI displays reason and evidence
~~~

只有完成 A + B + C，才算真正实现“智能体越用越顺手”。
