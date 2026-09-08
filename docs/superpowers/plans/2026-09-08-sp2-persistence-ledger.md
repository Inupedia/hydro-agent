# SP2 Task, Scheme, Snapshot, ActionRun Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the minimum Hydro-Agent domain records needed to construct an `ExecutionRequest`, prove exactly which immutable inputs were used, and save execution/artifact/cost outcomes for later WorldState and audit views.

**Architecture:** Use synchronous SQLAlchemy 2 with SQLite for the first milestone. Domain rows store stable identifiers and immutable hashes; JSON columns hold bounded configuration payloads. A repository layer owns creation and terminal-state transitions so sandbox code never writes SQL directly.

**Tech Stack:** Python 3.12, SQLAlchemy 2, SQLite, Pydantic 2, pytest 8.

**Spec:** `docs/superpowers/specs/2026-09-08-execution-sandbox-design.md`

## Global Constraints

- SQLite + local filesystem metadata is sufficient for milestone 1.
- Registered `Scheme` and `DataSnapshot` records are immutable after creation.
- Every numerical run has one unique `action_run_id`.
- Cost must persist wall time and peak memory.
- Failed/timed-out/contract-error runs may persist diagnostic artifacts but may not register a successful Forecast or candidate Scheme.
- No Alembic migration framework is required before the schema stabilizes; tests create a fresh database from metadata.

---

## File Structure

```text
pyproject.toml
src/hydro_agent/persistence/__init__.py
src/hydro_agent/persistence/database.py
src/hydro_agent/persistence/models.py
src/hydro_agent/persistence/repository.py
src/hydro_agent/persistence/schemas.py
tests/persistence/test_database.py
tests/persistence/test_repository.py
```

### Task 1: Add SQLAlchemy and create the database/session boundary

**Files:**
- Modify: `pyproject.toml`
- Create: `src/hydro_agent/persistence/__init__.py`
- Create: `src/hydro_agent/persistence/database.py`
- Test: `tests/persistence/test_database.py`

**Interfaces:**
- Consumes: none beyond SP1 package skeleton.
- Produces: `Database(url)`, `Database.create_schema()`, `Database.session()`.

- [ ] **Step 1: Write the failing database test**

```python
# tests/persistence/test_database.py
from sqlalchemy import text
from hydro_agent.persistence.database import Database


def test_database_opens_sqlite_session(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path / 'hydro.db'}")
    with db.session() as session:
        assert session.execute(text("select 1")).scalar_one() == 1
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/persistence/test_database.py -v`

Expected: FAIL because persistence package is missing.

- [ ] **Step 3: Add dependency and minimal database class**

Add to `pyproject.toml` dependencies:

```toml
"sqlalchemy>=2.0,<3",
```

```python
# src/hydro_agent/persistence/database.py
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_engine(url, future=True)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self):
        session: Session = self._sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
```

- [ ] **Step 4: Run test**

Run: `uv sync --extra dev && uv run pytest tests/persistence/test_database.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/hydro_agent/persistence tests/persistence/test_database.py
git commit -m "feat: add sqlite persistence boundary"
```

### Task 2: Define Task, Scheme, DataSnapshot, ActionRun, Artifact, and Cost rows

**Files:**
- Create: `src/hydro_agent/persistence/models.py`
- Create: `src/hydro_agent/persistence/schemas.py`
- Modify: `tests/persistence/test_database.py`

**Interfaces:**
- Produces tables: `tasks`, `schemes`, `data_snapshots`, `action_runs`, `artifacts`, `cost_ledger`.
- Produces Pydantic inputs: `TaskCreate`, `SchemeCreate`, `DataSnapshotCreate`.

- [ ] **Step 1: Write failing schema/table test**

```python
from sqlalchemy import inspect


def test_required_tables_are_created(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path / 'hydro.db'}")
    import hydro_agent.persistence.models  # noqa: F401
    db.create_schema()
    names = set(inspect(db.engine).get_table_names())
    assert {"tasks", "schemes", "data_snapshots", "action_runs", "artifacts", "cost_ledger"} <= names
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/persistence/test_database.py::test_required_tables_are_created -v`

Expected: FAIL because models do not exist.

