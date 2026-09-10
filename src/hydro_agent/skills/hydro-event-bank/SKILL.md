---
name: hydro-event-bank
description: Build basin-adaptive flood event evidence from continuous discharge for calibration, routing diagnosis, and representative-event validation.
metadata:
  title_zh: "洪水事件库"
  purpose_zh: "把多年连续序列转换成可逐场比较的洪峰、峰现、洪量、退水证据。"
  when_to_use_zh: "P3_SOURCE_RECESSION|P4_ROUTING_EVENT|P6_DEVELOPMENT_VALIDATION"
  required_evidence_zh: "连续观测/模拟流量|时间步长|足够长历史序列"
  recommended_actions: "A06_DIAGNOSE,A08_GATE,A12_EVALUATE_REPORT"
  stop_conditions_zh: "事件数量与量级覆盖足以支持当前阶段判断"
  counterexamples_zh: "不要把全时段最大峰当成所有洪水|不要把固定绝对阈值从别的流域照搬过来"
---

# 洪水事件库

事件提取服务应从连续观测流量识别高流量簇，保存每场事件的起止、观测峰值、模拟峰值、峰现误差、洪量误差和退水误差。

事件量级按本流域事件洪峰分位进行相对分类，至少区分 small / medium / large。开发 Gate 应同时报告全事件中位数与 large-event 子集，防止多年平均指标掩盖大洪水失败。

事件库是诊断证据，不是新的可调参数来源。若事件受融雪、调度等当前 forcing/model 未表达过程主导，应标记 regime/quality warning，而不是硬解释成 XAJ 参数问题。
