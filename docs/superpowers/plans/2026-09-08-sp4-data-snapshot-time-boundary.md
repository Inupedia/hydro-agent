# SP4 DataSnapshot Materialization and F/R Time Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a real `camels_13235000` DataSnapshot for XAJ and enforce historical data availability before any runtime is launched, so F-mode cannot see future observations/reanalysis and R-mode is explicitly labeled when future reanalysis is used.

**Architecture:** Normalize source data into row-level records carrying both hydrologic time and `available_at`. A deterministic `SnapshotBuilder` filters those records according to Task phase, forcing mode, issue time, and action capability, writes only legal rows to an immutable snapshot directory, hashes every file, and stores the manifest through SP2. `SandboxRunner` receives the resulting snapshot path; it never receives a general data root.

**Tech Stack:** Python 3.12, csv/json stdlib, Pydantic 2, pytest 8. Optional one-time preparation uses Caravan v1.6 CSV/NetCDF source data outside the sandbox.

**Spec:** `docs/superpowers/specs/2026-09-08-execution-sandbox-design.md`

## Global Constraints

- Primary basin: South Fork Payette River at Lowman, Idaho / USGS 13235000 / `camels_13235000`.
- XAJ R-mode forcing uses precipitation plus FAO Penman-Monteith PET when available; do not silently substitute actual ET or unlabeled evaporation.
- F-mode rule: every value visible to model execution must satisfy its historical availability semantics at `issue_time`.
- Future observed discharge is unavailable to `forecast`, `calibrate`, `adapt`, and `rebuild_state`.
- Future observed discharge is visible only to E-phase read-only evaluation.
- R-mode may expose future reanalysis only when Task `forcing_mode == "R"`; the manifest records that mode.
- Data is filtered/materialized before execution; prompt instructions are not a security boundary.
- Snapshot files and manifest are immutable after hashing/persistence.

---

## File Structure

```text
src/hydro_agent/data/__init__.py
src/hydro_agent/data/contracts.py
src/hydro_agent/data/policy.py
src/hydro_agent/data/snapshot.py
src/hydro_agent/data/lowman.py
scripts/prepare_lowman_source.py
tests/data/test_policy.py
tests/data/test_snapshot.py
tests/data/test_lowman.py
data/.gitkeep
```

### Task 1: Define row-level availability and snapshot contracts

**Files:**
- Create: `src/hydro_agent/data/__init__.py`
- Create: `src/hydro_agent/data/contracts.py`
- Test: `tests/data/test_policy.py`

**Interfaces:**
- Produces: `ForcingRow`, `FlowObservation`, `SnapshotContext`, `SnapshotManifest`, `SnapshotFile`.

- [ ] **Step 1: Write failing validation tests**

```python
# tests/data/test_policy.py
from datetime import date, datetime, timezone
import pytest
from pydantic import ValidationError
from hydro_agent.data.contracts import ForcingRow


def test_forcing_row_requires_explicit_provenance_and_availability():
    row = ForcingRow(
        valid_date=date(2025, 5, 2),
        precipitation_mm_day=4.0,
        pet_mm_day=2.0,
        source_kind="forecast",
        source="hres",
        available_at=datetime(2025, 5, 1, 0, tzinfo=timezone.utc),
    )
    assert row.source_kind == "forecast"
    with pytest.raises(ValidationError):
        ForcingRow(
            valid_date=date(2025, 5, 2),
            precipitation_mm_day=4.0,
            pet_mm_day=2.0,
            source_kind="forecast",
            source="hres",
            available_at=None,
        )
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/data/test_policy.py -v`

Expected: FAIL because contracts are missing.

- [ ] **Step 3: Implement exact contracts**

```python
ForcingSourceKind = Literal["observation", "reanalysis", "forecast"]
Phase = Literal["B", "F", "E"]
ForcingMode = Literal["R", "F"]
```

`ForcingRow` fields: `valid_date`, `precipitation_mm_day >= 0`, `pet_mm_day >= 0`, `source_kind`, `source`, `available_at`.

`FlowObservation` fields: `valid_date`, `discharge_m3s >= 0`, `source`, `available_at`.

`SnapshotContext` fields: `task_id`, `snapshot_id`, `basin_id`, `phase`, `forcing_mode`, `capability`, `issue_time`.

`SnapshotFile` fields: `role`, `relative_path`, `sha256`, `bytes`, `row_count`, `min_valid_date`, `max_valid_date`, `sources`.

`SnapshotManifest` fields: `snapshot_id`, `context`, `files`, `created_at`.

All models are frozen and `extra="forbid"`.

- [ ] **Step 4: Run contract tests**

Run: `uv run pytest tests/data/test_policy.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/data tests/data/test_policy.py
git commit -m "feat: define snapshot availability contracts"
```

### Task 2: Implement deterministic F/R and phase policy

**Files:**
- Create: `src/hydro_agent/data/policy.py`
- Modify: `tests/data/test_policy.py`

