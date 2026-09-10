---
name: xaj-calibration
description: Expert hydrologist workflow for bounded XAJ calibration. Use multi-year or representative flood-period calibration, separate development Gate and final holdout data, diagnose water balance/peak/timing/recession, and stop from validation-curve convergence rather than exhausting a fixed loop count.
metadata:
  title_zh: "新安江模型专家率定"
  purpose_zh: "把水文员的分阶段率定、洪水期验证和收敛停止判断固化为可审计 Agent Skill。"
  when_to_use_zh: "已有连续模拟-观测序列|NSE/GB/T未达标且允许率定|Gate要求继续或回滚后已重新诊断"
  required_evidence_zh: "多年或代表性洪水期率定集|独立Gate开发集|最终不可见留出集|水量偏差|洪峰比|峰现|退水|最近best-so-far曲线"
  recommended_actions: "A06_DIAGNOSE,A07_OPTIMIZE,A08_GATE,A09_RESOLVE,A10_FREEZE"
  recommended_strategies: "xaj-bounded-v1,xaj-peak-bias-v1,xaj-local-refine-v1"
  stop_conditions_zh: "Gate达到目标等级|验证NSE增益曲线趋平|低水平平台且存在强迫/结构警告|硬预算上限"
  counterexamples_zh: "不要把20轮当必须跑满|不要用3个lead点NSE做长期率定|不要反复查看最终留出集|不要因预算剩余继续无效搜索|不要用参数补偿缺失融雪/调度过程"
  nse_good_enough: "0.5"
---

# 新安江模型专家率定

## 核心原则

Agent 的职责不是“把循环跑满”，而是像经验水文员一样判断：**下一次调整还有没有信息增益。**

硬预算（如最多 20 次优化）只是安全上限。真正停止由 Gate 的验证曲线决定：

`多年率定 -> 开发验证 Gate -> best-so-far 曲线 -> 重新诊断 -> 下一实验 / 收敛停止`

最终独立留出期只在方案冻结后运行一次，不参与任何参数选择。

## 0. 数据时段必须先合格

参数率定不能只取十几天普通过程。优先顺序：

1. **多年连续资料**：条件允许时至少覆盖多个丰、平、枯水年；课题实验优先 5~10 年量级。
2. **代表性洪水过程**：若资料不足，率定与验证至少要覆盖若干独立洪水，包含涨水、洪峰、退水。
3. 校准集、开发 Gate 集、最终 holdout 三者必须时间上分离。
4. 开发 Gate 可以被 Agent 反复查看，因此它不是最终测试集。
5. 最终 holdout 在 `A10_FREEZE` 后才允许读取，用于论文/结题的真正泛化结果。

对 Lowman 当前实验采用：多年 calibration + 多年 Gate-development + 最终独立洪水期 holdout。

## 1. 先判断是不是“可率定问题”

检查降水、PET、观测流量的水量与趋势是否具有基本物理一致性。若观测径流持续上升而同期降水无法解释，且模型只有降水+PET，应考虑积雪融水、调度、地下水释放或资料问题。

**专家级行为包括停止错误率定。** 如果 best-so-far NSE 已进入低水平平台，同时存在 forcing/structure warning，应输出 `STRUCTURAL_LIMIT`，而不是继续用参数补偿模型缺项。

## 2. 分阶段判断水文误差

### A. 水量平衡

先看 Bias、累计径流深、降水/PET 和 NSE。

- 模拟总量偏低：优先 `evap + runoff`，重点关注 K、总蓄水能力（当前适配器以 DM 残余坐标体现）、B。
- 模拟总量偏高：同组反向约束。
- 水量没有基本对上前，不要优先微调峰现。

### B. 洪峰量级

水量合理后再看 `peak_ratio`、高流量 MAE、洪水段水量误差。

- 洪峰低估：`runoff + routing`，优先 `xaj-peak-bias-v1` + `composite`。
- 洪峰高估：`runoff + routing` 或 `xaj-local-refine-v1`。
- Gate 必须单独检查高流量/洪水表现，不能只看全时段 NSE。

### C. 峰现

峰值量级接近后再判断峰现误差，优先 routing；不要为了修一两天峰现重新放开全部产流参数。

