# 防数据泄漏检查

- calibration：允许优化器直接使用。
- development：允许独立 Gate 比较候选与当前基线，但不能冒充 final test。
- final-test：冻结前不得进入诊断、Skill prior、参数选择或停止判断。
- 历史案例/专家 prior 如果由当前数据集产生，必须通过 `evidence_dataset_ids` 过滤间接泄漏。
- 任何已经暴露给调参过程的数据都不能事后重新标记为 unseen final-test。

Skill 只解释这些原则；实际窗口与禁止访问规则由 Campaign/Protocol 强制执行。