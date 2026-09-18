# Experience Skill Evolution 执行索引

> **For agentic workers:** 本索引按 obra/superpowers 的 writing-plans 方法拆分。每个子计划都是独立可测试交付单元；执行时优先使用 superpowers:subagent-driven-development，也可使用 superpowers:executing-plans。

**Spec:** docs/superpowers/specs/2026-09-18-experience-skill-evolution-design.md

## 总体拆分

| 顺序 | 子计划 | 目标 | 主要依赖 |
|---|---|---|---|
| SP1 | Experience State & Persistence | 建立结构化 Experience Store、Evidence Provenance、版本元数据 | 无 |
| SP2 | Reflection & Convergence | Task 结束后生成 Experience Diff，并计算 learning/converging/converged/reopened | SP1 |
| SP3 | Agent Skill Compiler & Versioning | 按 Agent Skills 标准编译、校验、保存、冻结 Experience Skill 版本 | SP1 |
| SP4 | Runtime Experience Policy | 将 Experience 真正接入 WorldState、AgentDecision、Exploitation/Exploration | SP1 + SP3；使用 SP2 产生的经验 |
| SP5 | Regression & Promotion | Candidate Skill 回归、Hard Case、自动 Gate、Promote/Reject | SP2 + SP3 + SP4 |
| SP6 | API & Evolution Observatory | 提供只读 API 和前端进化观测台，展示完整证据链 | SP1-SP5 |

## 计划文件

1. docs/superpowers/plans/2026-09-18-sp1-experience-state-persistence.md
2. docs/superpowers/plans/2026-09-18-sp2-experience-reflection-convergence.md
3. docs/superpowers/plans/2026-09-18-sp3-experience-skill-versioning.md
4. docs/superpowers/plans/2026-09-18-sp4-runtime-experience-policy.md
5. docs/superpowers/plans/2026-09-18-sp5-experience-regression-promotion.md
6. docs/superpowers/plans/2026-09-18-sp6-agent-evolution-observatory.md

## 推荐执行顺序

~~~
SP1
 |\
 | \
 v  v
SP2 SP3
 \  /
  \/
  SP4
   |
   v
  SP5
   |
   v
  SP6
~~~

SP2 与 SP3 在 SP1 合并后可以并行开发。

## 全局约束

所有子计划共同遵守：

- 不实现用户画像或用户偏好。
- Experience 是共享 Agent 资产。
- Experience State 持续变化，不等于 Skill Version 持续升级。
- 只有结构变化才能创建 Candidate Version。
- Experience 仅为 advisory knowledge，不能绕过 Validation Gate、参数边界、阶段权限和 leakage 防护。
- Experience Skill 必须遵守 Agent Skills 公开规范。
- Task 运行期间 Experience Skill Snapshot 不可变化。
- 相同输入 + 相同 Experience Skill Version 的核心决策应尽量可复现。
- Exploration 必须具有水文合理性，不能靠纯随机制造“不同结果”。
- 每条 Experience Influence 必须能追溯到 Evidence。
- 新代码遵循项目现有 Python 3.12、Pydantic 2、SQLAlchemy 2、FastAPI、Vue 3 + TypeScript、Vitest/Playwright 技术栈。
- TDD：每个任务先写失败测试，再实现最小代码，再跑测试。
- 频繁提交；每个 Task 应有独立、可审查的 commit。

## 整体验收

完成全部 SP 后，必须端到端演示：

1. Task A 只 REINFORCE，Experience State 更新但 Skill Version 不变。
2. Task B 触发 SPLIT/SUPERSEDE，产生 Candidate Version，经 Regression 后 Promote。
3. Task C 使用新 Version，AgentDecision 路径发生可解释变化。
4. UI 能从 Decision 追溯 Experience，再追溯 Task/Experiment/Evidence。
5. Replay 能使用旧 Experience Skill Version 重放历史 Task。
