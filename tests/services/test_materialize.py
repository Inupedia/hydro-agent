import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hydro_agent.data.contracts import SnapshotContext
from hydro_agent.data.lowman import load_normalized_source
from hydro_agent.data.policy import DataAccessPolicy
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.execution.contracts import ExecutionPolicy, ExecutionRequest
from hydro_agent.execution.hashing import sha256_file
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.services.workspace import MaterializingWorkspaceManager

FIXTURE_SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "lowman_reanalysis_source"
PARAMS = {
    "K": 0.75,
    "B": 0.25,
    "IM": 0.06,
    "UM": 20.0,
    "LM": 60.0,
    "DM": 40.0,
    "C": 0.16,
    "SM": 20.0,
    "EX": 1.2,
    "KI": 0.3,
    "KG": 0.4,
    "CS": 0.9,
    "L": 2.0,
    "CI": 0.8,
    "CG": 0.98,
}


@pytest.fixture
def materialize_stack(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    source = load_normalized_source(FIXTURE_SOURCE)
    repo.create_task(
        task_id="task-1",
        basin_id=str(source.basin["basin_id"]),
        phase="B",
        forcing_mode="R",
    )
    repo.create_scheme(
        scheme_id="scheme-base",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={"model_id": "xaj", "warmup_days": 2, "parameters": PARAMS},
        content_hash="scheme-hash",
    )
    snapshot_root = tmp_path / "snapshots"
    builder = SnapshotBuilder(snapshot_root, DataAccessPolicy(), repo)
    builder.build(
        SnapshotContext(
            task_id="task-1",
            snapshot_id="snap-1",
            basin_id=str(source.basin["basin_id"]),
            phase="B",
            forcing_mode="R",
            capability="forecast",
            issue_time=datetime(2020, 5, 1, tzinfo=timezone.utc),
            history_days=2,
        ),
        forcing_rows=list(source.forcing_rows),
        flow_rows=list(source.flow_rows),
        basin=source.basin,
    )
    manager = MaterializingWorkspaceManager(tmp_path / "runs", repo, snapshot_root=snapshot_root)
    request = ExecutionRequest(
        task_id="task-1",
        action_run_id="run-mat-1",
        model_id="xaj",
        capability="forecast",
        data_snapshot_id="snap-1",
        scheme_id="scheme-base",
        issue_time="2020-05-01T00:00:00Z",
        parameters={},
        policy=ExecutionPolicy(
            timeout_seconds=30, network_access=False, max_output_bytes=1_000_000, device="cpu"
        ),
    )
    return repo, manager, request


def test_scheme_materialization_comes_from_repository_not_caller(materialize_stack):
    repo, materializer_manager, request = materialize_stack
    workspace = materializer_manager.create(request)
    scheme = json.loads((workspace / "input/scheme/scheme.json").read_text())
    assert scheme["scheme_id"] == request.scheme_id
    assert scheme["parameters"]["K"] == 0.75
    snapshot = repo.get_snapshot(request.data_snapshot_id)
    for item in snapshot.manifest_json["files"]:
        assert sha256_file(workspace / "input/snapshot" / item["relative_path"]) == item["sha256"]


def test_materialize_strips_workbench_metadata(materialize_stack):
    repo, materializer_manager, request = materialize_stack
    scheme = repo.get_scheme(request.scheme_id)
    scheme.config_json["workbench"] = {
        "allow_optimization": True,
        "start_date": "2020-04-29",
        "end_date": "2020-05-01",
    }
    scheme.config_json["provenance"] = {"source_scheme_id": "scheme-base"}
    workspace = materializer_manager.create(request)
    payload = json.loads((workspace / "input/scheme/scheme.json").read_text())
    assert "workbench" not in payload
    assert "provenance" not in payload
    assert payload["warmup_days"] == 2
    assert payload["scheme_id"] == request.scheme_id
