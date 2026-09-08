import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hydro_agent.execution.contracts import ExecutionPolicy, ExecutionRequest
from hydro_agent.models.xaj.adapter import XajRuntimeAdapter

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "xaj"


@pytest.fixture
def prepared_xaj_workspace(tmp_path):
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
    (tmp_path / "execution-manifest.json").write_text(request.model_dump_json(), encoding="utf-8")
    return tmp_path


def test_xaj_runtime_writes_three_leads(prepared_xaj_workspace):
    pytest.importorskip("numpy")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "hydro_agent.models.xaj.runtime",
            "--workspace",
            str(prepared_xaj_workspace),
        ],
        check=False,
    )
    assert completed.returncode == 0
    payload = json.loads((prepared_xaj_workspace / "output/result.json").read_text())
    assert payload["unit"] == "m3/s"
    assert [item["lead"] for item in payload["forecast"]] == [1, 2, 3]


def test_xaj_adapter_returns_argv_not_shell_text(execution_request, tmp_path):
    adapter = XajRuntimeAdapter()
    argv = adapter.command(execution_request.model_copy(update={"model_id": "xaj"}), tmp_path)
    assert argv[:3] == [sys.executable, "-m", "hydro_agent.models.xaj.runtime"]
    assert "--workspace" in argv
