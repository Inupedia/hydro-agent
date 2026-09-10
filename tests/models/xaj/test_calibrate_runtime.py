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
    # Observed discharge aligned to the synthetic forcing window.
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
            timeout_seconds=120, network_access=False, max_output_bytes=5_000_000, device="cpu"
        ),
    )
    (workspace / "execution-manifest.json").write_text(request.model_dump_json(), encoding="utf-8")
    return workspace


@pytest.fixture
def calibration_workspace(tmp_path):
    return _prepare(tmp_path / "base")


def _run_calibration(target: Path) -> dict:
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
    return json.loads((target / "output/calibration-result.json").read_text())


def run_calibration_copy(calibration_workspace: Path, suffix: str) -> dict:
    pytest.importorskip("numpy")
    target = calibration_workspace.parent / suffix
    shutil.copytree(calibration_workspace, target)
    scheme_path = target / "input/scheme/scheme.json"
    before = sha256_file(scheme_path)
    result = _run_calibration(target)
    assert sha256_file(scheme_path) == before
    return result


def test_bounded_calibration_is_deterministic(calibration_workspace):
    first = run_calibration_copy(calibration_workspace, "a")
    second = run_calibration_copy(calibration_workspace, "b")
    assert first["strategy_id"] == "xaj-bounded-v1"
    assert first["candidate_parameters"] == second["candidate_parameters"]
    assert first["requested_candidates"] == 32
    assert 0 < first["evaluated_candidates"] <= 32
    assert first["evaluated_candidates"] == second["evaluated_candidates"]
    assert first["model_version"] == "teacher-xaj-v6-20260908"


def test_distributed_calibration_preserves_units_in_candidate_scheme(calibration_workspace):
    pytest.importorskip("numpy")
    target = calibration_workspace.parent / "distributed"
    shutil.copytree(calibration_workspace, target)

    scheme_path = target / "input/scheme/scheme.json"
    scheme = json.loads(scheme_path.read_text(encoding="utf-8"))
    scheme["units"] = [
        {"unit_id": 1, "area_km2": 592.0, "centroid_lon": -115.7, "centroid_lat": 44.1},
        {"unit_id": 2, "area_km2": 592.0, "centroid_lon": -115.5, "centroid_lat": 44.0},
    ]
    scheme_path.write_text(json.dumps(scheme), encoding="utf-8")

    forcing = target / "input/snapshot/forcing.csv"
    forcing.write_text(
        "\n".join(
            [
                "date,unit_1_precipitation_mm_day,unit_1_pet_mm_day,unit_2_precipitation_mm_day,unit_2_pet_mm_day",
                "2025-12-28,1.0,0.5,1.2,0.4",
                "2025-12-29,2.0,0.6,2.2,0.5",
                "2025-12-30,0.0,0.7,0.2,0.6",
                "2025-12-31,3.0,0.8,3.2,0.7",
                "2026-01-01,1.5,0.9,1.7,0.8",
                "2026-01-02,4.0,1.0,4.2,0.9",
                "2026-01-03,0.5,1.1,0.7,1.0",
                "2026-01-04,2.5,1.2,2.7,1.1",
                "",
            ]
        ),
        encoding="utf-8",
    )

    _run_calibration(target)
    candidate = json.loads((target / "output/candidate-scheme.json").read_text())

    assert [unit["unit_id"] for unit in candidate["units"]] == [1, 2]
    assert sum(unit["area_km2"] for unit in candidate["units"]) == pytest.approx(1184.0)
