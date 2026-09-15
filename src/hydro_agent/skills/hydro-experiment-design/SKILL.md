---
name: hydro-experiment-design
description: 将当前水文诊断假设转换成一轮可证伪、可比较、受硬边界约束的数值 ExperimentPlan。
metadata:
  title_zh: "水文实验设计"
  purpose_zh: "决定这一轮测什么、为什么测、开放哪些参数组以及什么结果会支持或否定假设。"
  when_to_use_zh: "A04 形成假设后|Gate 后需要下一轮实验|局部搜索触边界但绝对边界仍有空间"
  required_evidence_zh: "diagnosis|当前基线|上一轮 Gate|Campaign locks|可用 strategy registry"
  recommended_actions: "A05_OPTIMIZE|A06_GATE|A07_RESOLVE"
  recommended_strategies: "xaj-water-balance-v1|xaj-routing-refine-v1|xaj-hydro-composite-v1|xaj-local-refine-v1|xaj-broadened-refine-v1"
  counterexamples_zh: "Agent 不直接给原始参数向量|实验不能越过 Validator 绝对边界|不能改 campaign objective"
  prompt_references: "references/experiment-strategies.md|references/hypothesis-testing.md|references/budget-allocation.md"
---

# 水文实验设计

每轮 ExperimentPlan 至少说明：

1. **Hypothesis**：当前认为哪个水文过程最可能解释误差；
2. **Intervention**：只开放哪些参数组/选择哪个已注册 strategy；
3. **Expected evidence**：如果假设正确，哪些指标或过程特征应改善；
4. **Falsification**：什么结果意味着本假设应降权或回退；
5. **Budget**：本轮最多允许多少模型评估；
6. **Independent check**：候选必须进入 development Gate，不能用 calibration 指标自证成功。

Agent 决定 WHAT/WHY；optimizer 决定具体参数值；Validator 决定合法空间。
