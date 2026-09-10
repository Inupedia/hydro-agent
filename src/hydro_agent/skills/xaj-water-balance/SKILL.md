---
name: xaj-water-balance
description: Calibrate XAJ evapotranspiration and runoff-production behaviour against multi-year water balance before optimizing hydrograph shape.
metadata:
  title_zh: "新安江多年水量平衡率定"
  purpose_zh: "P2阶段优先把多年、年际和季节径流总量控制正确。"
  when_to_use_zh: "P2_WATER_BALANCE|多年径流量系统偏差|季节性水量偏差"
  required_evidence_zh: "volume_rel_error|annual_volume_bias_mae|seasonal_volume_bias_mae|P/PET/Q一致性"
  recommended_actions: "A06_DIAGNOSE,A07_OPTIMIZE,A08_GATE,A09_RESOLVE"
  recommended_strategies: "xaj-bounded-v1,xaj-local-refine-v1"
  stop_conditions_zh: "多年水量误差约10%以内且年际/季节约束通过|本阶段搜索平台化"
  counterexamples_zh: "不要在水量未对齐时优先调峰现|不要因为NSE短期下降否决明显改善的水量平衡"
---

# P2 水量平衡

本阶段主目标不是 NSE，而是水量闭合。

优先证据：

- `volume_rel_error`；
- `annual_volume_bias_mae`；
- `seasonal_volume_bias_mae`；
- 丰、平、枯年份是否存在同方向系统偏差；
- precipitation / PET / observed runoff depth 是否基本物理一致。

调参遵循最小自由度原则。优先检查蒸散发折算与流域蓄水能力，再考虑蓄水容量分布。不要因为某一场洪峰暂时变差就破坏多年水量修正；但若候选造成灾难性过程退化，应保留 guardrail。

完成条件是水量约束通过，而不是“当前 NSE 最大”。通过后锁住已稳定的水量参数，进入 P3。
