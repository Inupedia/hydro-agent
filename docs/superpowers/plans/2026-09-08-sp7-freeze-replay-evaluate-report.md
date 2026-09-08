# SP7 Freeze, Historical Replay, Read-Only Evaluation, and Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze one accepted/kept Scheme into an immutable operational package, replay sequential historical issue times without changing that package, evaluate the replay only in E phase using evaluation-only observations, and generate traceable metrics/report artifacts.

**Architecture:** `FreezeService` creates a new immutable frozen Scheme record instead of mutating an existing Scheme. `ReplayPlanner` expands a date range into issue-time cases and delegates snapshot legality to SP4A `SnapshotResolver`. `ReplayService` calls SP4A `ForecastService` for every case, so each replay forecast uses the same audited Tool -> ActionRun -> Sandbox path as a single forecast. `EvaluationService` switches to read-only E-phase data access, computes metrics through SP5 evaluation functions, and writes JSON/Markdown report artifacts. A10/A11/A12 become real ToolRouter handlers only after these services exist.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy 2, NumPy, pytest 8; SP2 persistence, SP4A ForecastService/SnapshotResolver, SP5 metrics/Gate contracts, SP6 ToolRouter.

**Spec:** `docs/superpowers/specs/2026-09-08-execution-sandbox-design.md`

## Global Constraints

- A frozen Scheme is immutable; freezing creates a new Scheme record and never changes the source Scheme row.
- F-phase replay uses the same frozen Scheme for every issue time.
- No A07 optimization is allowed in F or E phase.
- For F mode, every runtime input must satisfy `available_at <= issue_time`; future observed discharge is forbidden during replay.
- Future observed discharge becomes visible only to the read-only E-phase evaluator.
- Replay is sequential and deterministic for the first milestone; no distributed scheduler is introduced.
- Evaluation never writes model parameters, Scheme config, or replay Forecast values.
- Every Forecast and report must trace to `task_id`, frozen `scheme_id`, `data_snapshot_id`, `issue_time`, and artifact hashes.
- Report generation is deterministic application code; the LLM may summarize later but does not calculate metrics.

---

## File Structure

```text
src/hydro_agent/replay/__init__.py
src/hydro_agent/replay/contracts.py
src/hydro_agent/replay/freeze.py
src/hydro_agent/replay/planner.py
src/hydro_agent/replay/service.py
src/hydro_agent/evaluation/metrics.py
src/hydro_agent/evaluation/service.py
src/hydro_agent/reporting/__init__.py
src/hydro_agent/reporting/report.py
src/hydro_agent/persistence/repository.py
src/hydro_agent/agent/tools.py
tests/replay/test_freeze.py
tests/replay/test_planner.py
tests/replay/test_service.py
tests/evaluation/test_service.py
tests/reporting/test_report.py
tests/integration/test_frozen_historical_replay.py
```

### Task 1: Define replay contracts and enforce replay Forecast uniqueness

**Files:**
- Create: `src/hydro_agent/replay/__init__.py`
- Create: `src/hydro_agent/replay/contracts.py`
- Modify: `src/hydro_agent/persistence/repository.py`
- Test: `tests/replay/test_service.py`

**Interfaces:**
- Consumes: SP4A `ForecastRecord` and `list_forecasts()`.
- Produces: `ReplayCase`, `ReplayPlan`, `repository.get_forecast_for_issue(task_id, scheme_id, issue_time)`.

- [ ] **Step 1: Write the failing replay lookup test**

```python
# tests/replay/test_service.py

def test_replay_lookup_returns_exact_existing_forecast(seeded_repository):
    seeded_repository.create_forecast(
        forecast_id="fc-1",
        task_id="task-1",
        action_run_id="run-forecast-1",
        scheme_id="scheme-frozen-1",
        data_snapshot_id="snapshot-issue-1",
        issue_time="2025-05-01T00:00:00Z",
        lead_values={1: 10.0, 2: 11.0, 3: 12.0},
        unit="m3/s",
        artifact_ids=("artifact-forecast-1",),
    )
    row = seeded_repository.get_forecast_for_issue(
        "task-1", "scheme-frozen-1", "2025-05-01T00:00:00Z"
    )
    assert row.forecast_id == "fc-1"
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/replay/test_service.py::test_replay_lookup_returns_exact_existing_forecast -v`

Expected: FAIL because replay contracts/lookup do not exist.

- [ ] **Step 3: Implement exact replay contracts**

```python
# src/hydro_agent/replay/contracts.py
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReplayCase(FrozenModel):
    issue_time: datetime
    data_snapshot_id: str


class ReplayPlan(FrozenModel):
    task_id: str
    scheme_id: str
    forcing_mode: Literal["R", "F"]
    cases: tuple[ReplayCase, ...]
```

