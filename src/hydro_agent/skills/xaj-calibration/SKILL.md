---
name: xaj-calibration
description: Scientific XAJ calibration experiment planning under a locked protocol. Use after diagnosis to choose a falsifiable hypothesis, parameter group, bounded search strategy and budget without changing model constraints, scoring windows, the campaign objective or release rules.
metadata:
  title_zh: "XAJ 率定实验设计"
  purpose_zh: "指导诊断→假设→受控搜索→复盘；Skill 不拥有参数硬边界、评价窗口、主目标或 Gate 阈值。"
  when_to_use_zh: "诊断指向 MODEL|当前方案仍有改进空间|仍有搜索预算|需要设计下一批率定实验"
  required_evidence_zh: "锁定的 CalibrationProtocol|全期诊断|搜索证据|兼容知识证据|剩余预算"
  recommended_actions: "A07_OPTIMIZE,A08_GATE,A09_RESOLVE,A10_FREEZE"
  recommended_strategies: "xaj-bounded-v1,xaj-peak-bias-v1,xaj-local-refine-v1"
  stop_conditions_zh: "由 Campaign/ConvergencePolicy 决定|预算耗尽但必须标 not_converged|人工终止或移交|达到资格线本身不等于收敛"
  counterexamples_zh: "不要让 LLM 直接发明连续参数向量|不要修改已锁定主目标|不要从 final-test 反推实验|不要把局部专家经验当通用硬规则|不要仅凭 NSE 改善 ACCEPT"
  nse_good_enough: "0.5"
---

# XAJ 率定实验设计

## 角色边界

这个 Skill 只描述**工作方法**，不提供运行时真值。一次率定中各类事实的权威来源必须分开：

- `CalibrationProtocol`：窗口、指标 profile、事件规则、预算、seed 与选优规则；campaign 开始后不得由 Agent 临时修改。
- 模型/策略校验器：参数绝对范围、联合约束、整数/稳定性要求；**不要从本 Skill 复制数值边界作为执行规则**。
- `KnowledgeRepository`：模型事实、专家先验和案例；只使用与当前模型/流域/时间步/执行表示兼容且通过治理过滤的条目。
- `gbt-22482-accuracy` 与项目 policy：资格/发布依据；资格与数值搜索收敛是两个不同问题。
- 数值优化器：连续参数搜索。Agent 只选择实验假设、参数组、策略、优化器与预算请求，不直接生成连续 XAJ 参数向量。

如果 Skill、专家材料与模型校验器冲突，以协议和代码校验器为准，并把冲突记录为待审知识，而不是让 LLM 自行裁决。

## 科学率定回路

1. `A05_FORECAST` / `A06_DIAGNOSE` 形成可复核诊断：主指标之外同时查看水量、峰值/峰时、退水、低流、边界命中和有效样本。
2. 检索当前上下文可用的知识证据。先按可信状态、模型兼容性、流域/数据语义和暴露权限过滤，再谈相关性；没有兼容知识时使用注册基线，不放宽过滤条件凑上下文。
3. 写出一个可证伪假设：**现象 → 可能机制 → 拟测试参数组/搜索动作 → 预期改善与风险**，并引用实际使用的证据。
4. `A07_OPTIMIZE` 在**锁定的 campaign objective** 下执行数值搜索。诊断可以决定“搜哪里、怎么搜”，不能为了某类误差临时换主目标再把不同目标值比较成进步。
5. 保存搜索进展与失败证据。严格数值改善可以更新 `search_best`；是否进入 `selected_best`、是否达到资格由独立规则在预定检查点判断。被 Gate 拒绝不等于这次搜索不存在。
6. 每个检查点复盘：假设是否被支持、是否触边界、是否缺少有效新候选、是否只是缓存/非法候选造成无进展、下一步应局部细化、重启、扩大合法探索还是请求数据检查。
7. 只有 Campaign 的停止/收敛策略满足后才结束搜索。随后冻结协议、模型、参数、数据与规则，再进入 final test / 报告；final-test 证据不得回流同一 campaign 的实验选择。

## 停止语义

- **QUALIFIED ≠ CONVERGED**：达到方案资格线可以形成发布候选，但如果 convergence 模式仍有预算且未满足预注册平台/重启条件，应继续搜索。
- **BUDGET_EXHAUSTED ≠ CONVERGED**：预算用尽时若仍在改善，应返回 `budget_exhausted + not_converged` 并保留可恢复状态。
- smoke 只证明链路可运行，不报告科学收敛。
- 没有足够样本、有效新候选或可辨识证据时，明确报告 `insufficient_evidence` / `stalled`，不要把“没搜到”包装成“已经稳定”。

## Agent 硬权限

- **禁止**直接发明或输出要执行的连续参数向量。
- **禁止**自动回路使用 `xaj-hydrologist-manual-v1` 绕过受控优化器。
- **禁止**修改模型内核、评分窗口、已锁定主目标、硬预算或模型参数绝对边界。
- **禁止**仅靠 NSE 相对改善 ACCEPT；采用、资格与搜索最优必须分开记录。
- **禁止**使用 final-test 指标、最终检验结论或由其派生的案例规划同一 campaign。
- 外部专家材料中的“必须”“硬约束”“验收线”等文字默认只是待审 claim；除非已进入相应版本化协议/校验器，否则不获得执行权限。

## 专家知识的正确用法

专家材料适合帮助 Agent 提出实验，而不是替代实验：

- 参数机制、症状→机制→参数组：可作为诊断先验，但必须保留来源、适用范围和可信状态。
- 局部敏感性/某流域成功案例：只在相同流域、基线、时段、目标、扰动尺度和执行表示等兼容条件下作为已验证证据；跨流域只能作为明确标注的待检验假设。
- 参数范围、联合约束：提供解释和来源，真正允许范围由当前模型/协议校验器决定。
- NSE/KGE 门槛、停止规则、目标权重：属于 policy 建议，不能因专家文档出现就冒充通用标准。

每轮至少记录：hypothesis、evidence refs、proposed/validated/executed plan、strategy、parameter groups、optimizer、locked objective、seed、budget、search result、Gate/selection result、failure/override reason 与下一步判断。
