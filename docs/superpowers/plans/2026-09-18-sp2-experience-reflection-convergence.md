# Experience Reflection & Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 在完整率定 Task 结束后生成结构化 Experience Diff，安全应用状态变化，并根据结构变化频率计算 learning / converging / converged / reopened。

**Architecture:** Reflection 分成“Provider 产生候选 Diff”和“Deterministic Validator/Applier 应用 Diff”两层。LLM 不直接写数据库或 SKILL.md。Convergence 只观察已持久化 Evolution Events，结构操作与非结构操作分开计数。

**Tech Stack:** Python 3.12, Pydantic 2, pytest

**Spec:** docs/superpowers/specs/2026-09-18-experience-skill-evolution-design.md

## Global Constraints

- Reflection 输出仅允许 KEEP/REINFORCE/WEAKEN/CREATE/MERGE/SPLIT/SUPERSEDE/REJECT。
- REINFORCE/WEAKEN 默认只产生 Experience State 新 revision，不触发 Skill Candidate。
- CREATE/MERGE/SPLIT/SUPERSEDE 属于 structural change。
- Provider 不能绕过 deterministic validation。
- Converged 可被强反例 reopened。

---

## File Structure

- Create: src/hydro_agent/experience/reflection.py
- Create: src/hydro_agent/experience/diff.py
- Create: src/hydro_agent/experience/convergence.py
- Create: tests/experience/test_reflection.py
- Create: tests/experience/test_convergence.py

### Task 1: Define and validate Experience Diff

**Files:**
- Create: src/hydro_agent/experience/diff.py
- Test: tests/experience/test_reflection.py

**Interfaces:**
- Produces: ExperienceDiffOperation, ExperienceDiff, is_structural_change(diff).

- [ ] **Step 1: Write failing tests**

~~~python
def test_reinforce_is_not_structural():
    diff = ExperienceDiff(operation="REINFORCE", experience_id="EXP-XAJ-1")
    assert is_structural_change(diff) is False

def test_split_is_structural():
    diff = ExperienceDiff(operation="SPLIT", experience_id="EXP-XAJ-1", proposals=(...))
    assert is_structural_change(diff) is True
~~~

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/experience/test_reflection.py -v

- [ ] **Step 3: Implement contracts and operation-specific validation**

CREATE requires one proposal; MERGE requires >=2 source IDs and one proposal; SPLIT requires one source and >=2 proposals; SUPERSEDE requires source and replacement; REINFORCE/WEAKEN require evidence refs.

- [ ] **Step 4: Verify GREEN**

Run: uv run pytest tests/experience/test_reflection.py -v

- [ ] **Step 5: Commit**

~~~bash
git add src/hydro_agent/experience/diff.py tests/experience/test_reflection.py
git commit -m "feat: define structured experience diffs"
~~~

### Task 2: Build reflection engine and deterministic applier

**Files:**
- Create: src/hydro_agent/experience/reflection.py
- Modify: src/hydro_agent/experience/__init__.py
- Test: tests/experience/test_reflection.py

**Interfaces:**
- Produces:
  - ExperienceReflectionInput
  - ExperienceReflectionProvider protocol
  - ExperienceReflectionEngine.reflect(task_id) -> ReflectionResult
  - ExperienceDiffApplier.apply(task_id, diffs) -> ApplyResult

- [ ] **Step 1: Write failing tests with a ScriptedReflectionProvider**

The scripted provider returns REINFORCE for an active rule and SPLIT for another. Assert that REINFORCE creates a new revision with more evidence while SPLIT supersedes the old rule and creates two children.

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/experience/test_reflection.py -v

- [ ] **Step 3: Implement reflection input collection**

Collect task, decisions, evidence, experiment history and current applicable Experience from repository. Keep the provider interface pure: it returns candidate diffs only.

- [ ] **Step 4: Implement deterministic applier**

Apply operations transactionally through HydroRepository. Append ExperienceEvolutionEvent for every accepted diff. Return structural_change=True only if at least one accepted structural op exists.

- [ ] **Step 5: Run tests**

Run: uv run pytest tests/experience/test_reflection.py -v

- [ ] **Step 6: Commit**

~~~bash
git add src/hydro_agent/experience/reflection.py src/hydro_agent/experience/__init__.py tests/experience/test_reflection.py
git commit -m "feat: apply task experience reflection"
~~~

### Task 3: Implement convergence state machine

**Files:**
- Create: src/hydro_agent/experience/convergence.py
- Test: tests/experience/test_convergence.py

**Interfaces:**
- Produces: ExperienceConvergenceStatus, ConvergenceSummary, compute_convergence(events, window=10).

- [ ] **Step 1: Write failing state transition tests**

Cover:
- many structural events -> learning;
- mostly KEEP/REINFORCE/WEAKEN -> converging;
- two consecutive quiet windows -> converged;
- structural change after converged -> reopened.

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/experience/test_convergence.py -v

- [ ] **Step 3: Implement explainable window rules**

Do not create a black-box score. Return counts for structural and non-structural operations plus a reason string so UI can explain the state.

- [ ] **Step 4: Run tests**

Run: uv run pytest tests/experience/test_convergence.py -v

- [ ] **Step 5: Commit**

~~~bash
git add src/hydro_agent/experience/convergence.py tests/experience/test_convergence.py
git commit -m "feat: track experience convergence"
~~~
