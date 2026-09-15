# Hydro-Agent Agent Skills 与规则架构

> 当前版本目标：把 Hydro-Agent 的“可编辑水文经验”和“不可被文本覆盖的确定性规则”彻底分开。Agent Skills 是领域能力层，不是第二套 Protocol，也不是参数配置文件。

## 1. 权威分层

```text
                       Hydro-Agent
                           │
                  Observe / Decide / Act
                           │
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
  Agent Skills          Protocol            Standards
 可编辑软知识           实验协议              规范/政策
       │                   │                   │
       ▼                   ▼                   ▼
诊断/假设/实验建议   数据窗口/预算/锁定目标   GB/T 配置/Gate Policy
       │                   │                   │
       └──────────────┬────┴──────────────┬────┘
                      ▼                   ▼
               ExperimentPlan       Deterministic Gate
                      │
                      ▼
              Model Validator / Kernel
              硬边界 / 联合约束 / 只读项
                      │
                      ▼
                 Numerical Optimizer
                      │
                      ▼
              Independent Development Gate
                      │
                 ADOPT / KEEP / ROLLBACK
                      │
                      ▼
             Campaign / ConvergencePolicy
                      │
                 stop_reason 出现后
                      ▼
             Freeze → Final Test → Report
```

### Skill 可以做

- 解释水文误差模式；
- 提出可证伪假设；
- 建议应测试的物理过程和参数组；
- 从已注册 strategy 中建议实验路径；
- 提供带 provenance、scope、review/verification 状态的专家 prior；
- 说明标准 evaluator 的调用时机与结果语义。

### Skill 不能做

- 定义或覆盖 XAJ 参数硬边界；
- 定义 KG/KI 等跨参数执行约束；
- 修改已锁定的 Campaign objective；
- 修改 calibration/development/final-test 分区；
- 用 NSE/KGE/PBIAS 单阈值宣布 Campaign 收敛；
- 在 SKILL.md 中保存可执行 GB/T 甲乙丙阈值；
- 绕过 A08/A09 直接采用候选。

## 2. 当前 Skill 体系

```text
skills/
├── hydro-data-readiness/
│   ├── SKILL.md
│   ├── references/
│   │   ├── data-semantics.md
│   │   └── leakage-checks.md
│   └── assets/expert/
│
├── hydro-error-diagnosis/
│   ├── SKILL.md
│   └── references/
│       ├── metric-patterns.md
│       └── diagnosis-routing.md
│
├── xaj-water-balance/
│   ├── SKILL.md
│   ├── references/
│   │   ├── water-balance.md
│   │   └── evap-runoff-semantics.md
│   └── assets/
│       ├── expert/
│       └── governed/
│
├── xaj-runoff-generation/
│   ├── SKILL.md
│   └── references/
│       ├── runoff-generation.md
│       └── source-partition.md
│
├── xaj-routing-diagnosis/
│   ├── SKILL.md
│   ├── references/
│   │   ├── routing.md
│   │   └── recession-and-lag.md
│   └── assets/governed/
│
├── hydro-campaign-design/
│   ├── SKILL.md
│   └── references/
│       ├── period-splitting.md
│       ├── objective-locking.md
│       └── convergence-policy.md
│
├── hydro-experiment-design/
│   ├── SKILL.md
│   ├── references/
│   │   ├── experiment-strategies.md
│   │   ├── hypothesis-testing.md
│   │   └── budget-allocation.md
│   └── assets/
│       ├── parameter-groups.json
│       └── governed/
│
├── xaj-calibration/
│   ├── SKILL.md
│   ├── references/
│   │   ├── workflow.md
│   │   ├── parameter-semantics.md
│   │   ├── parameter-relations.md
│   │   └── escalation.md
│   └── assets/
│       ├── governed/
│       └── review/
│
└── gbt-22482-accuracy/
    ├── SKILL.md
    └── references/
        └── evaluation-workflow.md
```

旧 `data-check`、`forecast-diagnose` 和以 `xaj-calibration` 为万能知识容器的结构已经删除。

## 3. 为什么把 Campaign 和 Experiment 分开

