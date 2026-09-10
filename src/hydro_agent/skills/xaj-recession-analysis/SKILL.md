---
name: xaj-recession-analysis
description: Diagnose XAJ source separation from observed and simulated recession signatures before changing routing or global parameters.
metadata:
  title_zh: "新安江退水与水源划分分析"
  purpose_zh: "P3阶段用lnQ-t快/中/慢退水特征约束壤中流、地下水和调蓄参数。"
  when_to_use_zh: "P3_SOURCE_RECESSION|退水过快或过慢|基流尾部不匹配"
  required_evidence_zh: "recession_fast_rel_error|recession_mid_rel_error|recession_tail_rel_error|event_recession_rel_error_median"
  recommended_actions: "A06_DIAGNOSE,A07_OPTIMIZE,A08_GATE,A09_RESOLVE"
  recommended_strategies: "xaj-local-refine-v1,xaj-bounded-v1"
  stop_conditions_zh: "退水signature误差约30%以内且水量不显著回退|本阶段平台化"
  counterexamples_zh: "不要只凭总NSE判断水源划分|不要为修地下水尾部同时放开全部产流和汇流参数"
---

# P3 退水与水源划分

对观测和模拟的正流量下降段计算 `ln(Q)` 相邻斜率，并按流量水平分成 fast / middle / tail 三类。重点比较：

- fast：洪峰后快速排泄；
- middle：壤中流和中间储泄；
- tail：地下水缓慢退水。

Agent 应根据误差出现在哪个退水带形成假设，再选择最小参数组。当前 teacher `calibrate:true` 范围内优先关注 `SM / KI / KG / CI`；teacher 冻结参数不得被数值优化器偷偷修改。

P3 候选必须继承 P2 的成果：若退水变好但多年水量显著退化，应回滚。只有退水目标和上游水量 guardrail 同时通过才进入 P4。
