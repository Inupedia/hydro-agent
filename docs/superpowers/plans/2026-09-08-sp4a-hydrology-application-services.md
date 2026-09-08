# SP4A Hydrology Application Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the missing application boundary between business Tools and numerical runtimes so forecast/calibration capabilities are independently callable, auditable services before the Agent is connected.

**Architecture:** `SnapshotResolver` resolves/builds the exact legal DataSnapshot for a capability and issue time through SP4. `SchemeMaterializer` writes the immutable Scheme config into the action workspace input contract. `ForecastService` owns the full application transaction: create ActionRun -> build ExecutionRequest -> materialize declared inputs -> run SandboxRunner -> persist ExecutionResult/cost/artifacts -> persist immutable Forecast. `CalibrationService` performs the same execution lifecycle for SP5's bounded XAJ calibration and returns the calibration payload; candidate registration and Gate remain SP5 responsibilities.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy 2, pytest 8; SP1 SandboxRunner, SP2 HydroRepository, SP3 XajRuntimeAdapter, SP4 data policy/snapshot builder.

**Spec:** `docs/superpowers/specs/2026-09-08-execution-sandbox-design.md`

## Global Constraints

- Hydrology Tools call application services; they never invoke `SandboxRunner` or model processes directly.
- Application services create all ActionRun ids and persistence records required for audit.
- The Agent/browser never supplies shell argv, filesystem paths, or continuous XAJ parameter vectors.
- Forecast success requires a contract-valid `ExecutionResult`; failed/timed-out/contract-error runs never create a Forecast row.
- Forecast rows are immutable.
- Snapshot resolution applies SP4 F/R/phase rules before SandboxRunner launch.
- Scheme input is derived from immutable SP2 Scheme records, not caller-supplied JSON.
- Service methods are callable without an LLM.

---

## File Structure

```text
src/hydro_agent/services/__init__.py
src/hydro_agent/services/contracts.py
src/hydro_agent/services/snapshots.py
src/hydro_agent/services/materialize.py
src/hydro_agent/services/forecast.py
src/hydro_agent/services/calibration.py
src/hydro_agent/persistence/models.py
src/hydro_agent/persistence/repository.py
tests/services/test_snapshots.py
tests/services/test_materialize.py
tests/services/test_forecast.py
tests/services/test_calibration.py
```

### Task 1: Persist immutable Forecast records before Agent integration

**Files:**
- Create: `src/hydro_agent/services/__init__.py`
- Create: `src/hydro_agent/services/contracts.py`
- Modify: `src/hydro_agent/persistence/models.py`
- Modify: `src/hydro_agent/persistence/repository.py`
- Test: `tests/services/test_forecast.py`

**Interfaces:**
- Produces: `ForecastRecord`, `create_forecast()`, `get_forecast()`, `list_forecasts()`.

- [ ] **Step 1: Write the failing persistence test**

```python
# tests/services/test_forecast.py

def test_successful_forecast_record_is_immutable_and_traceable(seeded_repository):
    seeded_repository.create_forecast(
        forecast_id="fc-1",
        task_id="task-1",
        action_run_id="run-1",
        scheme_id="scheme-base",
        data_snapshot_id="snap-1",
        issue_time="2025-05-01T00:00:00Z",
        lead_values={1: 10.0, 2: 11.0, 3: 12.0},
        unit="m3/s",
        artifact_ids=("artifact-1",),
    )
    row = seeded_repository.get_forecast("fc-1")
    assert row.scheme_id == "scheme-base"
    assert row.data_snapshot_id == "snap-1"
    assert row.lead_values_json == {"1": 10.0, "2": 11.0, "3": 12.0}
    assert not hasattr(seeded_repository, "update_forecast")
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/services/test_forecast.py::test_successful_forecast_record_is_immutable_and_traceable -v`

Expected: FAIL because Forecast persistence is missing.

- [ ] **Step 3: Add exact Forecast contract/table**

```python
class ForecastRecord(FrozenModel):
    forecast_id: str
    task_id: str
    action_run_id: str
    scheme_id: str
    data_snapshot_id: str
    issue_time: datetime
    lead_values: dict[int, float]
    unit: str
    artifact_ids: tuple[str, ...]
```

