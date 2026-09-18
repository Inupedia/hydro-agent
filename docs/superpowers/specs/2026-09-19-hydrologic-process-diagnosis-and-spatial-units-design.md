# Hydro-Agent 水文过程诊断、次洪评价与空间异质性改造设计

**日期：** 2026-09-19  
**状态：** 设计规格，仅规划，不在本 PR 中修改源码  
**背景：** 基于导师对 Hydro-Agent 当前率定与方案构建能力提出的四点优化意见，结合当前 `main` 代码、经典水文模型率定文献与现行/即将实施的水文预报规范形成。

---

## 1. 目标

本设计不推翻 Hydro-Agent 已有的“智能体提出实验假设、确定性工具执行、独立验证后再采用”的架构，而是在现有基础上完成三项升级：

1. 将率定判断从“单一标量目标驱动”升级为“水文过程证据驱动”；
2. 将连续过程评价进一步拆到次洪尺度，使 Agent 能识别洪峰、峰现、洪量、涨退水等误差模式；
3. 将“方案构建”从固定面积/数量划分计算单元，升级为参考流域气象、地形、下垫面空间异质性的方案推荐。

最终要形成的核心链路是：

```text
流域/方案资料
  ↓
连续模拟
  ↓
确定性水文证据提取
  ├─ 总体指标
  ├─ 高/中/低流
  ├─ FDC
  ├─ 季节/年份
  └─ 次洪事件
        ↓
LLM / Skill 做水文诊断
  ↓
形成可证伪假设
  ↓
选择过程层 + 参数组 + 调整方向
  ↓
Morris / 局部扰动验证方向
  ↓
DDS / SCE-UA 做数值精调
  ↓
保留多个行为候选
  ↓
多指标 × 多次洪 × 独立时段比较
  ↓
Adopt / Keep / Rollback
  ↓
经验沉淀
```

空间方案构建走并行链路：

```text
DEM / 河网 / 降雨空间分布 / 土地利用 / 土壤
  ↓
Spatial Heterogeneity Analyzer
  ↓
生成若干确定性计算单元候选
  ↓
Agent 比较方案复杂度与水文解释
  ↓
推荐 lumped / sub-basin / heterogeneity-aware 方案
  ↓
仍由确定性 GIS / 建模工具真正生成单元
```

---

## 2. 导师意见的技术解释

### 2.1 不应只靠 NSE 等单一精度指标决定如何优化

导师原意可理解为：DDS / SCE-UA 作为数值搜索器并没有错，但如果搜索与候选选择都只围绕 NSE 之类的单一标量，容易出现“异参同效”——多套不同参数均可得到相近综合分数，却对应不同的洪峰、洪量、退水或低流误差。

当前代码中这一问题仍然存在：

- `src/hydro_agent/models/shared_calibrate_runtime.py` 的 `_objective_score()` 每次优化仍返回一个标量；
- `nse` 使用 NSE；
- `peak` 使用单一洪峰得分；
- `composite` 当前实际上是 KGE 的兼容别名，并不是真正的多维综合判别；
- `DDS`、`SCE-UA` 的输出仍以 `best_score` / `best_parameters` 为核心。

本设计不要求立即引入多目标优化算法。原因是 Hydro-Agent 的研究价值不应变成“再实现一种多目标优化器”，而应体现在：

> Agent 负责诊断“哪里错了、为什么错、下一轮应该验证什么”；DDS/SCE-UA 负责在 Agent 缩小后的参数空间内高效搜索。

因此搜索阶段允许使用明确标量目标，但候选采用阶段不得退化为只比较一个目标函数值。

### 2.2 过程线识别应成为 LLM 判断的重要证据

当前项目已经具备较强的确定性证据底座：

- `evaluation/evidence.py`：overall、flow regimes、season、year、FDC、flood events；
- `evaluation/hydrograph.py`：观测/基线/候选过程线及 residual；
- `services/continuous_simulation.py`：NSE、KGE、PBIAS、MAE、RMSE、高流 MAE、peak ratio、peak timing；
- `agent/hydrologic_evidence.py`：Agent 面向的稳定证据契约；
- `optimization/calibration_scientist.py`：Evidence → Hypothesis → Plan。

