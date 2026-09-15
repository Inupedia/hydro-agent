# XAJ 率定工作流

Observe → Diagnose → Hypothesis → ExperimentPlan → Numerical Search → Development Gate → Resolve → Reflect。

每轮只把上一轮产生的新 Evidence 写回 World State；不要把 calibration 最优值当成最终成功。候选只有在独立 development Gate 后才有资格成为新的工作基线。冻结条件由 Campaign 统一判断。