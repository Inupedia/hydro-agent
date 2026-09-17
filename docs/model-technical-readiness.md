# 水文模型与 Agent Skill 技术验收基线

本文记录的是产品运行边界，不是模型清单。只有通过数值内核技术验收的模型，才能在正式任务中开放自动率定；其余模型只允许做受限预报和实现验证。

## 当前结论

| 模型 | 当前实现 | 技术状态 | 正式自动率定 | 主要依据与缺口 |
| --- | --- | --- | --- | --- |
| XAJ | 固定版本的 `hydromodel` XAJ teacher kernel | `source_verified` | 开放 | 保留上游内核、状态和 warm-up 语义；当前传统 ModelPlan 资料链仍只覆盖内置腰古数据 |
| GR4J | Hydro-Agent NumPy GR4J | `source_verified` | 开放 | 已与 GRsuite/airGR-1.7.9 对齐完成逐日状态与流量 parity（阈值见 `models/gr4j/parity.py`）；UH 90% 分割使用 airGR 同款 `float32(0.9)` |
| HBV | Hydro-Agent NumPy HBV-light | `source_verified` | 开放 | 已对齐 Seibert & Vis / hydromad HBV-light（含 `UZL`、`SFCF`、连续 `MAXBAS`）；阈值见 `models/hbv/parity.py`；分区与 CET 重建不在 lumped 产品范围 |
| Tank | Hydro-Agent NumPy 3-tank + discrete Nash | `source_verified` | 开放 | 产品固定三层水箱 + 整数 Nash 级数（`N` 采样后取整）；独立方程 oracle parity（见 `models/tank/parity.py`）；不宣称等同经典四层 Sugawara 全图 |
| SAC-SMA | Hydro-Agent NumPy NOAA-OWP SAC-SMA（16 参数、无冻土过程） | `source_verified` | 开放 | 移植 NOAA-OWP `SAC1`/`EXSAC` 的无冻土结构：增量子步长、`ADIMP` 饱和产流、`PFREE` 分配、`RIVA` 河岸蒸散、`SIDE` 非河道基流、`RSERV` 补给；与固定版本 NOAA-OWP Fortran 可执行输出完成逐日状态/分量 parity（阈值与 revision 见 `models/sacsma/parity.py`）；当前预报输出另接仓库自定义日尺度三角单位线，`HOURS<=24` 时退化为同日响应，不属于 NOAA parity 范围 |

技术参考：

- GR4J：Perrin, Michel & Andréassian (2003), <https://doi.org/10.1016/S0022-1694(03)00225-7>；参考实现 `airGR`：<https://hydrogr.github.io/airGR/>。
- HBV-light：Seibert & Vis (2012), <https://doi.org/10.5194/hess-16-3315-2012>；参考实现对齐 hydromad pure-R HBV；University of Zurich HBV-light：<https://www.geo.uzh.ch/en/units/h2k/Services/HBV-Model.html>。
- SAC-SMA：NOAA-OWP `sac-sma`：<https://github.com/NOAA-OWP/sac-sma>。
- Tank model family：Sugawara et al.：<https://www.jstage.jst.go.jp/article/jgeography1889/94/4/94_4_209/_article>；本产品实现为三层 + 离散 Nash 汇流变体（见 `models/tank/parity.py`）。

## Agent、Skill 与 Core 的实际执行边界

1. A04 只生成可审计的诊断证据和确定性 fallback，不直接生成连续参数。
2. 在线 LLM 必须从当前模型发布的 `available_strategies`、`available_param_groups` 和三个合法 objective 中选择实验方向。
3. 模型专属 diagnosis Skill 把该选择编译为 `DiagnosisHypothesis`；公共 experiment-design Skill 再编译为 typed `CalibrationPlan`。
4. LangGraph 的 experiment guardrail 保留已经绑定的 Skill plan，并检查模型注册表、参数组、历史触边界证据和 campaign objective。只有硬约束可以覆盖 Skill plan。
5. 优化器在 Core 中搜索连续参数；Agent 和 Prompt 均不得输出连续参数向量。
6. A06/A07 独立决定候选是否采用；A08 冻结后，final-test 只能被 A09/A10 只读消费一次，不能返回实验设计环节。

确定性 `CalibrationScientistDecisionProvider` 不执行自然语言 Prompt。它通过同一 typed Skill/Core contract 产生可复现 fallback。`SiliconFlowDecisionProvider` 才读取 `SKILL.md` 及引用内容；其输出仍必须通过同一 typed contract 和 guardrail。因此，Prompt 可以选择合法实验方向，但不能改变模型公式、参数边界、预算、Gate 或 final-test 隔离规则。

## Prompt 验收规则

- Prompt 不得包含只适用于其他模型的策略示例或参数组。
- 每个模型专属 Skill 必须声明当前实现的真实变体、参数语义、缺失过程和禁止推断项。
- `peak` objective 当前只衡量洪峰幅值相对误差，不代表峰现时间；`composite` 当前映射为 KGE，不得描述成未实现的多指标加权函数。
- Skill 建议必须带模型作用域；跨模型 strategy 或 parameter group 必须回退到当前模型注册的安全方案。
- 未通过内核验收的模型必须从 `WorldStateView.model.capabilities` 移除 `calibrate`，且 API 在任务创建时拒绝 `allow_optimization=true`。

## 后续模型验收门槛

在放开任一实验模型的正式自动率定前，至少要完成：

1. 明确模型方程、状态更新顺序、单位、初始状态、warm-up 和缺测处理。
2. 使用官方或公认参考实现完成逐时段状态、流量和累计水量 parity；误差阈值必须预先注册。
3. 完成零降水、恒定降水、极端参数、分段续算和水量平衡测试。
4. 检查每个可率定参数是否对目标函数具有连续且可辨识的影响；离散参数必须使用离散搜索或固定配置。
5. 逐条核对模型 Skill 的过程解释、参数组、策略和 objective 语义，并证明 Prompt 选择在真实 LangGraph 路径中没有被静默覆盖。
6. 通过以上门槛后，才能把 `validation_status` 提升为 `source_verified`，并将 `supports_calibration` 改为 `true`。

这套基线通过代码闸门执行。更改标题或新增 Skill 目录不会自动提升模型成熟度。
