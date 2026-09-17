import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from hydro_agent.execution.contracts import ExecutionPolicy, ExecutionRequest
from hydro_agent.models.gr4j.adapter import Gr4jRuntimeAdapter
from hydro_agent.models.gr4j.contracts import Gr4jBasin, Gr4jScheme
from hydro_agent.models.gr4j.engine import simulate
from hydro_agent.models.registry import default_model_registry

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "gr4j"


@pytest.fixture
def prepared_gr4j_workspace(tmp_path):
    snapshot = tmp_path / "input" / "snapshot"
    scheme = tmp_path / "input" / "scheme"
    (tmp_path / "output").mkdir(parents=True)
    snapshot.mkdir(parents=True)
    scheme.mkdir(parents=True)
    shutil.copy(FIXTURES / "forcing.csv", snapshot / "forcing.csv")
    shutil.copy(FIXTURES / "basin.json", snapshot / "basin.json")
    shutil.copy(FIXTURES / "scheme.json", scheme / "scheme.json")
    request = ExecutionRequest(
        task_id="task-1",
        action_run_id="run-1",
        model_id="gr4j",
        capability="forecast",
        data_snapshot_id="snapshot-1",
        scheme_id="scheme-1",
        issue_time="2026-01-01T00:00:00Z",
        parameters={},
        policy=ExecutionPolicy(
            timeout_seconds=30, network_access=False, max_output_bytes=1_000_000, device="cpu"
        ),
    )
    (tmp_path / "execution-manifest.json").write_text(request.model_dump_json(), encoding="utf-8")
    return tmp_path


def test_gr4j_scheme_contract():
    scheme = Gr4jScheme.model_validate_json((FIXTURES / "scheme.json").read_text(encoding="utf-8"))
    assert scheme.model_id == "gr4j"
    assert scheme.parameter_vector() == (350.0, 0.0, 90.0, 1.7)


def test_gr4j_plugin_registered():
    registry = default_model_registry()
    plugin = registry.get("gr4j")
    assert plugin.descriptor.default_strategy_id == "gr4j-bounded-v1"
    assert plugin.descriptor.diagnosis_skill_id == "gr4j-calibration-diagnosis"
    assert "production" in plugin.descriptor.parameter_groups
    adapter = registry.runtime_registry().get("gr4j", "forecast")
    assert adapter.model_id == "gr4j"


def test_gr4j_zero_exchange_does_not_duplicate_effective_rainfall():
    """The fixed 90/10 routing split must conserve effective rainfall."""

    days = 500
    precipitation = 10.0
    inputs = np.zeros((days, 1, 2), dtype=float)
    inputs[:, 0, 0] = precipitation
    scheme = Gr4jScheme(
        warmup_days=1,
        parameters={"X1": 350.0, "X2": 0.0, "X3": 90.0, "X4": 1.7},
    )
    basin = Gr4jBasin(basin_id="water-balance", area_km2=1.0)

    discharge = simulate(scheme, basin, inputs, include_warmup=True)
    runoff_mm = float(discharge.sum()) * 86400.0 / (basin.area_km2 * 1000.0)

    initial_storage_mm = 0.3 * scheme.parameters["X1"] + 0.5 * scheme.parameters["X3"]
    assert runoff_mm <= days * precipitation + initial_storage_mm + 1e-9


def test_gr4j_runtime_forecast(prepared_gr4j_workspace):
    adapter = Gr4jRuntimeAdapter()
    argv = adapter.command(
        ExecutionRequest.model_validate_json(
            (prepared_gr4j_workspace / "execution-manifest.json").read_text(encoding="utf-8")
        ),
        prepared_gr4j_workspace,
    )
    completed = subprocess.run(argv, check=True, capture_output=True, text=True)
    assert completed.returncode == 0
    payload = json.loads((prepared_gr4j_workspace / "output" / "result.json").read_text(encoding="utf-8"))
    assert payload["model_id"] == "gr4j"
    assert [row["lead"] for row in payload["forecast"]] == [1, 2, 3]
    assert all(row["value"] >= 0 for row in payload["forecast"])


def test_gr4j_runtime_adapter_rejects_wrong_model(tmp_path):
    adapter = Gr4jRuntimeAdapter()
    request = ExecutionRequest(
        task_id="task-1",
        action_run_id="run-1",
        model_id="xaj",
        capability="forecast",
        data_snapshot_id="snapshot-1",
        scheme_id="scheme-1",
        issue_time="2026-01-01T00:00:00Z",
        parameters={},
        policy=ExecutionPolicy(
            timeout_seconds=30, network_access=False, max_output_bytes=1_000_000, device="cpu"
        ),
    )
    with pytest.raises(ValueError):
        adapter.command(request, tmp_path)