缺口不是“完全没有过程证据”，而是丰富证据进入 Agent 时被压缩得过度。特别是 `HydrologicEvidence.from_diagnosis()` 目前主要保留总体指标和一个诊断峰值，未完整携带：

- 多场洪水；
- FDC；
- 高/中/低流；
- 涨水段与退水段特征；
- 降雨到流量的响应滞时；
- 跨事件/跨年份误差一致性。

因此本设计要求新增 Agent-facing 的结构化过程诊断包，而不是把 ECharts/PNG 截图直接作为科研判断的唯一输入。

### 2.3 流域空间异质性应影响计算单元划分

当前 `modeling/plans.py` 已有：

- `model_mode = lumped | distributed`；
- `resolution_m`；
- `stream_area_km2`；
- `unit_area_km2`；
- `unit_count`；
- `M02_DELINEATE` “提取流域与计算单元”。

但目前计算单元仍主要由 DEM、河网和面积/数量参数驱动，尚未把气象、地形、土地利用、土壤等空间差异形成可审计的“异质性证据”。

本设计将“Agent 推荐计算单元方案”和“GIS 真正生成计算单元”严格分离：

- Agent 只能选择/解释候选方案；
- GIS、DEM、河网、聚类/分区算法负责真正划分；
- 不允许 LLM 直接输出任意 polygon 作为模型计算单元。

### 2.4 次洪评价不应被单一规范 Gate 绑死

当前项目有 `evaluation/gbt22482.py` 和 `optimization/gate.py`，且 `GatePolicy.require_gbt_grade=True` 默认将标准等级参与 qualification。

导师“可以用次洪，不一定要用水文情报预报规范去限制”的意见更适合解释为：

- GB/T 评价仍保留；
- 但科研率定是否继续、是否采用候选，不应完全由某一版标准等级主导；
- Agent 应优先观察不同次洪和过程特征是否一致改善；
- 标准评价作为业务合规/最终报告的一条独立证据链。

截至 2026-09-19，GB/T 22482-2026 已于 2026-07-30 发布，将于 2027-02-01 实施。设计上更应避免把 Agent 核心推理与某一版标准硬编码绑定。

---

## 3. 科学原则

### 3.1 优化器与诊断器职责分离

```text
LLM / Skill:
  观察
  诊断
  提假设
  选择参数组
  选择实验策略
  解释结果

Morris / 局部扰动:
  验证参数影响方向
  识别敏感参数

DDS / SCE-UA:
  搜索具体连续参数值

Evaluator / Gate:
  判断候选是否改善、是否退化、是否可采用
```

LLM 不直接生成并强制执行 XAJ 连续参数值。

### 3.2 过程证据必须先由确定性程序计算

“LLM 看过程线”在科研链路中的含义是：

1. 程序从真实 obs/sim/forcing 中提取过程特征；
2. 每个特征保留数据窗口、样本数、事件 ID、单位和质量状态；
3. LLM 读取结构化证据并做解释；
4. 图像可用于 UI 展示和辅助复核，但不能成为唯一证据来源。

### 3.3 任何诊断都必须可证伪

一个合法诊断不能只是：

> 洪峰不太好，建议调 routing。

而应至少包含：

```text
phenomenon
process_layer
confidence
supporting_evidence_ids
contradictory_evidence_ids
parameter_groups
direction
falsification_conditions
```

例：

```text
phenomenon:
  多场洪水洪量基本正确，但峰现普遍偏晚、上涨段过缓

process_layer:
  routing

parameter_groups:
  routing

direction:
  accelerate_response

falsification:
  若 routing 参数局部扰动不能改善峰现且保持洪量，
  则当前 routing 假设不成立，应重新诊断
```

### 3.4 不能用一个人工加权分数重新隐藏多目标问题

本期不把：

```text
0.4*NSE + 0.2*KGE + 0.2*peak + ...
```

当作解决异参同效的核心方案。

允许优化器使用一个明确目标，但候选选择必须保留多维证据，并至少区分：

- overall skill；
- water balance；
- high-flow；
- event peak；
- event timing；
- event volume；
- recession / rising-limb；
- independent development performance。

### 3.5 final-test 继续保持不可回流

现有 calibration / development / final-test 隔离原则保持不变。

