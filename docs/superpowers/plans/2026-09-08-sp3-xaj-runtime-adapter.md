# SP3 First Real Hydrologic RuntimeAdapter — XAJ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one real XAJ lead-1/2/3 forecast for `camels_13235000` through `ExecutionRequest -> SandboxRunner -> XajRuntimeAdapter -> ExecutionResult`, with no model/network access outside the sandbox contract.

**Architecture:** Lock the upstream `OuyangWenyu/hydromodel` implementation to commit `89d7a8ed1d72ce4fffbbd9897490b089382ecbac`. Hydro-Agent prepares a model-neutral snapshot (`forcing.csv`, `basin.json`) and immutable XAJ scheme (`scheme.json`). A child CLI converts those files to NumPy arrays, calls `hydromodel.models.xaj.xaj`, converts runoff depth to m³/s using basin area, and emits `forecast.csv` plus normalized `result.json`.

**Tech Stack:** Python 3.12, NumPy, pinned GitHub `hydromodel` XAJ implementation, Pydantic 2, pytest 8.

**Spec:** `docs/superpowers/specs/2026-09-08-execution-sandbox-design.md`

## Global Constraints

- XAJ is the first real Adapter; OpenHydroNet remains behind the same `RuntimeAdapter` boundary for a later slice.
- Upstream source is locked to commit `89d7a8ed1d72ce4fffbbd9897490b089382ecbac`; do not follow `master` implicitly.
- Upstream `hydromodel` is GPL-3.0; record the dependency/license in `THIRD_PARTY.md` before distribution decisions.
- Direct XAJ call uses parameter order `K, B, IM, UM, LM, DM, C, SM, EX, KI, KG, CS, L, CI, CG` and `normalized_params=False`.
- Daily XAJ run uses `time_interval_hours=24`.
- Forecast runtime receives only materialized snapshot/scheme files; it does not download CAMELS/USGS data.
- Runtime must output lead 1/2/3 with explicit issue time, target dates, unit, scheme id, and snapshot id.
- Same frozen inputs must reproduce the same values within absolute tolerance `1e-9` m³/s on the same dependency lock/device.

---

## File Structure

```text
pyproject.toml
THIRD_PARTY.md
src/hydro_agent/models/__init__.py
src/hydro_agent/models/xaj/__init__.py
src/hydro_agent/models/xaj/contracts.py
src/hydro_agent/models/xaj/adapter.py
src/hydro_agent/models/xaj/runtime.py
src/hydro_agent/models/xaj/conversion.py
tests/models/xaj/test_contracts.py
tests/models/xaj/test_conversion.py
tests/models/xaj/test_runtime.py
tests/integration/test_xaj_sandbox_forecast.py
tests/fixtures/xaj/scheme.json
tests/fixtures/xaj/forcing.csv
tests/fixtures/xaj/basin.json
```

### Task 1: Lock the XAJ dependency and define immutable scheme/input contracts

**Files:**
- Modify: `pyproject.toml`
- Create: `THIRD_PARTY.md`
- Create: `src/hydro_agent/models/__init__.py`
- Create: `src/hydro_agent/models/xaj/__init__.py`
- Create: `src/hydro_agent/models/xaj/contracts.py`
- Test: `tests/models/xaj/test_contracts.py`

**Interfaces:**
- Produces: `XajScheme`, `XajBasin`, `XajForecastRow`.

- [ ] **Step 1: Write the failing XAJ contract test**

```python
# tests/models/xaj/test_contracts.py
import pytest
from pydantic import ValidationError
from hydro_agent.models.xaj.contracts import XajScheme

PARAMS = {
    "K": 0.75, "B": 0.25, "IM": 0.06, "UM": 20.0, "LM": 60.0,
    "DM": 40.0, "C": 0.16, "SM": 20.0, "EX": 1.2, "KI": 0.3,
    "KG": 0.4, "CS": 0.9, "L": 2.0, "CI": 0.8, "CG": 0.98,
}


def test_xaj_scheme_requires_exact_parameter_set():
    scheme = XajScheme(model_id="xaj", warmup_days=365, parameters=PARAMS)
    assert list(scheme.parameter_vector()) == [PARAMS[name] for name in scheme.PARAMETER_ORDER]
    broken = dict(PARAMS)
    broken.pop("KG")
    with pytest.raises(ValidationError):
        XajScheme(model_id="xaj", warmup_days=365, parameters=broken)
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/models/xaj/test_contracts.py -v`

Expected: FAIL because XAJ package is missing.

- [ ] **Step 3: Add the dependency lock and contracts**

Add an optional dependency so SP1 tests do not require the heavy model stack:

```toml
[project.optional-dependencies]
xaj = [
  "hydromodel @ git+https://github.com/OuyangWenyu/hydromodel.git@89d7a8ed1d72ce4fffbbd9897490b089382ecbac",
]
```

`THIRD_PARTY.md` must record repository, locked commit, GPL-3.0, and that Hydro-Agent uses its XAJ numerical implementation.

Implement `XajScheme` as frozen Pydantic model with class constant:

```python
PARAMETER_ORDER = ("K", "B", "IM", "UM", "LM", "DM", "C", "SM", "EX", "KI", "KG", "CS", "L", "CI", "CG")
```

Validate `set(parameters) == set(PARAMETER_ORDER)`, `warmup_days >= 1`, and all values finite. `parameter_vector()` returns the values in that exact order.

`XajBasin` fields: `basin_id: str`, `area_km2: float > 0`.

- [ ] **Step 4: Run contract tests**

Run: `uv sync --extra dev --extra xaj && uv run pytest tests/models/xaj/test_contracts.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml THIRD_PARTY.md src/hydro_agent/models tests/models/xaj/test_contracts.py
git commit -m "feat: lock XAJ runtime contract"
```

### Task 2: Define the materialized XAJ file contract and conversion helpers

**Files:**
- Create: `src/hydro_agent/models/xaj/conversion.py`
- Create: `tests/models/xaj/test_conversion.py`
- Create: `tests/fixtures/xaj/scheme.json`
- Create: `tests/fixtures/xaj/forcing.csv`
- Create: `tests/fixtures/xaj/basin.json`

**Interfaces:**
- Consumes: snapshot files under `input/snapshot/` and scheme under `input/scheme/`.
- Produces: `load_xaj_inputs(workspace) -> tuple[XajScheme, XajBasin, list[date], np.ndarray]`, `runoff_mm_day_to_m3s()`.

- [ ] **Step 1: Write failing conversion tests**

```python
# tests/models/xaj/test_conversion.py
from hydro_agent.models.xaj.conversion import runoff_mm_day_to_m3s


def test_runoff_depth_conversion():
    # 1 mm/day over 1 km² = 1000 m³/day
    assert runoff_mm_day_to_m3s(1.0, 1.0) == pytest.approx(1000.0 / 86400.0)
```

Add a file-loading test asserting:

```text
forcing.csv columns exactly:
date,precipitation_mm_day,pet_mm_day
```

and that dates are strictly increasing, values are finite, precipitation/PET are non-negative, and row count is at least `warmup_days + 3`.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/models/xaj/test_conversion.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement conversion helpers**

```python
def runoff_mm_day_to_m3s(runoff_mm_day: float, area_km2: float) -> float:
    return runoff_mm_day * area_km2 * 1000.0 / 86400.0
```

`load_xaj_inputs()` reads:

```text
input/snapshot/forcing.csv
input/snapshot/basin.json
input/scheme/scheme.json
```

and returns `p_and_e` as shape `[time, 1, 2]` with precipitation first, PET second.

Fixture forcing data may be deterministic synthetic values for fast unit tests; it must not be used to claim the SP3 real-data acceptance.

- [ ] **Step 4: Run conversion tests**

Run: `uv run pytest tests/models/xaj/test_conversion.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/models/xaj/conversion.py tests/models/xaj/test_conversion.py tests/fixtures/xaj
git commit -m "feat: define XAJ sandbox input format"
```

### Task 3: Implement the child-process XAJ runtime

**Files:**
- Create: `src/hydro_agent/models/xaj/runtime.py`
- Test: `tests/models/xaj/test_runtime.py`

**Interfaces:**
- Consumes: `--workspace PATH`, materialized XAJ files, and `execution-manifest.json`.
- Produces: `output/forecast.csv`, `output/result.json`; exit code 0 only for a contract-valid run.

- [ ] **Step 1: Write failing runtime test**

```python
# tests/models/xaj/test_runtime.py
import json
import subprocess
import sys


def test_xaj_runtime_writes_three_leads(prepared_xaj_workspace):
    completed = subprocess.run(
        [sys.executable, "-m", "hydro_agent.models.xaj.runtime", "--workspace", str(prepared_xaj_workspace)],
        check=False,
    )
    assert completed.returncode == 0
    payload = json.loads((prepared_xaj_workspace / "output/result.json").read_text())
    assert payload["unit"] == "m3/s"
    assert [item["lead"] for item in payload["forecast"]] == [1, 2, 3]
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/models/xaj/test_runtime.py -v`

Expected: FAIL because runtime is missing.

- [ ] **Step 3: Implement runtime execution**

Runtime logic:

```python
from hydromodel.models.xaj import xaj

q_sim, _ = xaj(
    p_and_e,
    np.asarray([scheme.parameter_vector()], dtype=float),
    return_state=False,
    warmup_length=scheme.warmup_days,
    normalized_params=False,
    name="xaj",
    source_type="sources",
    source_book="HF",
    time_interval_hours=24,
)
```

Flatten the single-basin `q_sim`, take the final three values as lead 1/2/3, convert each from mm/day to m³/s, and write:

```json
{
  "model_id": "xaj",
  "scheme_id": "...",
  "data_snapshot_id": "...",
  "issue_time": "...",
  "unit": "m3/s",
  "forecast": [
    {"lead": 1, "target_date": "YYYY-MM-DD", "value": 1.23},
    {"lead": 2, "target_date": "YYYY-MM-DD", "value": 2.34},
    {"lead": 3, "target_date": "YYYY-MM-DD", "value": 3.45}
  ]
}
```

