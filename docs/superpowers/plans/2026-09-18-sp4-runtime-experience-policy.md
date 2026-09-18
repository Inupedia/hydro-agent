# Runtime Experience Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 让 Experience 真正进入 Agent 下一轮率定决策，形成可审计的 Experience Retrieval、Exploitation/Exploration 和 Experiment Priority。

**Architecture:** 新增 deterministic ExperienceRetriever 与 ExperiencePolicy。WorldStateBuilder 只注入当前任务适用的精简 ExperienceContext。Calibration Scientist provider 在模型诊断后、实验计划前使用 ExperiencePolicy 调整候选优先级；AgentDecision 明确记录 mode、refs 和 influence，不让 Experience 直接产生 raw parameter vector。

**Tech Stack:** Python 3.12, Pydantic 2, existing AgentRuntime/WorldState/SkillOrchestrator, pytest

**Spec:** docs/superpowers/specs/2026-09-18-experience-skill-evolution-design.md

## Global Constraints

- Experience 不能绕过 SkillOrchestrator、Experiment Guardrail 和 Gate。
- Exploration 不能是纯随机。
- 同输入 + 同 Experience Version 应稳定排序。
- Decision 审计必须记录 Experience Version/hash/refs。
- 同流域同模型经验权重大于跨流域弱先验。

---

## File Structure

- Create: src/hydro_agent/experience/retrieval.py
- Create: src/hydro_agent/experience/policy.py
- Modify: src/hydro_agent/agent/contracts.py
- Modify: src/hydro_agent/agent/world_state.py
- Modify: src/hydro_agent/agent/providers/calibration_scientist.py
- Modify: src/hydro_agent/skills/orchestration.py
- Modify: src/hydro_agent/persistence/models.py
- Modify: src/hydro_agent/persistence/repository.py
- Create: tests/experience/test_policy.py
- Modify: tests/agent/test_world_state.py
- Modify: tests/agent/test_calibration_scientist_provider.py

### Task 1: Retrieve applicable Experience deterministically

**Files:**
- Create: src/hydro_agent/experience/retrieval.py
- Test: tests/experience/test_policy.py

**Interfaces:**
- ExperienceMatch(experience_id, revision, relevance, transfer_weight, confidence, decision)
- ExperienceRetriever.retrieve(model_id, basin_id, diagnosis, limit=12)

- [ ] **Step 1: Write failing retrieval ranking test**

Create three Experience entries: same basin/model, same model/other basin, general. Assert exact order and transfer weights.

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/experience/test_policy.py -v

- [ ] **Step 3: Implement scope + pattern matcher**

Use deterministic JSON pattern matching for first version. Unknown pattern keys contribute no match rather than guessing. Stable tie-break by experience_id/revision.

- [ ] **Step 4: Verify GREEN**

Run: uv run pytest tests/experience/test_policy.py -v

- [ ] **Step 5: Commit**

~~~bash
git add src/hydro_agent/experience/retrieval.py tests/experience/test_policy.py
git commit -m "feat: retrieve applicable calibration experience"
~~~

### Task 2: Add ExperienceContext to WorldState

**Files:**
- Modify: src/hydro_agent/agent/contracts.py
- Modify: src/hydro_agent/agent/world_state.py
- Modify: tests/agent/test_world_state.py

**Interfaces:**
- Produces ExperienceContext with skill_version, skill_hash, status, matches, exploration_level.

- [ ] **Step 1: Write failing WorldState test**

Build a task with promoted Experience Skill and matching experience. Assert view.hydro.experience.skill_version and refs are populated.

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/agent/test_world_state.py -v

- [ ] **Step 3: Extend HydroContext**

Add experience: ExperienceContext using a default empty context so old callers remain compatible.

- [ ] **Step 4: Inject retriever into WorldStateBuilder**

Do not include full historical evidence payload; include compact IDs, revision, decision summary, confidence and weights.

- [ ] **Step 5: Run tests**

Run: uv run pytest tests/agent/test_world_state.py tests/agent -q

- [ ] **Step 6: Commit**

~~~bash
git add src/hydro_agent/agent/contracts.py src/hydro_agent/agent/world_state.py tests/agent/test_world_state.py
git commit -m "feat: expose experience in world state"
~~~

### Task 3: Implement dynamic Exploitation/Exploration policy

**Files:**
- Create: src/hydro_agent/experience/policy.py
- Test: tests/experience/test_policy.py

**Interfaces:**
- ExperiencePolicy.score_candidates(...)
- ExperiencePolicy.choose_mode(...)
- CandidateScore fields: experience_score, plausibility, uncertainty_bonus, novelty_bonus, failure_penalty, total.

- [ ] **Step 1: Write failing policy tests**

Assert:
- high-confidence same-basin Experience chooses exploitation;
- unfamiliar basin + low confidence increases exploration_level;
- repeatedly failed candidate receives penalty;
- same inputs produce same ordered candidates.

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/experience/test_policy.py -v

- [ ] **Step 3: Implement explainable scoring**

No random sampling. Exploration means selecting a lower-history but hydrologically plausible candidate when uncertainty/novelty bonus justifies it. Return reason codes.

- [ ] **Step 4: Run tests**

Run: uv run pytest tests/experience/test_policy.py -v

- [ ] **Step 5: Commit**

~~~bash
git add src/hydro_agent/experience/policy.py tests/experience/test_policy.py
git commit -m "feat: rank experiments with experience policy"
~~~

### Task 4: Feed Experience influence into AgentDecision and audit

**Files:**
- Modify: src/hydro_agent/agent/contracts.py
- Modify: src/hydro_agent/agent/providers/calibration_scientist.py
- Modify: src/hydro_agent/skills/orchestration.py
- Modify: src/hydro_agent/persistence/models.py
- Modify: src/hydro_agent/persistence/repository.py
- Modify: tests/agent/test_calibration_scientist_provider.py

**Interfaces:**
- AgentDecision gains experience_skill_version, experience_skill_hash, experience_refs, experience_mode, experience_influence.

- [ ] **Step 1: Write failing provider test**

Given peak-underestimation diagnosis and routing-positive Experience, assert selected plan prefers routing and decision audit references EXP-XAJ-*.

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/agent/test_calibration_scientist_provider.py -v

- [ ] **Step 3: Integrate policy after diagnosis and before experiment planning**

Pass proposed strategy/groups/objective into existing SkillOrchestrator; do not directly create parameter vectors.

- [ ] **Step 4: Persist audit fields**

AgentDecisionRun may store a single experience_audit_json object to avoid proliferating nullable columns, provided API exposes typed fields.

- [ ] **Step 5: Run focused and full agent tests**

Run: uv run pytest tests/agent tests/skills/test_orchestration.py tests/experience/test_policy.py -q

- [ ] **Step 6: Commit**

~~~bash
git add src/hydro_agent/agent src/hydro_agent/skills/orchestration.py src/hydro_agent/persistence tests/agent
git commit -m "feat: apply experience to agent decisions"
~~~