Add repository lookup using the SP4A Forecast uniqueness key `(task_id, scheme_id, issue_time)`. Return `None` when absent and raise if database corruption yields more than one row.

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/replay/test_service.py::test_replay_lookup_returns_exact_existing_forecast -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/replay src/hydro_agent/persistence/repository.py tests/replay/test_service.py
git commit -m "feat: define replay cases and forecast lookup"
```

### Task 2: Freeze the selected Scheme by creating a new immutable frozen Scheme

**Files:**
- Create: `src/hydro_agent/replay/freeze.py`
- Test: `tests/replay/test_freeze.py`

**Interfaces:**
- Consumes: source Scheme, Task state, Gate policy/decision, preprocessing config and budget summary.
- Produces: `FreezeService.freeze(task_id, source_scheme_id, gate_decision_id=None) -> frozen_scheme_id`.

- [ ] **Step 1: Write failing freeze immutability test**

```python
# tests/replay/test_freeze.py

def test_freeze_creates_new_scheme_without_mutating_source(seeded_repository, freeze_service):
    before = seeded_repository.get_scheme("scheme-base").content_hash
    frozen_id = freeze_service.freeze(
        task_id="task-1",
        source_scheme_id="scheme-base",
        gate_decision_id=None,
    )
    source = seeded_repository.get_scheme("scheme-base")
    frozen = seeded_repository.get_scheme(frozen_id)
    assert source.content_hash == before
    assert frozen.scheme_id != source.scheme_id
    assert frozen.status == "frozen"
    assert frozen.config_json["provenance"]["source_scheme_id"] == "scheme-base"
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/replay/test_freeze.py -v`

Expected: FAIL because `FreezeService` is missing.

- [ ] **Step 3: Implement exact freeze behavior**

Frozen id format:

```text
{source_scheme_id}--frozen--{task_id}
```

Construct frozen config by canonical deep copy of source config plus provenance and a `freeze_contract` containing the already-configured `model_id`, lead 1/2/3, forcing mode, preprocessing version, warmup, Gate policy reference, and budget summary. Do not invent missing values; required missing keys raise `ValueError("scheme cannot be frozen: missing <field>")`.

Canonical-JSON hash the frozen config and call `create_scheme(status="frozen")`. Update only `task_state.current_scheme_id` to the new frozen id; never mutate the source Scheme.

- [ ] **Step 4: Run freeze tests**

Run: `uv run pytest tests/replay/test_freeze.py -v`

Expected: PASS, including a missing-metadata rejection test.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/replay/freeze.py tests/replay/test_freeze.py
git commit -m "feat: freeze immutable forecast schemes"
```

### Task 3: Build sequential replay cases from issue times and legal snapshots

**Files:**
- Create: `src/hydro_agent/replay/planner.py`
- Test: `tests/replay/test_planner.py`

**Interfaces:**
- Consumes: Task forcing mode, frozen Scheme, date range, SP4A `SnapshotResolver.resolve()`.
- Produces: `ReplayPlanner.plan(task_id, start_date, end_date) -> ReplayPlan`.

- [ ] **Step 1: Write failing F-mode planner test**

```python
# tests/replay/test_planner.py
from datetime import date
import pytest


def test_f_mode_plan_uses_only_snapshot_available_by_each_issue_time(replay_planner):
    plan = replay_planner.plan("task-1", date(2025, 5, 1), date(2025, 5, 3))
    assert [case.issue_time.date().isoformat() for case in plan.cases] == [
        "2025-05-01", "2025-05-02", "2025-05-03"
    ]
    assert [case.data_snapshot_id for case in plan.cases] == ["snap-0501", "snap-0502", "snap-0503"]


def test_f_mode_plan_rejects_day_without_legal_forecast_snapshot(replay_planner_missing_day):
    with pytest.raises(DataAccessViolation, match="no legal forcing"):
        replay_planner_missing_day.plan("task-1", date(2025, 5, 1), date(2025, 5, 3))
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/replay/test_planner.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement deterministic daily planning**

Rules:

1. load Task and assert `current_scheme_id` points to a Scheme with `status="frozen"`;
2. generate one UTC issue time per calendar day using the explicit Task issue hour;
3. call `SnapshotResolver.resolve(task_id, "forecast", issue_time)` for every day;
4. preserve chronological order and reject duplicate issue times;
5. never search for a later snapshot if the resolver rejects an F-mode day.

Return a frozen `ReplayPlan`.

- [ ] **Step 4: Run planner tests**

Run: `uv run pytest tests/replay/test_planner.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/replay/planner.py tests/replay/test_planner.py
git commit -m "feat: plan legal historical replay cases"
```

### Task 4: Execute replay sequentially through SP4A ForecastService

**Files:**
- Create: `src/hydro_agent/replay/service.py`
- Modify: `tests/replay/test_service.py`

**Interfaces:**
- Consumes: `ReplayPlan`, `ForecastService.forecast(...)`.
- Produces: `ReplayService.execute(plan) -> tuple[ForecastRecord, ...]`.

- [ ] **Step 1: Write failing same-scheme replay test**

```python