次洪只是评价粒度的改变，不得把 final-test 中识别出的洪水误差回流给当前 campaign 继续调参。

---

## 4. P0：次洪与过程诊断

### 4.1 次洪事件定义

新增独立事件分割器，替代“仅用 Q90 连续超阈值即为事件”的最终科研逻辑。

V1 仍要求确定性、可重复，不追求复杂自动水文分割。事件至少结合：

- 降雨开始/结束；
- 流量起涨；
- 洪峰；
- 退水；
- 最小事件间隔；
- 多峰洪水合并规则。

每个事件输出：

```text
event_id
start
end
rain_start
rain_end
rise_start
peak_time_obs
peak_time_sim
recession_end
antecedent_precip
event_precip
obs_peak
sim_peak
peak_relative_error
timing_lag
obs_volume
sim_volume
volume_relative_error
rising_limb_error
recession_error
duration_error
response_lag
quality_status
```

如果降雨数据不足，允许退化成 flow-only event，但必须显式标记 `event_basis=flow_only`。

### 4.2 HydrographDiagnosisPacket

新增稳定 Agent-facing 契约，完整承接 `HydrologicEvidenceBundle`：

```text
HydrographDiagnosisPacket
  overall
  water_balance
  flow_regimes
  fdc
  seasons
  years
  flood_events
  rainfall_runoff
  data_quality
  contradictions
```

Agent 不再只看到第一场 peak 或 overall 数值。

### 4.3 涨水段与退水段

V1 只做简单、透明的统计，不做复杂深度学习曲线识别：

- rising limb：起涨到观测洪峰；
- recession limb：观测洪峰到事件结束；
- 计算 slope / MAE / normalized shape error；
- 时间步不同时统一用“步数 + 实际小时数”表示。

---

## 5. P1：诊断驱动率定闭环

### 5.1 Directional Hypothesis

扩展 `DiagnosisHypothesis`：

```text
diagnostic_signature
direction
direction_confidence
direction_evidence_ids
verification_required
```

`direction` 应是模型无关或过程层级语义，例如：

- `increase_water_loss`
- `decrease_water_loss`
- `increase_runoff_response`
- `decrease_runoff_response`
- `accelerate_routing`
- `delay_routing`
- `increase_fast_component`
- `increase_slow_component`

不能让 LLM 输出“把 L 从 3 改成 1.5”作为直接动作。

### 5.2 Morris / 局部扰动负责验证方向

现有 `optimization/morris.py` 保留。

新闭环：

```text
LLM hypothesis
  ↓
限定 parameter_groups
  ↓
directional probe / Morris
  ↓
如果数值响应支持
  → DDS / SCE-UA 局部搜索
否则
  → hypothesis refuted
  → re-diagnose
```

### 5.3 Behavioral Candidate Set

优化运行不能只保留最终一套参数作为科研判断依据。

V1 保留固定数量 Top-K 行为候选，例如默认 `K=8`，要求：

- 参数向量不同；
- 主目标接近；
- 每个候选保留完整过程证据；
- 不因 objective 稍低即丢弃；
- 候选集仅在 calibration 窗口产生；
- development 只做选优/采用，不重新搜索。

候选采用比较的重点是“哪个候选在多维水文表现上更一致”，而不是再次生成一个隐藏的加权总分。

### 5.4 Research Gate 与 Standard Evaluation 解耦

建议拆成：

```text
ResearchAdoptionGate
  ├─ independent development improvement
  ├─ event guardrails
  ├─ water-balance guardrail
  ├─ high-flow guardrail
  └─ no material regression

StandardEvaluator
  └─ GB/T 22482 profile
```

最终结果同时输出：

```text
adoption_status
research_qualification
standard_profile
standard_grade
```

不得再让“缺失 GB/T 评价”自动等价于“科研候选不可继续”。

---

## 6. P2：空间异质性与计算单元推荐

### 6.1 BasinSpatialProfile

在现有 `BasinHydroProfile` 外新增空间画像，V1 只使用可审计资料：

```text
BasinSpatialProfile
  elevation
    min / max / mean / std / quantiles
  slope
    mean / std / steep_fraction
  precipitation
    station/grid count
    annual_mean_cv
    wet_event_cv
  land_cover
    dominant_classes
    class_fractions
  soil
    dominant_classes
    class_fractions
  drainage
    area
    stream_density
    main_channel_length
  evidence_quality
```