**Interfaces:**
- Produces: `DataAccessPolicy.select_forcing(context, rows)`, `select_flow(context, rows)`.

- [ ] **Step 1: Write failing time-leak regression tests**

```python
from datetime import date, datetime, timezone
from hydro_agent.data.policy import DataAccessPolicy

ISSUE = datetime(2025, 5, 1, 0, tzinfo=timezone.utc)


def test_f_mode_forecast_rejects_future_reanalysis(f_context, forcing_rows):
    selected = DataAccessPolicy().select_forcing(f_context, forcing_rows)
    assert all(not (r.valid_date > ISSUE.date() and r.source_kind == "reanalysis") for r in selected)


def test_f_mode_accepts_future_forecast_issued_by_issue_time(f_context, forcing_rows):
    selected = DataAccessPolicy().select_forcing(f_context, forcing_rows)
    future = [r for r in selected if r.valid_date > ISSUE.date()]
    assert future
    assert all(r.source_kind == "forecast" and r.available_at <= ISSUE for r in future)


def test_r_mode_may_use_future_reanalysis(r_context, forcing_rows):
    selected = DataAccessPolicy().select_forcing(r_context, forcing_rows)
    assert any(r.valid_date > ISSUE.date() and r.source_kind == "reanalysis" for r in selected)


def test_forecast_never_sees_future_observed_discharge(f_context, flow_rows):
    selected = DataAccessPolicy().select_flow(f_context, flow_rows)
    assert all(r.valid_date <= ISSUE.date() for r in selected)
```

Add an E-phase test asserting target discharge after issue time is included only when `phase="E"` and `capability="evaluate"`.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/data/test_policy.py -k 'mode or discharge' -v`

Expected: FAIL.

- [ ] **Step 3: Implement policy rules explicitly**

For forcing:

```text
valid_date <= issue_date:
  include only rows with available_at <= issue_time

valid_date > issue_date and forcing_mode == F:
  include only source_kind == forecast and available_at <= issue_time

valid_date > issue_date and forcing_mode == R:
  include source_kind == reanalysis (or forecast) and record mode R
```

For flow observations:

```text
phase B/F or capability != evaluate:
  valid_date <= issue_date and available_at <= issue_time

phase E and capability == evaluate:
  include evaluation target dates in the requested window
```

Raise `DataAccessViolation` when a required lead day has no legal forcing instead of filling it with later data.

- [ ] **Step 4: Run policy tests**

Run: `uv run pytest tests/data/test_policy.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/data/policy.py tests/data/test_policy.py
git commit -m "feat: enforce historical data availability"
```

### Task 3: Materialize legal rows into an immutable snapshot and persist its manifest

**Files:**
- Create: `src/hydro_agent/data/snapshot.py`
- Test: `tests/data/test_snapshot.py`

**Interfaces:**
- Consumes: `SnapshotContext`, normalized rows, basin metadata, SP2 `HydroRepository`.
- Produces: `SnapshotBuilder.build(...) -> Path` containing `forcing.csv`, `streamflow.csv`, `basin.json`, `snapshot-manifest.json`.

- [ ] **Step 1: Write failing materialization test**

```python
# tests/data/test_snapshot.py
import json


def test_snapshot_contains_only_policy_selected_rows(snapshot_builder, f_context, forcing_rows, flow_rows, basin):
    path = snapshot_builder.build(f_context, forcing_rows=forcing_rows, flow_rows=flow_rows, basin=basin)
    manifest = json.loads((path / "snapshot-manifest.json").read_text())
    assert manifest["context"]["forcing_mode"] == "F"
    assert {f["relative_path"] for f in manifest["files"]} == {"forcing.csv", "streamflow.csv", "basin.json"}
    assert all(len(f["sha256"]) == 64 for f in manifest["files"])
```

Add a test that rebuilding the same `snapshot_id` raises `FileExistsError`.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/data/test_snapshot.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement SnapshotBuilder**

Use signature:

```python
class SnapshotBuilder:
    def __init__(self, root: Path, policy: DataAccessPolicy, repository: HydroRepository) -> None: ...

    def build(
        self,
        context: SnapshotContext,
        *,
        forcing_rows: list[ForcingRow],
        flow_rows: list[FlowObservation],
        basin: dict[str, object],
    ) -> Path: ...