def test_replay_uses_same_frozen_scheme_for_every_issue(replay_service, three_case_plan, repository):
    forecasts = replay_service.execute(three_case_plan)
    assert len(forecasts) == 3
    assert {forecast.scheme_id for forecast in forecasts} == {"scheme-frozen-1"}
    assert [forecast.issue_time for forecast in forecasts] == sorted(f.issue_time for f in forecasts)
    assert repository.get_task_state("task-1").optimization_cycles_used == 0
```

Add a failure test where ForecastService fails on case 2: case 1 remains persisted, case 2's failed ActionRun remains auditable, case 3 is not executed, and `ReplayStopped` is raised.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/replay/test_service.py -k 'replay' -v`

Expected: FAIL.

- [ ] **Step 3: Implement sequential execution**

For each `ReplayCase`:

```text
assert Task phase == F
assert Scheme status == frozen
if existing Forecast for same task/scheme/issue exists -> return it after hash/reference verification
else ForecastService.forecast(task_id, frozen_scheme_id, issue_time, policy)
continue
```

Never call `CalibrationService`, `CandidateSchemeService`, or `GateEvaluator` from replay execution.

- [ ] **Step 4: Run replay tests**

Run: `uv run pytest tests/replay/test_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/replay/service.py tests/replay/test_service.py
git commit -m "feat: execute frozen historical replay"
```

### Task 5: Extend metrics with KGE and build a read-only EvaluationService

**Files:**
- Modify: `src/hydro_agent/evaluation/metrics.py`
- Create: `src/hydro_agent/evaluation/service.py`
- Modify: `src/hydro_agent/persistence/repository.py`
- Test: `tests/evaluation/test_service.py`

**Interfaces:**
- Consumes: persisted Forecasts + E-phase observation snapshot.
- Produces: `repository.set_task_phase(task_id, phase)`, `EvaluationService.evaluate(task_id, observation_snapshot_id) -> ReplayEvaluation`.

- [ ] **Step 1: Write failing read-only evaluation tests**

```python
# tests/evaluation/test_service.py

def test_evaluation_reads_future_truth_only_in_e_phase(evaluation_service, repository):
    repository.set_task_phase("task-1", "E")
    before_scheme = repository.get_scheme("scheme-frozen-1").content_hash
    result = evaluation_service.evaluate("task-1", "snapshot-eval-truth")
    assert set(result.metrics) >= {"NSE", "KGE", "MAE", "Bias"}
    assert repository.get_scheme("scheme-frozen-1").content_hash == before_scheme


def test_evaluation_refuses_truth_snapshot_outside_e_phase(evaluation_service):
    with pytest.raises(ValueError, match="E phase"):
        evaluation_service.evaluate("task-build-phase", "snapshot-eval-truth")
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/evaluation/test_service.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement phase transition, KGE, and evaluation join**

`set_task_phase()` is the only Task phase mutation method; allow only `B -> F -> E`, never reverse transitions.

KGE 2009:

```python
r = corrcoef(obs, sim)[0, 1]
alpha = std(sim, ddof=0) / std(obs, ddof=0)
beta = mean(sim) / mean(obs)
kge = 1 - sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)
```

Reject zero observed standard deviation or zero observed mean with `ValueError` instead of returning NaN.

`EvaluationService` requires phase E, loads all successful replay Forecasts for the frozen Scheme, loads the evaluation observation snapshot through SP4 data policy with `capability="evaluate"`, joins truth to target dates for lead 1/2/3, computes per-lead NSE/KGE/MAE/Bias plus aggregate summaries, and returns a frozen result containing Task/Scheme/Snapshot/Forecast ids and sample counts. It writes no Scheme/Forecast mutation.

- [ ] **Step 4: Run evaluation tests**

Run: `uv run pytest tests/evaluation/test_service.py tests/evaluation/test_metrics.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/evaluation src/hydro_agent/persistence/repository.py tests/evaluation/test_service.py
git commit -m "feat: evaluate frozen replay in read-only phase"
```

### Task 6: Generate deterministic JSON and Markdown report artifacts

**Files:**
- Create: `src/hydro_agent/reporting/__init__.py`
- Create: `src/hydro_agent/reporting/report.py`
- Test: `tests/reporting/test_report.py`

**Interfaces:**
- Produces: `ReplayReportBuilder.build(evaluation, output_dir) -> tuple[Path, Path]`.

- [ ] **Step 1: Write failing report traceability test**

```python
# tests/reporting/test_report.py
import json