资料缺失时返回 unknown，不猜。

### 6.2 Heterogeneity Score 不直接决定单元数

可以计算各维度异质性等级用于展示，但不得使用一个总分直接推出“应该 7 个单元”。

Agent 的输入应该是：

- 各空间维度事实；
- 候选方案；
- 每个候选的面积分布、河网关系、异质性保留情况；
- 复杂度代价。

### 6.3 候选方案而非自由生成

V1 最多生成 3 类候选：

1. `lumped`：单单元；
2. `topology_subbasin`：按河网拓扑/面积阈值；
3. `heterogeneity_aware`：在拓扑候选基础上，根据空间异质性进一步拆分或合并。

Agent 只允许从候选中推荐，并给出理由及不确定性。

### 6.4 不在本阶段重写 XAJ 内核

老师 XAJ v6 原生多分区能力保留，但本设计阶段不要求：

- 重写老师内核；
- 立即开放全部多分区参数率定；
- 引入新的分布式水文模型；
- 用 LLM 直接生成空间边界。

先证明“异质性分析 → 候选计算单元 → 推荐”闭环，再决定是否进入完整多区 XAJ 运行。

---

## 7. Experience Skill 的升级方向

经验条目应从：

```text
参数变化 → NSE 变化
```

升级为：

```text
流域上下文
+ 误差现象
+ 诊断假设
+ 参数组
+ 方向验证
+ 优化实验
+ 多事件结果
+ 独立验证
→ hypothesis supported / refuted / inconclusive
```

示例：

```text
当多场洪水：
- 洪量接近无偏
- 洪峰普遍偏晚
- 上涨段偏缓

在 XAJ / 日尺度 / 当前流域条件下：
- routing 假设曾 6 次提出
- 5 次局部扰动支持 accelerate_routing
- 4 次独立 development 改善峰现且未恶化洪量

状态：
supported_prior
```

单次实验成功不得自动晋升为通用规则。

---

## 8. UI 展示目标

本设计不是 UI PR，但后续前端应能展示：

### 8.1 过程诊断卡

```text
Agent 观察
洪量基本正确
洪峰偏低 18%
峰现偏晚 1 天
6/8 场洪水具有相同模式

判断
优先怀疑汇流响应偏慢

下一步实验
routing 参数组
Morris 方向验证
SCE-UA 局部精调
```

### 8.2 次洪矩阵

行 = event，列 = peak / timing / volume / rise / recession / status。

### 8.3 候选对比

显示 Top-K 候选的多维表现，不给一个“AI 综合分”掩盖差异。

### 8.4 空间异质性

地图展示：

- 高程；
- 雨量；
- 土地利用；
- 候选计算单元；
- Agent 推荐理由。

---

## 9. 分阶段范围

### P0 必做

- 次洪分割；
- 次洪峰/时/量/涨退水证据；
- 完整过程证据进入 Agent；
- 诊断 packet；
- 过程诊断 UI 所需后端数据。

### P1 必做

- directional hypothesis；
- Morris/局部扰动验证方向；
- DDS/SCE-UA 精调；
- Top-K behavioral candidates；
- Research Gate 与 GB/T Evaluator 解耦；
- 经验条目记录 hypothesis outcome。

### P2 后做

- BasinSpatialProfile；
- 空间异质性候选方案；
- Agent 推荐计算单元；
- 地图审查和可解释输出。

### 本期明确不做

- 不新增 RL；
- 不新增多 Agent；
- 不让 LLM 直接输出最终参数；
- 不让 LLM 自由绘制子流域；
- 不替换老师 XAJ v6；
- 不把所有指标硬拼成一个“超级综合分”；
- 不把 final-test 次洪证据回流率定；
- 不在本轮直接实现完整多区率定。

---

## 10. 验收标准

### 10.1 过程诊断

- 同一 obs/sim/forcing 输入重复运行得到相同 event 边界和 metrics；
- 一场洪水可追溯到原始日期、观测、模拟和降雨；
- Agent 收到的 event 证据与 evaluator 产物一致；
- 不存在由 LLM 自己计算 NSE/洪峰/洪量的路径。

