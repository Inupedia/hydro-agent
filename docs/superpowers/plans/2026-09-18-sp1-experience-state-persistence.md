# Experience State & Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 建立跨任务共享、可修订、可追溯的结构化 Experience State 与 Skill Version 元数据持久化层。

**Architecture:** 新增 hydro_agent.experience 领域包承载 Experience 合同；SQLAlchemy 继续使用现有 persistence 模块统一建表；HydroRepository 提供追加 revision、查询 active experience、版本与 evolution event 的最小接口。Experience Revision 采用 append-only，不原地覆盖历史事实。

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy 2, SQLite, pytest

**Spec:** docs/superpowers/specs/2026-09-18-experience-skill-evolution-design.md

## Global Constraints

- 不实现用户维度。
- Experience 是 advisory knowledge。
- revision 历史必须可追溯。
- State Optimization 不自动等于 Skill Version Change。
- 所有 Evidence refs 必须保留来源 Task/Experiment/Evidence。
- SQLite 仍通过 Database.create_schema() 管理，不引入第二套数据库框架。

---

## File Structure

- Create: src/hydro_agent/experience/__init__.py — Experience 公共导出。
- Create: src/hydro_agent/experience/contracts.py — ExperienceEntry、Scope、Diff/Version 领域合同。
- Modify: src/hydro_agent/persistence/models.py — 新增 experience_revisions、experience_skill_versions、experience_evolution_events。
- Modify: src/hydro_agent/persistence/repository.py — 增加 append/query API。
- Create: tests/experience/test_contracts.py
- Create: tests/experience/test_persistence.py

### Task 1: Define Experience domain contracts

**Files:**
- Create: src/hydro_agent/experience/__init__.py
- Create: src/hydro_agent/experience/contracts.py
- Test: tests/experience/test_contracts.py

**Interfaces:**
- Produces: ExperienceScope, ExperiencePattern, ExperienceDecision, ExperienceEvidenceRef, ExperienceEntry, ExperienceStatus, ExperienceSkillVersionStatus, ExperienceEvolutionEventType.

- [ ] **Step 1: Write failing contract tests**

~~~python
from hydro_agent.experience.contracts import ExperienceEntry, ExperienceScope

def test_experience_entry_has_no_user_scope():
    entry = ExperienceEntry(
        experience_id="EXP-XAJ-0001",
        revision=1,
        category="model",
        scope=ExperienceScope(model_ids=("xaj",), basin_ids=("basin-a",)),
        pattern={"peak_bias": "negative"},
        decision={"prefer_param_groups": ["routing"]},
        supporting_evidence=(),
        contradicting_evidence=(),
        confidence=0.7,
        status="active",
    )
    assert entry.scope.model_ids == ("xaj",)
    assert not hasattr(entry.scope, "user_ids")
~~~

- [ ] **Step 2: Run the test and verify RED**

Run: uv run pytest tests/experience/test_contracts.py -v  
Expected: FAIL because hydro_agent.experience does not exist.

- [ ] **Step 3: Implement minimal immutable Pydantic contracts**

Use FrozenModel from hydro_agent.execution.contracts. Constrain confidence to 0..1 and revision >= 1. Keep pattern/decision JSON-compatible and intentionally exclude user identity.

- [ ] **Step 4: Run contract tests**

Run: uv run pytest tests/experience/test_contracts.py -v  
Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/hydro_agent/experience tests/experience/test_contracts.py
git commit -m "feat: add experience domain contracts"
~~~

### Task 2: Add append-only Experience persistence rows

**Files:**
- Modify: src/hydro_agent/persistence/models.py
- Test: tests/experience/test_persistence.py

**Interfaces:**
- Consumes: ExperienceEntry fields from Task 1.
- Produces: ExperienceRevision, ExperienceSkillVersion, ExperienceEvolutionEvent SQLAlchemy rows.

- [ ] **Step 1: Write failing schema test**

~~~python
def test_database_creates_experience_tables(database):
    database.create_schema()
    names = set(inspect(database.engine).get_table_names())
    assert "experience_revisions" in names
    assert "experience_skill_versions" in names
    assert "experience_evolution_events" in names
~~~

- [ ] **Step 2: Run test and verify RED**

Run: uv run pytest tests/experience/test_persistence.py::test_database_creates_experience_tables -v

- [ ] **Step 3: Add SQLAlchemy models**

experience_revisions must include a unique constraint on (experience_id, revision). Store scope_json, pattern_json, decision_json, supporting_evidence_json, contradicting_evidence_json, confidence, status, source_hash and created_at. Version rows store integer version, parent_version, status, skill_hash, manifest_json and regression_json. Evolution events store task_id, experience_id, event_type, from_revision, to_revision, version_before, version_after, reason and evidence_refs_json.

- [ ] **Step 4: Run persistence schema tests**

Run: uv run pytest tests/experience/test_persistence.py -v  
Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/hydro_agent/persistence/models.py tests/experience/test_persistence.py
git commit -m "feat: persist experience revisions and versions"
~~~

### Task 3: Add HydroRepository Experience APIs

**Files:**
- Modify: src/hydro_agent/persistence/repository.py
- Test: tests/experience/test_persistence.py

**Interfaces:**
- Produces:
  - append_experience_revision(entry: ExperienceEntry) -> ExperienceEntry
  - get_experience(experience_id: str, revision: int | None = None) -> ExperienceEntry
  - list_active_experiences(model_id: str | None = None, basin_id: str | None = None) -> list[ExperienceEntry]
  - create_experience_skill_version(...)
  - get_experience_skill_version(version: int)
  - get_current_experience_skill_version()
  - append_experience_evolution_event(...)

- [ ] **Step 1: Write failing repository tests**

Cover append revision 1 then 2, duplicate revision rejection, active query filtering by model/basin, and current promoted skill version selection.

- [ ] **Step 2: Run tests and verify RED**

Run: uv run pytest tests/experience/test_persistence.py -v

- [ ] **Step 3: Implement repository mapping helpers and methods**

Never UPDATE an ExperienceRevision row. A new confidence or evidence state is a new revision. SkillVersion status may transition candidate -> promoted/rejected using an explicit repository method; preserve prior promoted versions.

- [ ] **Step 4: Run tests**

Run: uv run pytest tests/experience/test_persistence.py tests/persistence -q  
Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/hydro_agent/persistence/repository.py tests/experience/test_persistence.py
git commit -m "feat: add experience repository APIs"
~~~

## Self-Review

- Spec coverage: structured state, revisions, provenance, versions and events are represented.
- Placeholder scan: no implementation step may be replaced by generic “add validation”.
- Type consistency: ExperienceEntry must be the API contract on both write and read.