二者回答的是不同问题：

```text
Campaign
“整个研究怎么保证公平、可复现、不会泄漏？”
    ├── 数据分区
    ├── objective lock
    ├── model/data version
    ├── total budget
    ├── convergence policy
    └── final-test isolation

Experiment
“这一轮具体要验证哪个假设？”
    ├── hypothesis
    ├── parameter groups
    ├── registered strategy
    ├── trial budget
    ├── expected evidence
    └── falsification condition
```

因此 `hydro-campaign-design` 主要服务任务创建/研究设计，不在每轮 Agent Decide 中自动注入；`hydro-experiment-design` 则在 A06 之后进入单轮试验设计。

## 4. 为什么拆 XAJ 三类专业诊断

`xaj-calibration` 现在只做总编排。真正的过程知识分为：

- `xaj-water-balance`：长期水量、蒸散发、径流总量；
- `xaj-runoff-generation`：产流形成、响应强弱、水源划分；
- `xaj-routing-diagnosis`：峰现、过程形状、滞后、退水。

这样用户在前端修改一个 routing 经验时，不会覆盖整个率定方法，也不会意外改变 water-balance prior。

## 5. 运行时 Progressive Disclosure

```text
还没有基线预报
    → hydro-data-readiness

已有预报、尚未诊断
    → hydro-error-diagnosis

已有诊断
    → hydro-error-diagnosis
    → 根据 hypothesis / recommended_param_groups 激活：
        evap        → xaj-water-balance
        runoff      → xaj-water-balance + xaj-runoff-generation
        routing     → xaj-routing-diagnosis
        MODEL/UNKNOWN 且未定位 → 三类专业诊断并行提供候选假设

允许优化且进入率定循环
    → xaj-calibration
    → hydro-experiment-design

候选进入 Gate / 最终评价
    → gbt-22482-accuracy
```

这里没有 “NSE < 某值才继续 / NSE > 某值就 Freeze” 的 Skill 逻辑。停止只来自 `Campaign.stop_reason`。

## 6. Soft Knowledge 的治理

可执行 expert prior 通过 `skills/expert.py` 从当前激活的专业 Skill 资产聚合；claim-level 来源事实通过 `skills/catalog.py` 聚合。

所有 claim 在进入 planning 前仍经过统一治理过滤：

- authority；
- review status；
- verification status；
- model/kernel/adapter/basin/timestep scope；
- exposure tag；
- evidence dataset leakage。

用户可编辑不等于拥有运行权。

## 7. 参数知识的最终边界

`parameter-groups.json` 只描述 Agent-facing 的概念组：`evap / runoff / routing`，不保存数值范围。

```text
Skill
“这轮值得测试 routing 组”
        ↓
ExperimentPlan
        ↓
Model Registry / Validator
“routing 组当前实际包含哪些可调参数、合法范围是什么”
        ↓
Optimizer
“在合法空间中找具体值”
```

任何来自论文、专家材料或历史 Skill 的范围，如果尚未被当前实现验证，只能作为 governed evidence 保存，不能提升为硬约束。

## 8. Standards 的边界

`gbt-22482-accuracy` 不再保存规范阈值，也不引用旧 `hydro_agent.knowledge`。

确定性链路为：

```text
standards/StandardRepository
        ↓
GbtAccuracyConfig
        ↓
deterministic evaluator
        ↓
GbtAccuracyReport + provenance
        ↓
research Gate policy
```

Skill 只负责解释什么时候调用和怎样理解。

## 9. 前端管理含义

前端“Skills”管理的是完整 Skill package：

- `SKILL.md`；
- `references/*.md`；
- 允许编辑的 `assets/*.json`；
- user override 覆盖 built-in package。

因此更新专家经验不需要修改 Python 源码。与此同时，Protocol、Standard、Validator 不进入同一个可编辑入口，防止把软知识编辑器变成系统规则后台。

## 10. 最终原则

> **数据给事实，模型给计算，Skill 给专业方法和假设，ExperimentPlan 给本轮实验，Protocol/Validator/Standard 给边界，Gate 给独立判断，Campaign 决定什么时候真正结束。**
