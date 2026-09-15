# Hydro-Agent 最终知识、规则与 Agent Skills 架构

## 1. 核心结论

Hydro-Agent 不再设置一个可以同时装“标准、专家经验、硬约束、案例、流域属性”的通用 Knowledge Platform。不同信息拥有不同权威等级，必须由不同模块负责。

```text
可编辑经验/方法/claims              不可由 Skill 改写的确定性权威
┌──────────────────────┐          ┌──────────────────────────────┐
│ Agent Skills          │          │ Standards / Protocol /       │
│ SKILL.md              │          │ Model Validator / Gate       │
│ references/           │          │                              │
│ assets/expert/        │          │ 标准阈值、窗口、预算、硬边界 │
│ assets/governed/      │          │ final-test 隔离、准入规则    │
└──────────┬───────────┘          └──────────────┬───────────────┘
           │                                     │
           └──────────────┬──────────────────────┘
                          ▼
                  Hydro-Agent 决策层
                          │
           A06 Diagnosis → ExperimentPlan
                          │
                          ▼
                    Numerical Optimizer
                          │
                          ▼
                    Independent Gate
                          │
                          ▼
              Trial Ledger / Campaign State
                          │
                          ▼
                 Freeze → Final Test → Report
```

原则：**Skill 可以影响“下一步试什么”，不能拥有“什么是合法、什么算达标、能不能看 final-test”的最终权限。**

## 2. 权威分层

| 层 | 代码位置 | 是否可运行时编辑 | 权威 | 负责内容 |
|---|---|---:|---|---|
| Agent Skills | `hydro_agent.skills` / `.agents/skills` | 是 | advisory | 诊断方法、专家先验、实验设计、scope-bound claims |
| Standards | `hydro_agent.standards` | 否 | normative | GB/T 配置、标准条款、项目 Gate policy |
| Protocol / Campaign | experiment/runtime contracts | 否，任务创建后锁定 | protocol | warmup/calibration/development/final-test、主目标、预算、seed、停止规则 |
| Model Validator / Kernel | model runtime | 否 | executable hard constraint | 参数绝对边界、联合约束、模型能力 |
| Gate / Evaluator | evaluation | 否 | deterministic decision | adoption、qualification、guardrails |
| Research Memory | `hydro_agent.research` | 追加事实 | provenance only | Trial/Calibration case、历史结果、lesson |
| Hydrology | `hydro_agent.hydrology` | 否 | deterministic derived fact | 从合法数据推导流域属性 |

## 3. Agent Skill 的完整结构

```text
src/hydro_agent/skills/
├── data-check/
├── forecast-diagnose/
├── gbt-22482-accuracy/
└── xaj-calibration/
    ├── SKILL.md
    ├── references/
    └── assets/
        ├── expert/      # 可执行但 advisory-only 的专家先验
        ├── governed/    # 原子 claim + scope/provenance/governance
        └── review/      # claim 审核记录

.agents/skills/          # 用户可写 overlay
└── xaj-calibration/     # 同名即覆盖内置 Skill，copy-on-write
```

Skill 是一个整体版本单元：`SKILL.md + references + assets` 一起覆盖。用户更新专家阈值或 claim 后，下一次 Agent 决策读取当前激活 Skill；不需要改 Python 源码。

`scripts/` 暂时只读，管理 API 禁止上传可执行脚本，避免知识管理接口演化成远程代码执行接口。

## 4. 标准为什么必须独立

标准和专家经验不是同一类东西。GB/T 的 DC/QR、许可误差、方案等级属于版本化确定性配置，应由：

```text
StandardRepository
      ↓
GbtAccuracyConfig
      ↓
Deterministic Evaluator
      ↓
GbtAccuracyReport
      ↓
Gate policy
```

Skill 可以解释何时调用标准、如何理解结果，但不能通过修改 `SKILL.md` 或 `assets/` 改变标准阈值。

## 5. 率定运行时

正式率定链路固定为：

```text
A05 Forecast
   ↓
A06 Diagnosis（只看允许暴露的数据）
   ↓
Skill selection / governed claims / expert priors
   ↓
ExperimentPlan：假设、参数组、搜索策略、预算请求
   ↓
Protocol + Model Validator 二次约束
   ↓
DDS / SCE-UA / Morris 等确定性数值计算
   ↓
A08 Independent Gate
   ↓
A09 Resolve → Trial Ledger
   ↓
Campaign rebuild / stop decision
   ↓
A10 Freeze
   ↓
A11 Final replay
   ↓
A12 Final evaluation + report
```

其中 final-test 在 Freeze 前不可访问，Skill、LLM、案例记忆都不能绕过这一点。

## 6. Skill claim 治理

软知识不是“加载了就相信”。claim 进入 ExperimentPlan 前必须检查：authority、review status、verification status、model/kernel/adapter、basin、execution representation、timestep、evaporation semantics、exposure tags、evidence dataset provenance。

如果没有兼容 claim，返回空集合并使用注册基线；禁止为了填上下文而自动放宽 scope 或 final-test 防泄漏规则。

## 7. Research Memory 的定位

`CalibrationCaseMemory` 只保存结构化历史事实和结论，不保存隐藏推理过程，也不自动升级成规则。案例要成为可执行 expert prior，必须经过明确的 review/verification，再进入 Skill assets。

## 8. 后端管理边界

当前 API 管理的是 Agent Skill，不是系统全部规则：

```text
GET    /api/skills
GET    /api/skills/{skill_id}
PUT    /api/skills/{skill_id}
DELETE /api/skills/{skill_id}/override
POST   /api/skills/reload
GET    /api/skills/{skill_id}/resources
GET    /api/skills/{skill_id}/resources/{path}
PUT    /api/skills/{skill_id}/resources/{path}
```

允许写：`SKILL.md`、`references/*`、`assets/*`。
不允许写：`standards/*`、Protocol、Validator、Gate、`scripts/*`。

## 9. 最终目录责任

```text
hydro_agent/
├── agent/          # Observe → Decide → Act 编排
├── skills/         # 可编辑软知识与 Agent Skills
├── standards/      # 版本化规范与 Gate policy
├── hydrology/      # 确定性水文派生事实
├── research/       # Trial/Case 历史研究事实
├── optimization/   # ExperimentPlan + 数值优化
├── evaluation/     # 独立评价与 Gate
├── models/         # XAJ 等模型、adapter、validator
├── data/           # Snapshot 与时间/质量/lineage
├── replay/         # Freeze 后回放
└── reporting/      # 结果与报告
```

旧的 `hydro_agent.knowledge` 全部删除，不提供兼容别名。代码路径本身表达权威边界，避免未来再次把专家文本、技术标准和硬约束混在一个“知识库”里。
