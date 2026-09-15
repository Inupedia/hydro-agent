---
name: openhydronet-diagnosis
description: 面向 OpenHydroNet 的诊断建议：先区分数据、结构与训练/推理配置问题，再决定是否进入参数或架构实验。
metadata:
  title_zh: "OpenHydroNet 诊断"
  purpose_zh: "在深度学习水文模型上优先定位数据、结构与配置问题，避免套用 XAJ 参数组叙事。"
  when_to_use_zh: "模型为 openhydronet|预报后误差诊断|准备改进实验前"
  required_evidence_zh: "输入特征完整性|训练/推理配置|误差时序模式|对比基线"
  recommended_actions: "A04_DIAGNOSE|A05_OPTIMIZE"
  activation_stages: "diagnosis|experiment"
  activation_model_ids: "openhydronet"
  counterexamples_zh: "不能把 XAJ 的 evap/runoff/routing 组直接映射到 OpenHydroNet|不能在数据泄漏窗口上调参"
  prompt_references: "references/openhydronet-diagnosis.md"
---

# OpenHydroNet 诊断

OpenHydroNet 与概念性 XAJ 的可调对象不同。诊断顺序：

1. 输入特征、时间对齐与标准化是否与训练设定一致；
2. 误差是系统性偏湿/偏旱，还是峰现/退水形态问题；
3. 改进应落在数据窗口、特征、损失/目标，还是模型配置；
4. 任何实验都必须登记假设与否证条件，并隔离 final-test。

在模型未正式启用前，本 Skill 只提供诊断框架，不宣称可执行优化路径。
