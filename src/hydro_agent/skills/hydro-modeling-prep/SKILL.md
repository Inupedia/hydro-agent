---
name: hydro-modeling-prep
description: 在预报前检查建模资料、DEM/单元划分与方案边界是否足以支撑可复现实验。
metadata:
  title_zh: "建模资料与方案准备"
  purpose_zh: "先确认 DEM、站点、日资料与单元结构可信，再进入预报与率定。"
  when_to_use_zh: "数据准备阶段|新建模型方案前|边界复核失败后"
  required_evidence_zh: "DEM/站点/日资料就绪状态|结构模式|预热天数|方案 provenance"
  recommended_actions: "M01_CHECK_MATERIALS|A02_VALIDATE_SCHEME"
  activation_stages: "data"
  counterexamples_zh: "不能用建模 Skill 改写已锁定的 Campaign 分区|不能跳过资料缺失直接预报"
  prompt_references: "references/modeling-checklist.md"
---

# 建模资料与方案准备

建模阶段只回答：资料与结构是否足以支撑后续实验。

检查顺序：

1. 水文日资料、站点 GIS、DEM 是否齐全且时间/单位语义一致；
2. 集总/分布式结构、河网与单元阈值是否与研究目标匹配；
3. 预热天数是否足以稳定初始状态；
4. 方案 provenance（数据版本、参数空间、随机种子）是否可复现。

资料未就绪时，优先修复数据与边界，而不是进入参数搜索。
