---
name: data-check
description: Verify basin forcing and observations are sufficient for forecast or calibration before blaming the model. Use at task start, after forecast failure, or when observation coverage is thin.
metadata:
  title_zh: "资料核查"
  purpose_zh: "确认强迫与观测是否足以支撑预报/率定，而不是默认模型问题。"
  when_to_use_zh: "任务刚开始|预报失败|观测样本不足"
  required_evidence_zh: "流域与方案存在|snapshot 或源数据可物化"
  recommended_actions: "A01_CHECK_DATA,A03_VALIDATE_SCHEME"
  stop_conditions_zh: "资料不可用且无法修复"
  counterexamples_zh: "已有完整预报证据时不要反复只做资料检查"
---

# 资料核查

## 何时使用

- 任务刚开始，尚未确认数据可物化
- 预报失败且可能是资料问题
- 观测样本不足以支撑诊断或率定

## 步骤

1. 选择 `A01_CHECK_DATA` 确认流域、强迫、观测可用
2. 必要时 `A03_VALIDATE_SCHEME` 校验方案
3. 资料不可修复时停止，不要进入率定

## 停止条件

- 资料不可用且无法修复
- 已有完整预报证据时不要反复只做资料检查
