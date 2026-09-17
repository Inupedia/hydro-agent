import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hydro_agent.execution.contracts import ExecutionPolicy, ExecutionRequest
from hydro_agent.models.registry import default_model_registry
from hydro_agent.models.sacsma.adapter import SacSmaRuntimeAdapter
from hydro_agent.models.sacsma.contracts import SacSmaScheme

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "sacsma"


@pytest.fixture
def prepared_sacsma_workspace(tmp_path):
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
        model_id="sac-sma",
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


def test_sacsma_scheme_contract():
    scheme = SacSmaScheme.model_validate_json((FIXTURES / "scheme.json").read_text(encoding="utf-8"))
    assert scheme.model_id == "sac-sma"
    assert len(scheme.parameter_vector()) == 12


def test_sacsma_plugin_registered():
    registry = default_model_registry()
    plugin = registry.get("sac-sma")
    assert plugin.descriptor.default_strategy_id == "sac-sma-bounded-v1"
    assert plugin.descriptor.diagnosis_skill_id == "sac-sma-calibration-diagnosis"
    assert plugin.descriptor.required_forcings == ("precipitation", "pet")
    assert "upper" in plugin.descriptor.parameter_groups
    adapter = registry.runtime_registry().get("sac-sma", "forecast")
    assert adapter.model_id == "sac-sma"


def test_sacsma_runtime_forecast(prepared_sacsma_workspace):
    adapter = SacSmaRuntimeAdapter()
    argv = adapter.command(
        ExecutionRequest.model_validate_json(
            (prepared_sacsma_workspace / "execution-manifest.json").read_text(encoding="utf-8")
        ),
        prepared_sacsma_workspace,
    )
    completed = subprocess.run(argv, check=True, capture_output=True, text=True)
    assert completed.returncode == 0
    payload = json.loads((prepared_sacsma_workspace / "output" / "result.json").read_text(encoding="utf-8"))
    assert payload["model_id"] == "sac-sma"
    assert [row["lead"] for row in payload["forecast"]] == [1, 2, 3]
    assert all(row["value"] >= 0 for row in payload["forecast"])


def test_sacsma_runtime_adapter_rejects_wrong_model(tmp_path):
    adapter = SacSmaRuntimeAdapter()
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