```

Write CSVs in ascending date order, JSON with sorted keys, compute SHA-256 using SP1 `sha256_file`, set files `0444`, directory `0555` after completion, then call SP2 `create_snapshot()` with the manifest hash.

- [ ] **Step 4: Run snapshot tests**

Run: `uv run pytest tests/data/test_snapshot.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/data/snapshot.py tests/data/test_snapshot.py
git commit -m "feat: materialize immutable data snapshots"
```

### Task 4: Add a real Lowman/Caravan source normalizer outside the sandbox

**Files:**
- Create: `src/hydro_agent/data/lowman.py`
- Create: `scripts/prepare_lowman_source.py`
- Test: `tests/data/test_lowman.py`
- Create: `data/.gitkeep`

**Interfaces:**
- Consumes: a user-supplied Caravan v1.6 timeseries CSV for `camels_13235000` and one Caravan attribute row.
- Produces normalized JSONL under `data/source/camels_13235000/`: `forcing.jsonl`, `flow.jsonl`, `basin.json`.

- [ ] **Step 1: Write failing source-mapping tests**

```python
# tests/data/test_lowman.py
from hydro_agent.data.lowman import normalize_caravan_row


def test_caravan_v16_uses_fao_pm_pet():
    row = normalize_caravan_row({
        "date": "2020-01-01",
        "total_precipitation_sum": "5.0",
        "potential_evaporation_sum_FAO_PENMAN_MONTEITH": "2.5",
        "streamflow": "3.2",
    })
    assert row.forcing.precipitation_mm_day == 5.0
    assert row.forcing.pet_mm_day == 2.5
    assert row.flow.discharge_m3s == 3.2
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/data/test_lowman.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement the source normalizer and CLI**

CLI:

```bash
uv run python scripts/prepare_lowman_source.py \
  --timeseries /absolute/path/to/camels_13235000.csv \
  --attributes /absolute/path/to/camels_attributes.csv \
  --output data/source/camels_13235000
```

Required source columns:

```text
date
total_precipitation_sum
potential_evaporation_sum_FAO_PENMAN_MONTEITH
streamflow
```

`basin.json` must contain `basin_id="camels_13235000"`, `station_id="USGS-13235000"`, and positive `area_km2` read from the attribute source. For this historical R-source normalizer, set forcing `source_kind="reanalysis"`, source `caravan-era5-land-fao-pm`, and `available_at` to a clearly post-valid-time publication timestamp so these rows cannot accidentally qualify as real-time F-mode future forcing.

- [ ] **Step 4: Run normalizer tests**

Run: `uv run pytest tests/data/test_lowman.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/data/lowman.py scripts/prepare_lowman_source.py tests/data/test_lowman.py data/.gitkeep
git commit -m "feat: normalize Lowman Caravan source data"
```

### Task 5: Build the real R-mode Lowman XAJ snapshot and prove the F-mode rejection path

**Files:**
- Create: `scripts/build_snapshot.py`
- Create: `tests/integration/test_lowman_snapshot_policy.py`

**Interfaces:**
- Consumes: Task 4 normalized source, SP2 SQLite database.
- Produces: real snapshot directory consumed by SP3 integration test.

- [ ] **Step 1: Write the integration policy test**

```python
# tests/integration/test_lowman_snapshot_policy.py

def test_f_mode_cannot_build_three_future_leads_from_reanalysis_only(lowman_source, snapshot_builder, f_context):
    with pytest.raises(DataAccessViolation, match="no legal forcing"):
        snapshot_builder.build(f_context, **lowman_source)
```

- [ ] **Step 2: Verify failure before source fixture wiring**

Run: `uv run pytest tests/integration/test_lowman_snapshot_policy.py -v`

Expected: FAIL or SKIP only because the external Lowman source path is not configured; once configured, the test must PASS by raising the expected policy error.

- [ ] **Step 3: Implement the build CLI**

```bash
uv run python scripts/build_snapshot.py \
  --source data/source/camels_13235000 \
  --task-id lowman-r-001 \
  --snapshot-id lowman-r-2020-05-01 \
  --phase B \
  --forcing-mode R \
  --capability forecast \
  --issue-time 2020-05-01T00:00:00Z \
  --lead-days 1,2,3 \
  --db sqlite+pysqlite:///data/hydro-agent.db \
  --output-root data/snapshots
```

The CLI loads enough history for the scheme warmup (365 days) plus issue/lead dates and prints the absolute created snapshot path.

- [ ] **Step 4: Run the real snapshot + SP3 vertical slice**

```bash
SNAPSHOT=$(uv run python scripts/build_snapshot.py ... | tail -n 1)
HYDRO_AGENT_LOWMAN_SNAPSHOT="$SNAPSHOT" uv run pytest tests/integration/test_xaj_sandbox_forecast.py -v
```

Expected: SP4 policy tests PASS and SP3 real XAJ sandbox forecast PASS in R mode. F mode built from the same reanalysis-only source must be rejected.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_snapshot.py tests/integration/test_lowman_snapshot_policy.py
git commit -m "test: enforce Lowman snapshot time boundary"
```

## SP4 Acceptance

```bash
uv run pytest tests/data -v
uv run pytest tests/integration/test_lowman_snapshot_policy.py -v
```

Then create one real R-mode Lowman snapshot and use it to pass SP3's integration test. SP4 does not claim strict F-mode replay until historical forecast forcing (HRES/GraphCast/GEFS) is added with real issue/release timestamps.