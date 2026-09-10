---
name: xaj-calibration
description: Expert hydrologist workflow for bounded XAJ calibration. Diagnose water balance, peak magnitude, timing and recession separately; choose only identifiable parameter groups; validate every candidate on held-out observations; stop rather than compensate for missing forcing or model structure.
metadata:
  title_zh: "新安江模型专家率定"
  purpose_zh: "把水文员的分阶段率定判断固化为可审计 Agent Skill，在有限决策轮次内高效提高可验证精度。"
  when_to_use_zh: "已有多日模拟-观测诊断|NSE/GB/T未达标且允许率定|Gate拒绝后已重新诊断"
  required_evidence_zh: "至少7日且优先30日以上独立诊断序列|水量偏差|洪峰比|峰现时差|退水形态|降水/PET与观测径流一致性|最近Gate结果"
  recommended_actions: "A06_DIAGNOSE,A07_OPTIMIZE,A08_GATE,A09_RESOLVE,A10_FREEZE"
  recommended_strategies: "xaj-bounded-v1,xaj-peak-bias-v1,xaj-local-refine-v1"
  stop_conditions_zh: "held-out NSE/GB/T达标|优化预算耗尽|连续两轮Gate变差且强迫/结构不充分|候选重复"
  counterexamples_zh: "不要用3个lead点的NSE指导长期率定|不要每轮同时乱动全部参数|不要用验证窗反向调参|不要用参数补偿缺失的融雪/调度/观测问题"
  nse_good_enough: "0.5"
---

# 新安江模型专家率定

## 角色分工

Agent 负责像水文员一样**判断问题、选择实验和解释证据**；数值优化器负责在合法参数边界内搜索连续参数。Agent 不直接猜 15 维参数向量。

核心循环不是“看到 NSE 低就继续随机搜”，而是：

`诊断 -> 选择一个水文问题 -> 选择最小参数组/目标 -> A07 -> held-out A08 -> A09 -> 重新诊断`

每个被拒绝的 Gate 都是新证据。必须重新 A06，禁止沿用旧诊断机械重复实验。

## 0. 先判断这是不是一个“可率定问题”

1. 诊断样本不少于 7 个日尺度点，优先 30 日以上；3 个 lead 点只能用于即时预报诊断，不能作为参数识别依据。
2. 校准数据与 held-out 验证窗严格分离，不能根据 Gate 窗的具体观测去改参数。
3. 检查降水、PET、观测流量的水量和趋势是否具有基本物理一致性。
4. 若观测径流持续上升、同期降水不足，而模型只有降水+PET，考虑积雪融水、上游调度、地下水释放等未建模过程。
5. 连续两轮候选在 held-out Gate 中都比基线差，同时存在强迫充分性警告时，停止参数补偿，输出 `FORCING/STRUCTURE` 升级结论。

**专家水平不是任何数据都把 NSE 调高，而是知道什么时候参数率定没有可识别性。**

## 1. 按水文现象分阶段，不同时解决所有问题

按以下优先级读 `hydro.diagnosis.metrics`。

### A. 水量平衡先行

看：`mean_bias`、累计水量、`observed_runoff_depth_mm`、NSE。

- 模拟总量明显偏低：优先 `evap + runoff`，通常关注 `K`、总蓄水容量 `WM`（本适配器用 `DM` 作为残余坐标）、`B`。
- 模拟总量明显偏高：同组反向约束。
- 水量还没基本对上之前，不要把主要精力放在峰现微调。
- 目标优先 `nse`；若同时存在明显洪峰问题可用 `composite`。

物理方向提示：`K↑` 通常蒸散增强、径流减小；总 `WM↑` 通常更难产流；`B↑` 往往使局部更早达到蓄满产流。方向只用于解释和缩小搜索，不允许越界直接编造参数值。

### B. 洪峰量级

在水量大致合理后看 `peak_ratio`：

- 洪峰明显低估：`runoff + routing`，优先 `xaj-peak-bias-v1` + `composite`；重点由数值搜索在可率定参数 `B/SM/KI/KG/CS/CI` 中寻找组合。
- 洪峰明显高估：`runoff + routing` 或局部细化，优先 `xaj-local-refine-v1`。
- `SM↑` 往往使自由水调蓄增强、洪峰更平缓；`CS↑` 往往增强河网记忆、峰值更低/更滞后。

### C. 峰现时间

只有在峰值量级不再严重失真时才单独追峰现：

- 峰偏晚：优先 `routing`，检查汇流记忆。
- 峰偏早：同理反向检查。
- 不要为了修峰现把产流参数全部重新全局搜索。

### D. 退水与基流

看退水段是否系统过慢/过快：

- 退水过慢、记忆过强：关注 `CI/CS` 及 `KI/KG` 分配。
- 退水过快：反向检查。
- `CG` 等 teacher 明确标记 `calibrate:false` 的参数默认冻结，不得因为搜索方便而擅自放开。

参数意义和方向详见 `references/xaj-parameters.md`，完整操作表见 `references/hydrologist-calibration-playbook.md`。

## 2. 参数可识别性与最小改动原则

自动率定只允许 teacher 参数边界中 `calibrate:true` 的自由度。当前适配坐标为：

`K, B, DM(代表总WM调整), SM, KG, KI, CI, CS`

其余参数默认冻结。即便 Agent 选择 `runoff+routing`，数值运行时也必须再次与这份白名单求交集。

每轮只选择能够解释当前主要误差的参数组。不要因为“多参数更容易找到高 NSE”而把不可识别参数一起放开。

## 3. 数值搜索策略

- 第一次、误差模式不清：`xaj-bounded-v1`，做足够深的全局有界探索。
- 明显洪峰系统偏差：`xaj-peak-bias-v1`。
- 已接近有效区域：`xaj-local-refine-v1`。
- 同一策略再次使用时必须换可复现的新 seed；禁止生成完全相同的候选。
- Agent 决策轮次可以 <=20，但每个 A07 内部允许几百次廉价 XAJ 计算。不要把“20 个 agent round”误解成“只能算 20 个参数向量”。

## 4. Gate 后如何复盘

A08 后必须 A09。若 `KEEP/ROLLBACK` 且仍有预算：

1. A06 重新诊断当前基线；
2. 比较本轮 candidate 的参数组与 Gate 变化；
3. 判断失败属于水量、峰值、峰现、退水，还是强迫/结构；
4. 下一 A07 必须形成**不同的实验假说**，而不是只轮换 strategy 名称；
5. 若同一基线连续两轮 Gate 变差且存在 forcing adequacy warning，停止率定。

## 5. 20 轮预算模板

推荐最多 3 个有意义的数值实验，而不是 4 个没有复盘的随机实验：

`A01 -> A03 -> A05 -> A06 -> [A07 -> A08 -> A09 -> A06] x 2~3 -> A10 -> A11 -> A12`

三次完整“率定-验证-复盘”通常可控制在 20 个 Agent round 内。若更早 ACCEPT，立即冻结；若确认结构不适用，也应提前停止。

## 6. 成功标准

优先以 held-out Gate 和最终 replay/evaluate 判断，而不是校准集最好分数：

- 目标：`NSE/DC >= nse_good_enough` 且 GB/T 最低方案等级满足项目要求；
- 同时看 Bias/水量误差、洪峰误差、峰现和过程精度，防止单指标过拟合；
- 若模型结构/强迫不足，正确结果是明确升级模型或数据需求，不得伪造“高 NSE”。
