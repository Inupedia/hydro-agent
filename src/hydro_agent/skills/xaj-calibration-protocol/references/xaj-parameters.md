# XAJ 参数说明与率定边界

来源于当前 XAJ teacher 参数定义与 `parameter_bounds.yaml`。数值率定默认只允许 `calibrate:true` 的自由度；Agent 可以讨论冻结参数的物理意义，但不能让 optimizer 偷偷修改它们。

| 模块 | 参数 | 物理作用 | 当前自动率定 |
|---|---|---|---|
| 蒸散发/水量 | K(KC) | 增大蒸散发能力，通常减少径流 | 是 |
| 张力水 | UM/WUM | 上层张力水容量 | teacher冻结 |
| 张力水 | LM/WLM | 下层张力水容量 | teacher冻结 |
| 张力水 | DM | 当前适配器中承担总 WM 的可调残余坐标 | 是 |
| 蒸散发 | C | 深层蒸散发系数 | teacher冻结 |
| 产流 | IM/IMP | 不透水面积比例 | teacher冻结 |
| 产流 | B | 蓄水容量分布曲线指数 | 是 |
| 水源 | SM | 自由水蓄水容量 | 是 |
| 水源 | EX | 自由水容量曲线指数 | teacher冻结 |
| 水源 | KI | 壤中流出流系数 | 是 |
| 水源 | KG | 地下径流出流系数 | 是 |
| 汇流 | CI | 壤中流消退 | 是 |
| 汇流 | CG | 地下径流消退 | teacher冻结 |
| 汇流 | CS | 河网消退 | 是 |
| 汇流 | L/LAG | 纯滞后时段 | teacher冻结 |

当前自动率定自由度：`K, B, DM, SM, KI, KG, CI, CS`。

重要约束：

1. `WM = UM + LM + DM`；当前实现以 DM 作为 WM 调整坐标，同时保持 teacher 冻结的 UM/LM 不变。
2. `KG + KI < 1`；任何候选必须满足实现/物理约束。
3. 参数组只是 Agent 的实验权限边界：`evap / runoff / routing`；真正参与采样的参数仍要与 `calibrate:true` 求交集。
4. P2/P3/P4 逐阶段释放最少必要自由度；P5 才允许在已经通过的物理约束内联合优化。
