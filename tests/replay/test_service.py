from datetime import datetime, timezone

import pytest

from hydro_agent.execution.contracts import ExecutionPolicy
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.replay.contracts import ReplayCase, ReplayPlan
from hydro_agent.replay.service import ReplayService, ReplayStopped
from hydro_agent.services.contracts import ForecastRecord
from hydro_agent.services.forecast import ForecastExecutionFailed

ISSUE = "2025-05-01T00:00:00Z"
POLICY = ExecutionPolicy(
    timeout_seconds=1, network_access=False, max_output_bytes=1024, device="cpu"
)


@pytest.fixture
def seeded_repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    repo.create_task(task_id="task-1", basin_id="b1", phase="F", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-frozen-1",
        task_id="task-1",
        model_id="xaj",
        status="frozen",
        config={"model_id": "xaj", "warmup_days": 2, "parameters": {"K": 0.7}},
        content_hash="frozen-hash",
    )
    repo.create_snapshot(
        snapshot_id="snapshot-issue-1",
        task_id="task-1",
        source="fixture",
        available_at=ISSUE,
        manifest={"files": []},
        content_hash="snap-hash",
    )
    repo.create_action_run(
        task_id="task-1",
        action_run_id="run-forecast-1",
        model_id="xaj",
        capability="forecast",
        data_snapshot_id="snapshot-issue-1",
        scheme_id="scheme-frozen-1",
        issue_time=ISSUE,
    )
    repo.ensure_task_state("task-1", current_scheme_id="scheme-frozen-1")
    return repo


def test_replay_lookup_returns_exact_existing_forecast(seeded_repository):
    seeded_repository.create_forecast(
        forecast_id="fc-1",
        task_id="task-1",
        action_run_id="run-forecast-1",
        scheme_id="scheme-frozen-1",
        data_snapshot_id="snapshot-issue-1",
        issue_time=ISSUE,
        lead_values={1: 10.0, 2: 11.0, 3: 12.0},
        unit="m3/s",
        artifact_ids=("artifact-forecast-1",),
    )
    row = seeded_repository.get_forecast_for_issue(
        "task-1", "scheme-frozen-1", "2025-05-01T00:00:00Z"
    )
    assert row.forecast_id == "fc-1"


class SpyForecastService:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on or set()

    def forecast(self, *, task_id, scheme_id, issue_time, policy):
        self.calls.append(issue_time)
        if issue_time in self.fail_on:
            raise ForecastExecutionFailed("run-fail", "failed", "boom")
        issue = datetime.fromisoformat(issue_time.replace("Z", "+00:00"))
        return ForecastRecord(
            forecast_id=f"fc-{issue_time[:10]}",
            task_id=task_id,
            action_run_id=f"run-{issue_time[:10]}",
            scheme_id=scheme_id,
            data_snapshot_id=f"snap-{issue_time[:10]}",
            issue_time=issue,
            lead_values={1: 1.0, 2: 2.0, 3: 3.0},
            unit="m3/s",
            artifact_ids=(),
        )


def _plan(days):
    cases = tuple(
        ReplayCase(
            issue_time=datetime(2025, 5, day, tzinfo=timezone.utc),
            data_snapshot_id=f"snap-2025-05-0{day}",
        )
        for day in days
    )
    return ReplayPlan(task_id="task-1", scheme_id="scheme-frozen-1", forcing_mode="R", cases=cases)


def test_replay_uses_same_frozen_scheme_for_every_issue(seeded_repository):
    spy = SpyForecastService()
    service = ReplayService(seeded_repository, forecast_service=spy, policy=POLICY)
    forecasts = service.execute(_plan([1, 2, 3]))
    assert len(forecasts) == 3
    assert {forecast.scheme_id for forecast in forecasts} == {"scheme-frozen-1"}
    assert [forecast.issue_time for forecast in forecasts] == sorted(
        f.issue_time for f in forecasts
    )
    assert seeded_repository.get_task_state("task-1").optimization_cycles_used == 0


def test_replay_stops_after_failed_case(seeded_repository):
    spy = SpyForecastService(fail_on={"2025-05-02T00:00:00Z"})
    service = ReplayService(seeded_repository, forecast_service=spy, policy=POLICY)
    with pytest.raises(ReplayStopped) as exc:
        service.execute(_plan([1, 2, 3]))
    assert len(exc.value.completed) == 1
    assert spy.calls == ["2025-05-01T00:00:00Z", "2025-05-02T00:00:00Z"]
