import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hydro_agent.execution.contracts import ExecutionPolicy, ExecutionRequest
from hydro_agent.execution.hashing import sha256_file

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "xaj"


def _prepare(workspace: Path) -> Path:
    snapshot = workspace / "input" / "snapshot"
    scheme = workspace / "input" / "scheme"
    (workspace / "output").mkdir(parents=True)
    snapshot.mkdir(parents=True)
    scheme.mkdir(parents=True)
    shutil.copy(FIXTURES / "forcing.csv", snapshot / "forcing.csv")
    shutil.copy(FIXTURES / "basin.json", snapshot / "basin.json")
    shutil.copy(FIXTURES / "scheme.json", scheme / "scheme.json")
    streamflow = "\n".join(
        [
            "date,discharge_m3s",
            "2025-12-28,1.0",
            "2025-12-29,1.2",
            "2025-12-30,1.1",
            "2025-12-31,1.4",
            "2026-01-01,1.3",
            "2026-01-02,1.6",
            "2026-01-03,1.5",
            "2026-01-04,1.7",
            "",
        ]
    )
    (snapshot / "streamflow.csv").write_text(streamflow, encoding="utf-8")
    request = ExecutionRequest(
        task_id="task-cal",
        action_run_id="cal-run",
        model_id="xaj",
        capability="calibrate",
        data_snapshot_id="snap-cal",
        scheme_id="scheme-base",
        issue_time="2026-01-01T00:00:00Z",
        parameters={"strategy_id": "xaj-bounded-v1"},
        policy=ExecutionPolicy(
            timeout_seconds=120,
            network_access=False,
            max_output_bytes=5_000_000,
            device="cpu",
        ),
    )
    (workspace / "execution-manifest.json").write_text(
        request.model_dump_json(), encoding="utf-8"
    )
    return workspace


@pytest.fixture
def calibration_workspace(tmp_path):
    return _prepare(tmp_path / "base")


def run_calibration_copy(calibration_workspace: Path, suffix: str) -> dict:
    pytest.importorskip("numpy")
    target = calibration_workspace.parent / suffix
    shutil.copytree(calibration_workspace, target)
    scheme_path = target / "input/scheme/scheme.json"
    before = sha256_file(scheme_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "hydro_agent.models.xaj.calibrate_runtime",
            "--workspace",
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert sha256_file(scheme_path) == before
    return json.loads((target / "output/calibration-result.json").read_text())


def test_sceua_calibration_is_deterministic(calibration_workspace):
    first = run_calibration_copy(calibration_workspace, "a")
    second = run_calibration_copy(calibration_workspace, "b")
    assert first["strategy_id"] == "xaj-bounded-v1"
    assert first["optimizer"] == "sce-ua"
    assert first["candidate_parameters"] == second["candidate_parameters"]
    assert first["requested_candidates"] == 96
    assert 0 < first["optimizer_calls"] <= 96
    assert 0 < first["evaluated_candidates"] <= 96
    assert first["evaluated_candidates"] == second["evaluated_candidates"]
    assert first["objective_value"] == second["objective_value"]
    assert first["model_version"] == "teacher-xaj-v6-20260908"
    assert first["optimization_trace"]
    csv_path = calibration_workspace.parent / "a" / "output" / "calibration-comparison.csv"
    assert csv_path.is_file()
    header = csv_path.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("time,observed_m3s,baseline_m3s,candidate_m3s")
    metrics = json.loads(
        (calibration_workspace.parent / "a" / "output" / "calibration-metrics.json").read_text()
    )
    assert metrics["kind"] == "calibration"