- [ ] **Step 3: Implement exact row fields**

Use SQLAlchemy typed mappings with these required columns:

```text
tasks:
  task_id PK, basin_id, phase, forcing_mode, terminal_status nullable, created_at

schemes:
  scheme_id PK, task_id FK, model_id, status, config_json, content_hash, created_at

data_snapshots:
  snapshot_id PK, task_id FK, source, available_at nullable, manifest_json, content_hash, created_at

action_runs:
  action_run_id PK, task_id FK, model_id, capability, data_snapshot_id FK,
  scheme_id FK, issue_time nullable, status, error_code nullable, created_at, finished_at nullable

artifacts:
  artifact_id PK, action_run_id FK, kind, relative_path, sha256, bytes, promoted, created_at

cost_ledger:
  action_run_id PK/FK, wall_time_seconds, peak_memory_bytes nullable
```

Use `JSON` for `config_json` and `manifest_json`; use UTC-aware `DateTime(timezone=True)` fields.

Create Pydantic schemas with `extra="forbid"` for Task/Scheme/Snapshot creation.

- [ ] **Step 4: Run table tests**

Run: `uv run pytest tests/persistence/test_database.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/persistence/models.py src/hydro_agent/persistence/schemas.py tests/persistence/test_database.py
git commit -m "feat: define hydro execution ledger schema"
```

### Task 3: Create immutable Task/Scheme/Snapshot repository methods

**Files:**
- Create: `src/hydro_agent/persistence/repository.py`
- Test: `tests/persistence/test_repository.py`

**Interfaces:**
- Produces: `HydroRepository.create_task()`, `create_scheme()`, `create_snapshot()`, `get_scheme()`, `get_snapshot()`.

- [ ] **Step 1: Write failing creation/immutability tests**

```python
# tests/persistence/test_repository.py
import pytest
from sqlalchemy import update

from hydro_agent.persistence.repository import HydroRepository


def test_scheme_and_snapshot_can_be_created_and_read(repository):
    repository.create_task(task_id="task-1", basin_id="13235000", phase="B", forcing_mode="F")
    scheme = repository.create_scheme(
        scheme_id="scheme-1",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={"warmup_days": 365},
        content_hash="abc",
    )
    snapshot = repository.create_snapshot(
        snapshot_id="snap-1",
        task_id="task-1",
        source="caravan",
        available_at="2026-01-01T00:00:00Z",
        manifest={"files": []},
        content_hash="def",
    )
    assert repository.get_scheme("scheme-1").content_hash == "abc"
    assert repository.get_snapshot("snap-1").content_hash == "def"


def test_repository_has_no_update_scheme_method(repository):
    assert not hasattr(repository, "update_scheme")
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/persistence/test_repository.py -k 'scheme or snapshot' -v`

Expected: FAIL because `HydroRepository` is missing.

- [ ] **Step 3: Implement repository creation methods**

```python
class HydroRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_task(self, *, task_id: str, basin_id: str, phase: str, forcing_mode: str): ...
    def create_scheme(self, *, scheme_id: str, task_id: str, model_id: str, status: str,
                      config: dict[str, object], content_hash: str): ...
    def create_snapshot(self, *, snapshot_id: str, task_id: str, source: str,
                        available_at: str | None, manifest: dict[str, object],
                        content_hash: str): ...
    def get_scheme(self, scheme_id: str): ...
    def get_snapshot(self, snapshot_id: str): ...
```

Each create method must use `session.add()` and allow primary-key/foreign-key errors to propagate; do not implement mutation methods for Scheme or DataSnapshot.

- [ ] **Step 4: Run repository tests**

Run: `uv run pytest tests/persistence/test_repository.py -k 'scheme or snapshot' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/persistence/repository.py tests/persistence/test_repository.py
git commit -m "feat: persist immutable task inputs"
```

### Task 4: Persist ActionRun lifecycle and build ExecutionRequest from records

**Files:**
- Modify: `src/hydro_agent/persistence/repository.py`
- Modify: `tests/persistence/test_repository.py`

**Interfaces:**
- Consumes: SP1 `ExecutionPolicy`, `ExecutionRequest`.
- Produces: `create_action_run(...)`, `build_execution_request(action_run_id, parameters, policy)`.