Add `forecasts` columns:

```text
forecast_id PK
task_id FK
action_run_id FK unique
scheme_id FK
data_snapshot_id FK
issue_time
lead_values_json
unit
artifact_ids_json
created_at
```

Add uniqueness on `(task_id, scheme_id, issue_time)`. `create_forecast()` only accepts leads exactly `{1,2,3}`, finite values and `unit="m3/s"` for the first XAJ route.

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/services/test_forecast.py::test_successful_forecast_record_is_immutable_and_traceable -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/services src/hydro_agent/persistence tests/services/test_forecast.py
git commit -m "feat: persist immutable forecast outcomes"
```

### Task 2: Resolve one legal DataSnapshot for a requested capability/issue time

**Files:**
- Create: `src/hydro_agent/services/snapshots.py`
- Test: `tests/services/test_snapshots.py`

**Interfaces:**
- Produces: `SnapshotResolver.resolve(task_id, capability, issue_time) -> snapshot_id`.

- [ ] **Step 1: Write failing resolver tests**

```python
# tests/services/test_snapshots.py

def test_resolver_reuses_exact_existing_legal_snapshot(snapshot_resolver):
    snapshot_id = snapshot_resolver.resolve("task-1", "forecast", "2025-05-01T00:00:00Z")
    assert snapshot_id == "snap-legal-0501"


def test_resolver_never_falls_back_to_later_f_mode_snapshot(f_snapshot_resolver):
    with pytest.raises(DataAccessViolation, match="no legal forcing"):
        f_snapshot_resolver.resolve("task-1", "forecast", "2025-05-01T00:00:00Z")
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/services/test_snapshots.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement resolver**

Resolution order:

1. load Task phase/forcing mode/basin;
2. search persisted snapshots whose manifest context exactly matches task, basin, phase, forcing mode, capability and issue time;
3. if exactly one exists, return it after content-hash verification;
4. if none exists and normalized source rows are configured, build one using SP4 `SnapshotBuilder` with a deterministic snapshot id;
5. if no legal forcing exists, propagate `DataAccessViolation`;
6. never select a newer snapshot merely because it contains the requested target dates.

Deterministic id:

```text
{task_id}--{capability}--{issue_time:%Y%m%dT%H%M%SZ}
```

- [ ] **Step 4: Run resolver tests**

Run: `uv run pytest tests/services/test_snapshots.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/services/snapshots.py tests/services/test_snapshots.py
git commit -m "feat: resolve legal execution snapshots"
```

### Task 3: Materialize Scheme and Snapshot references into a Sandbox workspace

**Files:**
- Create: `src/hydro_agent/services/materialize.py`
- Test: `tests/services/test_materialize.py`

**Interfaces:**
- Produces: `ExecutionInputMaterializer.materialize(request, workspace) -> None`.

- [ ] **Step 1: Write failing source-of-truth test**

```python
# tests/services/test_materialize.py
import json


def test_scheme_materialization_comes_from_repository_not_caller(materializer, workspace, request):
    materializer.materialize(request, workspace)
    scheme = json.loads((workspace / "input/scheme/scheme.json").read_text())
    assert scheme["scheme_id"] == request.scheme_id
    assert scheme["parameters"]["K"] == 0.75
```

Add a hash test proving the copied snapshot files match SP2 manifest SHA-256 values.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/services/test_materialize.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement materialization**

`ExecutionInputMaterializer` loads `Scheme.config_json` and DataSnapshot manifest/path metadata from trusted repository/storage services. Write canonical `input/scheme/scheme.json`; copy only manifest-declared snapshot files under `input/snapshot/`; verify every SHA-256 before execution; then set input files read-only.

