from datetime import date

import pytest

from hydro_agent.evaluation.service import EvaluationService
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


@pytest.fixture
def repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    repo.create_task(task_id="task-1", basin_id="b1", phase="B", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-frozen-1",
        task_id="task-1",
        model_id="xaj",
        status="frozen",
        config={
            "model_id": "xaj",
            "warmup_days": 2,
            "parameters": {"K": 0.7},
            "provenance": {"source_scheme_id": "scheme-base"},
        },
        content_hash="frozen-hash",
    )
    repo.ensure_task_state("task-1", current_scheme_id="scheme-frozen-1")
    repo.set_task_phase("task-1", "F")
    for day, run_id in ((1, "run-1"), (2, "run-2"), (3, "run-3")):
        issue = f"2020-05-0{day}T00:00:00Z"
        snap = f"snap-{day}"
        repo.create_snapshot(
            snapshot_id=snap,
            task_id="task-1",
            source="fixture",
            available_at=issue,
            manifest={"files": []},
            content_hash=f"h-{day}",
        )
        repo.create_action_run(
            task_id="task-1",
            action_run_id=run_id,
            model_id="xaj",
            capability="forecast",
            data_snapshot_id=snap,
            scheme_id="scheme-frozen-1",
            issue_time=issue,
        )
        repo.create_forecast(
            forecast_id=f"fc-{day}",
            task_id="task-1",
            action_run_id=run_id,
            scheme_id="scheme-frozen-1",
            data_snapshot_id=snap,
            issue_time=issue,
            lead_values={1: 10.0 + day, 2: 11.0 + day, 3: 12.0 + day},
            unit="m3/s",
            artifact_ids=(),
        )
    repo.create_snapshot(
        snapshot_id="snapshot-eval-truth",
        task_id="task-1",
        source="truth",
        available_at="2020-05-10T00:00:00Z",
        manifest={"files": []},
        content_hash="truth-hash",
    )
    return repo


def _truth(_snapshot_id):
    # Enough points for leads 1/2/3 across three issue days.
    return {
        date(2020, 5, 2): 11.0,
        date(2020, 5, 3): 12.0,
        date(2020, 5, 4): 13.0,
        date(2020, 5, 5): 14.0,
        date(2020, 5, 6): 15.0,
    }


@pytest.fixture
def evaluation_service(repository, tmp_path):
    return EvaluationService(repository, snapshot_root=tmp_path, observation_loader=_truth)


def test_evaluation_reads_future_truth_only_in_e_phase(evaluation_service, repository):
    repository.set_task_phase("task-1", "E")
    before_scheme = repository.get_scheme("scheme-frozen-1").content_hash
    result = evaluation_service.evaluate("task-1", "snapshot-eval-truth")
    assert set(result.metrics) >= {"NSE", "KGE", "MAE", "Bias"}
    assert repository.get_scheme("scheme-frozen-1").content_hash == before_scheme


def test_evaluation_refuses_truth_snapshot_outside_e_phase(evaluation_service, repository):
    with pytest.raises(ValueError, match="E phase"):
        evaluation_service.evaluate("task-1", "snapshot-eval-truth")