Reject NaN/Inf and mismatched issue date before writing `result.json`.

- [ ] **Step 4: Run runtime tests**

Run: `uv run pytest tests/models/xaj/test_runtime.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/models/xaj/runtime.py tests/models/xaj/test_runtime.py
git commit -m "feat: run XAJ forecast runtime"
```

### Task 4: Register XajRuntimeAdapter with SandboxRunner

**Files:**
- Create: `src/hydro_agent/models/xaj/adapter.py`
- Modify: `src/hydro_agent/models/xaj/__init__.py`
- Modify: `tests/models/xaj/test_runtime.py`

**Interfaces:**
- Produces: `XajRuntimeAdapter.model_id == "xaj"`, capabilities `validate`, `rebuild_state`, `forecast`, `calibrate`.
- For this task only `forecast` command is executable; unsupported not-yet-implemented capabilities return a controlled runtime failure until SP5 implements calibration.

- [ ] **Step 1: Write failing adapter-command test**

```python
from hydro_agent.models.xaj.adapter import XajRuntimeAdapter


def test_xaj_adapter_returns_argv_not_shell_text(execution_request, tmp_path):
    adapter = XajRuntimeAdapter()
    argv = adapter.command(execution_request.model_copy(update={"model_id": "xaj"}), tmp_path)
    assert argv[:3] == [sys.executable, "-m", "hydro_agent.models.xaj.runtime"]
    assert "--workspace" in argv
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/models/xaj/test_runtime.py -k adapter -v`

Expected: FAIL.

- [ ] **Step 3: Implement adapter**

`XajRuntimeAdapter.command()` must require `request.capability == "forecast"` for SP3 and return:

```python
[sys.executable, "-m", "hydro_agent.models.xaj.runtime", "--workspace", str(workspace)]
```

No user/LLM string becomes executable argv.

- [ ] **Step 4: Run XAJ unit tests**

Run: `uv run pytest tests/models/xaj -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/models/xaj/adapter.py src/hydro_agent/models/xaj/__init__.py tests/models/xaj/test_runtime.py
git commit -m "feat: register XAJ sandbox adapter"
```

### Task 5: Prove the real Lowman lead-1/2/3 vertical slice

**Files:**
- Create: `tests/integration/test_xaj_sandbox_forecast.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: SP4 materialized snapshot at `data/snapshots/camels_13235000/<snapshot_id>/` and SP2 seeded Scheme/Snapshot records.
- Produces: one real successful SandboxRunner result with three forecast values.

- [ ] **Step 1: Write the integration test before SP4 data exists**

```python
# tests/integration/test_xaj_sandbox_forecast.py
import os
from pathlib import Path
import pytest

REAL_SNAPSHOT = os.getenv("HYDRO_AGENT_LOWMAN_SNAPSHOT")
pytestmark = pytest.mark.skipif(not REAL_SNAPSHOT, reason="set HYDRO_AGENT_LOWMAN_SNAPSHOT to SP4 snapshot")


def test_real_lowman_forecast_is_reproducible(real_xaj_runner, real_xaj_request):
    first = real_xaj_runner.run(real_xaj_request.model_copy(update={"action_run_id": "real-run-1"}))
    second = real_xaj_runner.run(real_xaj_request.model_copy(update={"action_run_id": "real-run-2"}))
    assert first.status == second.status == "succeeded"
    f1 = [x["value"] for x in first.result_payload["forecast"]]
    f2 = [x["value"] for x in second.result_payload["forecast"]]
    assert f1 == pytest.approx(f2, abs=1e-9)
    assert len(f1) == 3
```

- [ ] **Step 2: Verify the test is explicitly skipped until SP4 provides data**

Run: `uv run pytest tests/integration/test_xaj_sandbox_forecast.py -v`

Expected: SKIPPED with the exact setup reason, not FAIL.

- [ ] **Step 3: Wire the SP4 snapshot fixture**

After SP4 creates a snapshot, set:

```bash
export HYDRO_AGENT_LOWMAN_SNAPSHOT="$PWD/data/snapshots/camels_13235000/<generated-snapshot-id>"
```

The fixture must copy only that snapshot's declared `forcing.csv` and `basin.json`, plus the immutable XAJ `scheme.json`, into the action workspace before launch.

- [ ] **Step 4: Run the real integration test twice**

Run: `uv run pytest tests/integration/test_xaj_sandbox_forecast.py -v`

Expected: PASS with exactly three finite m³/s values and deterministic rerun tolerance `1e-9`.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_xaj_sandbox_forecast.py tests/conftest.py
git commit -m "test: prove real XAJ sandbox forecast"
```

## SP3 Acceptance

Fast tests:

```bash
uv run pytest tests/models/xaj -v
```

Real acceptance after SP4:

```bash
HYDRO_AGENT_LOWMAN_SNAPSHOT=/absolute/path/to/snapshot \
uv run pytest tests/integration/test_xaj_sandbox_forecast.py -v
```

SP3 is complete only after the real-data test passes; a synthetic fixture proves plumbing but does not satisfy the vertical-slice requirement.