The method rejects any resolved file outside configured snapshot storage root.

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/services/test_materialize.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/services/materialize.py tests/services/test_materialize.py
git commit -m "feat: materialize trusted sandbox inputs"
```

### Task 4: Implement independently callable ForecastService

**Files:**
- Create: `src/hydro_agent/services/forecast.py`
- Modify: `tests/services/test_forecast.py`

**Interfaces:**
- Produces:

```python
ForecastService.forecast(
    *, task_id: str, scheme_id: str, issue_time: str,
    policy: ExecutionPolicy
) -> ForecastRecord
```

- [ ] **Step 1: Write failing service lifecycle test**

```python

def test_forecast_service_owns_full_audited_execution(forecast_service, repository):
    forecast = forecast_service.forecast(
        task_id="task-1",
        scheme_id="scheme-base",
        issue_time="2025-05-01T00:00:00Z",
        policy=cpu_policy,
    )
    action = repository.get_action_run(forecast.action_run_id)
    assert action.capability == "forecast"
    assert action.status == "succeeded"
    assert repository.get_cost(action.action_run_id).wall_time_seconds >= 0
    assert repository.get_forecast(forecast.forecast_id).scheme_id == "scheme-base"
```

Add failure test: fake SandboxRunner returns `timed_out`; ActionRun/cost/log artifacts persist, but `list_forecasts()` remains empty.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/services/test_forecast.py -k 'service' -v`

Expected: FAIL.

- [ ] **Step 3: Implement exact orchestration**

```text
SnapshotResolver.resolve
-> repository.create_action_run(capability=forecast)
-> repository.build_execution_request
-> WorkspaceManager.create
-> ExecutionInputMaterializer.materialize
-> SandboxRunner.run
-> repository.record_execution_result
-> if status != succeeded: raise ForecastExecutionFailed
-> validate result_payload leads/unit/ids
-> repository.create_forecast
-> return ForecastRecord
```

ActionRun id may be UUIDv7 or another application-generated unique id; it is never LLM-supplied.

- [ ] **Step 4: Run forecast service tests**

Run: `uv run pytest tests/services/test_forecast.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/services/forecast.py tests/services/test_forecast.py
git commit -m "feat: add audited forecast application service"
```

### Task 5: Implement CalibrationService execution lifecycle for SP5

**Files:**
- Create: `src/hydro_agent/services/calibration.py`
- Test: `tests/services/test_calibration.py`

**Interfaces:**
- Produces:

```python
CalibrationService.calibrate(
    *, task_id: str, base_scheme_id: str,
    calibration_snapshot_id: str,
    validation_snapshot_id: str,
    strategy_id: str,
    policy: ExecutionPolicy
) -> CalibrationOutcome
```

- [ ] **Step 1: Write failing calibration boundary test**

```python
# tests/services/test_calibration.py

def test_calibration_service_returns_payload_without_registering_candidate(calibration_service, repository):
    outcome = calibration_service.calibrate(
        task_id="task-1",
        base_scheme_id="scheme-base",
        calibration_snapshot_id="snap-cal",
        validation_snapshot_id="snap-val",
        strategy_id="xaj-bounded-v1",
        policy=cpu_policy,
    )
    assert outcome.action_run_id
    assert outcome.strategy_id == "xaj-bounded-v1"
    assert outcome.candidate_parameters
    assert repository.list_schemes(status="candidate") == []
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/services/test_calibration.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement application execution only**

`CalibrationService` verifies the named snapshots belong to the Task and are phase-legal, creates a `calibrate` ActionRun, executes SP5's XAJ calibration runtime through the same materializer/SandboxRunner path, persists terminal result/cost/artifacts, and returns a frozen `CalibrationOutcome` containing action id, strategy id, base scheme id, candidate parameter payload and artifact ids.

It must not call `CandidateSchemeService` or `GateEvaluator`; SP5 owns those decisions.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/services/test_calibration.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/services/calibration.py tests/services/test_calibration.py
git commit -m "feat: add audited calibration application service"
```

## SP4A Acceptance

```bash
uv run pytest tests/services -v
```

Acceptance requires forecast and calibration to be callable without an Agent, all numerical execution to pass through SandboxRunner, legal snapshots and immutable Scheme inputs to be materialized from trusted records, successful Forecast persistence, and no Forecast promotion on failed/timed-out/contract-error runs.