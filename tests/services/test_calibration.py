from datetime import datetime, timezone
from pathlib import Path

import pytest

from hydro_agent.data.contracts import SnapshotContext
from hydro_agent.data.lowman import load_normalized_source
from hydro_agent.data.policy import DataAccessPolicy
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.execution.contracts import ExecutionPolicy
from hydro_agent.execution.registry import RuntimeRegistry
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.models.xaj.adapter import XajRuntimeAdapter
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.services.calibration import CalibrationService
from hydro_agent.services.workspace import MaterializingWorkspaceManager

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
FIXTURE_SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "lowman_reanalysis_source"
cpu_policy = ExecutionPolicy(
    timeout_seconds=120, network_access=False, max_output_bytes=5_000_000, device="cpu"
)


@pytest.fixture
def calibration_service(tmp_path):
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
        config={"model_id": "xaj", "warmup_days": 1, "parameters": PARAMS},
        content_hash="scheme-hash",
    )
    snapshot_root = tmp_path / "snapshots"
    builder = SnapshotBuilder(snapshot_root, DataAccessPolicy(), repo)
    for snapshot_id in ("snap-cal", "snap-val"):
        builder.build(
            SnapshotContext(
                task_id="task-1",
                snapshot_id=snapshot_id,
                basin_id=str(source.basin["basin_id"]),
                phase="B",
                forcing_mode="R",
                capability="forecast",
                issue_time=datetime(2020, 5, 1, tzinfo=timezone.utc),
                history_days=4,
            ),
            forcing_rows=list(source.forcing_rows),
            flow_rows=list(source.flow_rows),
            basin=source.basin,
        )
    workspaces = MaterializingWorkspaceManager(tmp_path / "runs", repo, snapshot_root=snapshot_root)
    registry = RuntimeRegistry()
    registry.register(XajRuntimeAdapter())
    runner = SandboxRunner(registry, workspaces)
    return repo, CalibrationService(repo, runner=runner)


def test_calibration_service_returns_payload_without_registering_candidate(calibration_service):
    repository, service = calibration_service
    outcome = service.calibrate(
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