- [ ] **Step 1: Write failing request-construction test**

```python
from hydro_agent.execution.contracts import ExecutionPolicy


def test_repository_builds_execution_request_from_immutable_refs(seeded_repository):
    seeded_repository.create_action_run(
        action_run_id="run-1",
        task_id="task-1",
        model_id="xaj",
        capability="forecast",
        data_snapshot_id="snap-1",
        scheme_id="scheme-1",
        issue_time="2026-01-01T00:00:00Z",
    )
    request = seeded_repository.build_execution_request(
        "run-1",
        parameters={"lead_days": [1, 2, 3]},
        policy=ExecutionPolicy(timeout_seconds=120, network_access=False, max_output_bytes=10_000_000, device="cpu"),
    )
    assert request.scheme_id == "scheme-1"
    assert request.data_snapshot_id == "snap-1"
    assert request.capability == "forecast"
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/persistence/test_repository.py::test_repository_builds_execution_request_from_immutable_refs -v`

Expected: FAIL.

- [ ] **Step 3: Implement lifecycle creation and request building**

`create_action_run()` inserts status `pending`. `build_execution_request()` joins ActionRun, Scheme, and DataSnapshot by their IDs and constructs the SP1 Pydantic request without copying arbitrary filesystem paths into the request.

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/persistence/test_repository.py::test_repository_builds_execution_request_from_immutable_refs -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/persistence/repository.py tests/persistence/test_repository.py
git commit -m "feat: build sandbox requests from ledger records"
```

### Task 5: Persist terminal ExecutionResult, artifacts, and CostLedger atomically

**Files:**
- Modify: `src/hydro_agent/persistence/repository.py`
- Modify: `tests/persistence/test_repository.py`

**Interfaces:**
- Consumes: SP1 `ExecutionResult` plus artifact metadata `{kind, relative_path, sha256, bytes, promoted}`.
- Produces: `record_execution_result(result, artifacts)`.

- [ ] **Step 1: Write failing terminal-result test**

```python
from hydro_agent.execution.contracts import ExecutionResult


def test_terminal_result_persists_status_artifacts_and_cost(seeded_action_repository):
    result = ExecutionResult(
        action_run_id="run-1",
        status="succeeded",
        exit_code=0,
        wall_time_seconds=1.25,
        peak_memory_bytes=4096,
        stdout_artifact="logs/stdout.log",
        stderr_artifact="logs/stderr.log",
        output_artifacts=("output/result.json",),
        result_payload={"lead_values": [1.0, 2.0, 3.0]},
        error_code=None,
    )
    seeded_action_repository.record_execution_result(
        result,
        artifacts=[{"artifact_id": "a1", "kind": "result", "relative_path": "output/result.json", "sha256": "abc", "bytes": 100, "promoted": True}],
    )
    action = seeded_action_repository.get_action_run("run-1")
    assert action.status == "succeeded"
    assert seeded_action_repository.get_cost("run-1").wall_time_seconds == 1.25
    assert seeded_action_repository.list_artifacts("run-1")[0].sha256 == "abc"
```

Add a second test where `status="failed"` and output artifact `promoted=True`; repository must raise `ValueError("failed run cannot promote output artifacts")`.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/persistence/test_repository.py -k 'terminal_result or promote' -v`

Expected: FAIL.

- [ ] **Step 3: Implement atomic terminal write**

Within one database session:

1. load ActionRun and ensure it is still `pending` or `running`;
2. set terminal `status`, `error_code`, and `finished_at`;
3. insert one CostLedger row;
4. insert artifact rows;
5. reject `promoted=True` for any non-`succeeded` result;
6. commit once at context-manager exit.

- [ ] **Step 4: Run all persistence tests**

Run: `uv run pytest tests/persistence -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/persistence/repository.py tests/persistence/test_repository.py
git commit -m "feat: persist execution result ledger"
```

## SP2 Acceptance

Run:

```bash
uv run pytest tests/persistence -v
```

Acceptance requires immutable Scheme/Snapshot creation, request construction from stable IDs, one ActionRun lifecycle, and atomic terminal persistence of status, artifacts, wall time, and peak memory.