def test_report_contains_traceable_scheme_snapshot_forecasts_and_metrics(report_builder, evaluation, tmp_path):
    json_path, md_path = report_builder.build(evaluation, tmp_path)
    payload = json.loads(json_path.read_text())
    assert payload["scheme_id"] == "scheme-frozen-1"
    assert payload["observation_snapshot_id"] == "snapshot-eval-truth"
    assert payload["forecast_ids"]
    text = md_path.read_text()
    assert "NSE" in text and "KGE" in text and "scheme-frozen-1" in text
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/reporting/test_report.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement deterministic report output**

Write `report.json` and `report.md`. Markdown sections are fixed: Task/frozen Scheme, replay period/forcing mode, snapshot/time-leak rules, forecast coverage, NSE/KGE/MAE/Bias table, Gate/freeze provenance, cost summary, limitations. Numeric formatting is `.4f`. Hash and register both files as promoted report artifacts; no LLM prose generation in SP7.

- [ ] **Step 4: Run reporting tests**

Run: `uv run pytest tests/reporting/test_report.py -v`

Expected: PASS and byte-identical output for identical inputs.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/reporting tests/reporting/test_report.py
git commit -m "feat: generate traceable replay reports"
```

### Task 7: Register A10/A11/A12 handlers and prove the complete frozen replay path

**Files:**
- Modify: `src/hydro_agent/agent/tools.py`
- Create: `tests/integration/test_frozen_historical_replay.py`

**Interfaces:**
- A10 -> `FreezeService`
- A11 -> `ReplayPlanner` + `ReplayService`
- A12 -> `EvaluationService` + `ReplayReportBuilder`

- [ ] **Step 1: Write the integration test**

```python
# tests/integration/test_frozen_historical_replay.py

def test_freeze_replay_evaluate_report_end_to_end(real_replay_flow):
    source_hash = real_replay_flow.repository.get_scheme("scheme-base").content_hash
    frozen_id = real_replay_flow.freeze()
    forecasts = real_replay_flow.replay(frozen_id)
    evaluation, report_artifacts = real_replay_flow.evaluate_and_report()

    assert len(forecasts) >= 3
    assert {f.scheme_id for f in forecasts} == {frozen_id}
    assert real_replay_flow.repository.get_scheme("scheme-base").content_hash == source_hash
    assert evaluation.scheme_id == frozen_id
    assert set(evaluation.metrics) >= {"NSE", "KGE", "MAE", "Bias"}
    assert len(report_artifacts) == 2
```

Also assert no `calibrate`/`adapt` ActionRun occurs after phase becomes F and a future-dated observation snapshot is rejected if injected into A11.

- [ ] **Step 2: Run and verify first missing boundary**

```bash
HYDRO_AGENT_LOWMAN_SNAPSHOT=... uv run pytest tests/integration/test_frozen_historical_replay.py -v
```

Expected before final wiring: FAIL at an unregistered A10/A11/A12 handler or missing fixture, not at data mutation.

- [ ] **Step 3: Register handlers explicitly**

```text
A10_FREEZE -> FreezeToolHandler
A11_REPLAY -> ReplayToolHandler
A12_EVALUATE_REPORT -> EvaluateReportToolHandler
```

Each handler converts service output to one `EvidencePacket`; no handler invokes model binaries directly.

- [ ] **Step 4: Run SP7 acceptance suite**

```bash
uv run pytest tests/replay tests/evaluation tests/reporting -v
HYDRO_AGENT_LOWMAN_SNAPSHOT=... uv run pytest tests/integration/test_frozen_historical_replay.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/agent/tools.py tests/integration/test_frozen_historical_replay.py
git commit -m "feat: complete frozen replay evaluation flow"
```

## SP7 Acceptance

```bash
uv run pytest tests/replay tests/evaluation tests/reporting -v
HYDRO_AGENT_LOWMAN_SNAPSHOT=... uv run pytest tests/integration/test_frozen_historical_replay.py -v
```

Acceptance requires one immutable frozen Scheme, sequential replay through the same Scheme, F-mode time-boundary enforcement for every issue time, no optimization after freeze, E-phase-only truth access, deterministic NSE/KGE/MAE/Bias computation, and traceable JSON/Markdown reports.