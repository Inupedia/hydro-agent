from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from hydro_agent.data.contracts import SnapshotContext
from hydro_agent.data.lowman import load_normalized_source
from hydro_agent.data.policy import DataAccessPolicy
from hydro_agent.data.snapshot import SnapshotBuilder
from hydro_agent.execution.contracts import ExecutionPolicy, ExecutionResult
from hydro_agent.execution.registry import RuntimeRegistry
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.models.xaj.adapter import XajRuntimeAdapter
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.services.forecast import ForecastExecutionFailed, ForecastService
from hydro_agent.services.snapshots import SnapshotResolver
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
ISSUE = "2020-05-01T00:00:00Z"
cpu_policy = ExecutionPolicy(
    timeout_seconds=120, network_access=False, max_output_bytes=5_000_000, device="cpu"
)


@pytest.fixture
def seeded_repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    repo.create_task(task_id="task-1", basin_id="camels_13235000", phase="B", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-base",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={"model_id": "xaj", "warmup_days": 2, "parameters": PARAMS},
        content_hash="scheme-hash",
    )
    repo.create_snapshot(
        snapshot_id="snap-1",
        task_id="task-1",
        source="fixture",
        available_at=ISSUE,
        manifest={"files": [], "context": {"basin_id": "camels_13235000"}},
        content_hash="snap-hash",
    )
    repo.create_action_run(
        task_id="task-1",
        action_run_id="run-1",
        model_id="xaj",
        capability="forecast",
        data_snapshot_id="snap-1",
        scheme_id="scheme-base",
        issue_time=ISSUE,
    )
    return repo


def test_successful_forecast_record_is_immutable_and_traceable(seeded_repository):
    seeded_repository.create_forecast(
        forecast_id="fc-1",
        task_id="task-1",
        action_run_id="run-1",
        scheme_id="scheme-base",
        data_snapshot_id="snap-1",
        issue_time=ISSUE,
        lead_values={1: 10.0, 2: 11.0, 3: 12.0},
        unit="m3/s",
        artifact_ids=("artifact-1",),
    )
    row = seeded_repository.get_forecast("fc-1")
    assert row.scheme_id == "scheme-base"
    assert row.data_snapshot_id == "snap-1"
    assert row.lead_values_json == {"1": 10.0, "2": 11.0, "3": 12.0}
    assert not hasattr(seeded_repository, "update_forecast")
    with pytest.raises(IntegrityError, match="immutable record"):
        with seeded_repository.database.session() as session:
            session.execute(text("UPDATE forecasts SET unit='bad'"))


@pytest.fixture
def forecast_service(tmp_path):
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
            snapshot_id="snap-legal-0501",
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
    resolver = SnapshotResolver(repo, builder=builder, source=source, history_days=2)
    workspaces = MaterializingWorkspaceManager(tmp_path / "runs", repo, snapshot_root=snapshot_root)
    registry = RuntimeRegistry()
    registry.register(XajRuntimeAdapter())
    runner = SandboxRunner(registry, workspaces)
    return repo, ForecastService(repo, resolver=resolver, runner=runner, model_id="xaj")


def test_forecast_service_owns_full_audited_execution(forecast_service):
    repository, service = forecast_service
    forecast = service.forecast(
        task_id="task-1",
        scheme_id="scheme-base",
        issue_time=ISSUE,
        policy=cpu_policy,
    )
    action = repository.get_action_run(forecast.action_run_id)
    assert action.capability == "forecast"
    assert action.status == "succeeded"
    assert repository.get_cost(action.action_run_id).wall_time_seconds >= 0
    assert repository.get_forecast(forecast.forecast_id).scheme_id == "scheme-base"
    assert set(forecast.lead_values) == {1, 2, 3}


def test_forecast_service_timeout_persists_without_forecast_row(forecast_service, monkeypatch):
    repository, service = forecast_service

    def timed_out(request):
        workspace = service.runner.workspaces.create(request)
        (workspace / "logs/stdout.log").write_text("", encoding="utf-8")
        (workspace / "logs/stderr.log").write_text("", encoding="utf-8")
        return ExecutionResult(
            action_run_id=request.action_run_id,
            status="timed_out",
            exit_code=None,
            wall_time_seconds=1.0,
            peak_memory_bytes=1,
            stdout_artifact="logs/stdout.log",
            stderr_artifact="logs/stderr.log",
            output_artifacts=(),
            result_payload={},
            error_code="timeout",
        )

    monkeypatch.setattr(service.runner, "run", timed_out)
    with pytest.raises(ForecastExecutionFailed):
        service.forecast(
            task_id="task-1",
            scheme_id="scheme-base",
            issue_time=ISSUE,
            policy=cpu_policy,
        )
    assert repository.list_forecasts("task-1") == []
    # The failed ActionRun id is application-generated; ensure no forecast leaked.
    assert all(row.task_id != "task-1" for row in repository.list_forecasts())