### 10.2 诊断驱动率定

- Agent 只能选择过程层、参数组、方向与实验；
- 连续参数仍由确定性优化器产生；
- 一个假设可被局部扰动/Morris 明确标记 supported/refuted/inconclusive；
- 主目标接近的不同参数候选不会被过早丢弃；
- development 选优不新增 calibration 搜索；
- GB/T 缺失不阻断 research evidence 的形成；
- final-test 仍完全隔离。

### 10.3 空间方案构建

- 相同空间资料产生相同空间画像；
- 缺数据显式 unknown；
- Agent 只能从确定性候选中推荐；
- 推荐理由能引用具体空间证据；
- 最终 polygon 来自 GIS 工具而不是语言模型自由生成。

---

## 11. 与当前代码的落点

| 能力 | 当前基础 | 主要改造位置 |
|---|---|---|
| 连续过程证据 | 已有 | `evaluation/evidence.py` |
| 次洪 | 有 Q90 事件雏形 | 新增 `evaluation/events.py` |
| Agent 证据 | 已有但压缩 | `agent/hydrologic_evidence.py` |
| 假设 | 已有 | `optimization/calibration_scientist.py` |
| Morris | 已有 | `optimization/morris.py` |
| DDS/SCE-UA | 已有 | 保留，主要改外围契约 |
| Top-K 候选 | 有 candidate 基础 | `optimization/candidates.py` + runtime |
| Gate | 已有 | `optimization/gate.py` |
| GB/T | 已有 | `evaluation/gbt22482.py` |
| 流域画像 | 仅 aridity/runoff ratio | `hydrology/basin_profile.py` + 新 spatial profile |
| 计算单元 | 已有 DEM/河网/面积流程 | `modeling/plans.py` + 新 heterogeneity 模块 |
| 经验进化 | 已有 experience 子系统 | 后续接 hypothesis outcome |

---

## 12. 参考依据

1. Duan, Q., Sorooshian, S., & Gupta, V. (1992). *Effective and efficient global optimization for conceptual rainfall-runoff models*. Water Resources Research, 28(4), 1015–1031. DOI: https://doi.org/10.1029/91WR02985  
   说明：经典 SCE-UA 论文明确讨论概念水文模型参数难以获得唯一最优解的问题。

2. Tolson, B. A., & Shoemaker, C. A. (2007). *Dynamically dimensioned search algorithm for computationally efficient watershed model calibration*. Water Resources Research, 43, W01413. DOI: https://doi.org/10.1029/2005WR004723  
   说明：DDS 是数值搜索算法，适合计算代价高、参数维度较多的流域模型率定。

3. Yilmaz, K. K., Gupta, H. V., & Wagener, T. (2008). *A process-based diagnostic approach to model evaluation: Application to the NWS distributed hydrologic model*. Water Resources Research, 44, W09417. DOI: https://doi.org/10.1029/2007WR006716  
   说明：支持通过 water balance、vertical/temporal redistribution 和 hydrologic signatures 诊断模型，而不是只依赖单一回归型综合指标。

4. Zhao, R.-J. (1992). *The Xinanjiang model applied in China*. Journal of Hydrology, 135, 371–381. DOI: https://doi.org/10.1016/0022-1694(92)90096-E  
   说明：新安江模型本身具有子流域/汇流结构，并指出不同性质参数可采用不同目标函数优化。

5. 国家标准 GB/T 22482-2026《水文情报预报规范》：https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=82F9AFB0A9422DF7579D20ECBB106560  
   发布：2026-07-30；实施：2027-02-01。

---

## 13. Superpowers 实施计划

本设计按独立子系统拆为三个计划，避免一个计划同时修改事件评价、优化闭环和空间建模：

1. `docs/superpowers/plans/2026-09-19-p0-event-process-diagnosis.md`
2. `docs/superpowers/plans/2026-09-19-p1-diagnosis-driven-calibration.md`
3. `docs/superpowers/plans/2026-09-19-p2-spatial-heterogeneity-units.md`

执行入口见：

`docs/superpowers/plans/2026-09-19-teacher-feedback-roadmap.md`

执行时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，并逐任务完成测试、审查和提交。