### D. 退水与基流

退水过慢/过快时检查 CI、CS 以及 KI/KG 分配。teacher 标记 `calibrate:false` 的参数默认冻结。

## 3. 最小可识别参数原则

自动率定仅允许 teacher 参数边界中 `calibrate:true` 的自由度。目前主要为：

`K, B, DM(代表总WM调整), SM, KG, KI, CI, CS`

Agent 选择的是**参数组与实验假说**，数值优化器在组内做有界搜索；LLM 不直接发明连续参数向量。

## 4. 每轮 A07 必须是一个实验

每次优化前需要回答：

- 当前主要误差是什么？
- 哪个物理环节最可能解释它？
- 最小需要放开的参数组是什么？
- 本轮目标用 NSE、peak 还是 composite？
- 上一轮为什么失败或成功？

Gate `ROLLBACK` 后必须重新 A06；禁止只换 random seed 或 strategy 名称继续盲搜。

## 5. Gate 是收敛控制器，不是静态阈值门

Gate 维护开发验证集上的 **best-so-far NSE/DC 曲线**。

状态语义：

- `ACCEPT`：达到要求的 GB/T 等级/绝对精度，立即停止。
- `CONTINUE`：候选在开发集上确实更好；晋升为新的 base，重新诊断后继续。
- `ROLLBACK`：候选没有泛化增益或破坏洪水/高流量 guardrail；保留旧 base，重新诊断。
- `CONVERGED`：最近若干次 best-so-far 增益、斜率、波动均趋近于零；即使还有预算也停止。
- `STRUCTURAL_LIMIT`：低水平收敛/连续失败，并有强迫或模型结构不足证据；停止参数补偿并升级模型/数据问题。

### 收敛判断

不要只比较本轮 `candidate - base`。至少观察最近 3~4 个 best-so-far 点：

- 窗口累计增益很小；
- 增长斜率接近 0；
- best-so-far 波动/跨度很小；
- 同时没有新的洪水期泛化改善。

满足这些条件就说明继续搜索的边际价值很低。**剩余轮数不是继续率定的理由。**

## 6. 洪水期 Gate guardrail

多年 NSE 改善仍可能牺牲洪水。Gate 必须同步看：

- 高流量（如 Q90 以上）MAE；
- 洪峰相对误差；
- 峰现误差；
- 洪水段水量偏差；
- GB/T 22482 指标与方案等级。

候选全时段 NSE 更高但洪水表现显著变差时，应 `ROLLBACK`。

## 7. 三段数据角色

推荐课题实验：

`Calibration 多年连续期 -> Gate-development 多年/多洪水期 -> Freeze -> Final holdout 洪水期`

例如 Lowman 基准可使用：

- 2011-01-01 ~ 2017-12-31：率定；
- 2018-01-01 ~ 2019-12-31：开发 Gate，允许反复查看；
- 2020-04-01 ~ 2020-07-31：最终独立洪水/融雪高流量期，只在冻结后读取。

这些日期是基准实验划分，不应写死到通用 Skill；真实项目应按资料年限和洪水代表性配置。

## 8. 关于“20次”

`max_optimization_cycles <= 20` 可以作为硬上限，但绝不是目标次数。

可能出现：

- 第 3 次已达到目标 → ACCEPT；
- 第 5 次曲线已经明显趋平 → CONVERGED；
- 第 2~4 次低水平平台且发现融雪强迫缺失 → STRUCTURAL_LIMIT；
- 只有仍持续获得可靠开发集增益时才继续，最多不超过硬上限。

XAJ 单次计算便宜，因此每个 A07 内部可以评估数百个有界参数候选；要节省的是无意义的 Agent 实验轮次，而不是数值函数调用次数。

## 9. 最终成功标准

最终论文/结题结果只看 Freeze 后的 final holdout：

- NSE/DC、KGE、Bias；
- 洪峰误差、峰现、洪水段水量；
- GB/T 方案等级；
- calibration / development Gate / final holdout 三者差距；
- 实际用了多少次优化，以及为什么停止。

如果开发集很好但最终 holdout 明显掉点，应明确报告泛化失败，而不能重新打开 final holdout 继续调参。
