# Experience Regression & Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 为 Experience Skill Candidate 建立代表性 Regression Set、Hard Case Pool 与自动 Promotion Gate，确保 Agent 自主升级不会污染后续任务。

**Architecture:** 复用现有 replay.freeze/planner/service 能力，不实现第二套 Replay 引擎。ExperienceRegressionService 选择代表性 historical tasks，分别用 current 与 candidate Experience Skill Snapshot replay，生成结构化比较结果。PromotionGate 只消费比较结果并给出 pass/reject reasons。

**Tech Stack:** Python 3.12, existing hydro_agent.replay, pytest

**Spec:** docs/superpowers/specs/2026-09-18-experience-skill-evolution-design.md

## Global Constraints

- Candidate 不能未经 Regression 直接 Promote。
- Hard Case 不得静默退化。
- Regression 结果必须保存到 ExperienceSkillVersion。
- 不要求第一版设计单一复杂总分；使用可解释 Gate。
- Replay 必须固定数据和 Skill Snapshot，避免比较条件漂移。

---

## File Structure

- Create: src/hydro_agent/experience/regression.py
- Create: src/hydro_agent/experience/promotion.py
- Modify: src/hydro_agent/replay/contracts.py
- Modify: src/hydro_agent/replay/service.py
- Modify: src/hydro_agent/persistence/models.py
- Modify: src/hydro_agent/persistence/repository.py
- Create: tests/experience/test_regression.py
- Modify: tests/replay/test_service.py

### Task 1: Define Experience Regression Set and Hard Case selection

**Files:**
- Create: src/hydro_agent/experience/regression.py
- Test: tests/experience/test_regression.py

**Interfaces:**
- RegressionCase(task_id, tags, hard_case, baseline_version)
- ExperienceRegressionSet(cases)
- ExperienceRegressionSelector.select(repository, limit_per_tag=2)

- [ ] **Step 1: Write failing selection test**

Seed historical tasks tagged by diagnosis categories and hard-case marker. Assert at least one representative case per available tag and all hard cases are included before ordinary cases.

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/experience/test_regression.py -v

- [ ] **Step 3: Implement deterministic selector**

Supported tags include peak-under, peak-over, timing-early, timing-late, volume-bias, low-flow, high-flow and basin:<id>. Stable ordering by hard_case desc then task_id.

- [ ] **Step 4: Run tests**

Run: uv run pytest tests/experience/test_regression.py -v

- [ ] **Step 5: Commit**

~~~bash
git add src/hydro_agent/experience/regression.py tests/experience/test_regression.py
git commit -m "feat: select experience regression cases"
~~~

### Task 2: Replay current vs candidate Experience Skill

**Files:**
- Modify: src/hydro_agent/replay/contracts.py
- Modify: src/hydro_agent/replay/service.py
- Modify: src/hydro_agent/experience/regression.py
- Modify: tests/replay/test_service.py
- Modify: tests/experience/test_regression.py

**Interfaces:**
- ExperienceRegressionService.compare(current_version, candidate_version, cases) -> RegressionComparison.

- [ ] **Step 1: Write failing replay comparison test**

Use scripted replay outcomes where candidate reduces repeated failed experiments in one case and regresses a hard case in another. Assert both per-case deltas are preserved.

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/experience/test_regression.py tests/replay/test_service.py -v

- [ ] **Step 3: Add Experience Skill override to replay context**

Replay must materialize the requested historical/candidate Experience package into the Skill snapshot used by the runtime without mutating global current/.

- [ ] **Step 4: Compute comparable outputs**

At minimum compare terminal status, optimization cycle count, repeated experiment signatures, accepted scheme metrics and guardrail/gate violations.

- [ ] **Step 5: Run tests**

Run: uv run pytest tests/replay tests/experience/test_regression.py -q

- [ ] **Step 6: Commit**

~~~bash
git add src/hydro_agent/replay src/hydro_agent/experience/regression.py tests/replay tests/experience/test_regression.py
git commit -m "feat: replay experience skill candidates"
~~~

### Task 3: Implement Promotion Gate and lifecycle

**Files:**
- Create: src/hydro_agent/experience/promotion.py
- Modify: src/hydro_agent/experience/skill_versions.py
- Modify: src/hydro_agent/persistence/repository.py
- Test: tests/experience/test_regression.py

**Interfaces:**
- PromotionGate.evaluate(comparison) -> PromotionDecision(accepted, reasons)
- ExperiencePromotionService.validate_and_promote(candidate_version)

- [ ] **Step 1: Write failing gate tests**

Reject when:
- any hard case changes from success to failure;
- constraint/gate violations increase;
- accepted validation metric degrades beyond configured tolerance.

Accept when repeated failures drop and quality is non-degrading.

- [ ] **Step 2: Verify RED**

Run: uv run pytest tests/experience/test_regression.py -v

- [ ] **Step 3: Implement explicit Gate reasons**

Reason codes examples: HARD_CASE_REGRESSION, QUALITY_REGRESSION, NEW_GUARDRAIL_VIOLATION, REPEATED_FAILURE_REDUCTION, NON_DEGRADING.

- [ ] **Step 4: Wire lifecycle**

On pass: version candidate -> promoted, old promoted -> superseded, atomically update current. On fail: candidate -> rejected and append evolution event.

- [ ] **Step 5: Run tests**

Run: uv run pytest tests/experience/test_regression.py tests/experience/test_skill_compiler.py -q

- [ ] **Step 6: Commit**

~~~bash
git add src/hydro_agent/experience src/hydro_agent/persistence/repository.py tests/experience
git commit -m "feat: gate experience skill promotion"
~~~
