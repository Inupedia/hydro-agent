---
name: hydrologic-evidence-review
description: 模型无关地审查观测与模拟的水文证据，先描述季节、流量、洪水和退水现象，再提出可证伪的问题；不直接推断 XAJ 参数。
metadata:
  title_zh: "水文证据审查"
  purpose_zh: "把确定性指标与过程线整理成现象、支持证据和反证。"
  recommended_actions: "A04_DIAGNOSE"
  prompt_references: "references/hydro-error-diagnosis-metric-patterns.md|references/hydro-error-diagnosis-diagnosis-routing.md|references/openhydronet-diagnosis-openhydronet-diagnosis.md"
---

# 水文证据审查

输入只能是有来源、窗口和样本数的 HydrologicEvidence：观测/模拟过程、NSE/KGE/PBIAS、季节与高低流量、洪峰时间与量级、洪量、退水及 forcing 对齐证据。先描述现象，再列支持与反证；标明尚未测量的维度。

本层不把一个指标映射成具体 XAJ 参数，不把水量接近说成洪峰或季节达标。NSE/KGE/PBIAS 和事件指标由 evaluation 计算；本 Skill 只解释其证据边界。OpenHydroNet 的结构与配置排查见按需 Reference，不能套用 XAJ 参数组。
