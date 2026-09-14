from datetime import date

import pytest

from hydro_agent.data.policy import DataAccessViolation
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.replay.planner import ReplayPlanner


class FakeResolver:
    def __init__(self, mapping):
        self.mapping = mapping

    def resolve(self, task_id, capability, issue_time):
        key = issue_time[:10]
        if key not in self.mapping:
            raise DataAccessViolation("no legal forcing")
        return self.mapping[key]


@pytest.fixture
def repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    repo.create_task(task_id="task-1", basin_id="b1", phase="F", forcing_mode="F")
    repo.create_scheme(
        scheme_id="scheme-frozen-1",
        task_id="task-1",
        model_id="xaj",
        status="frozen",
        config={"model_id": "xaj", "warmup_days": 2, "parameters": {"K": 0.7}},
        content_hash="frozen-hash",
    )
    repo.ensure_task_state("task-1", current_scheme_id="scheme-frozen-1")
    return repo


def test_f_mode_plan_uses_only_snapshot_available_by_each_issue_time(repository):
    planner = ReplayPlanner(
        repository,
        resolver=FakeResolver(
            {"2025-05-01": "snap-0501", "2025-05-02": "snap-0502", "2025-05-03": "snap-0503"}
        ),
    )
    plan = planner.plan("task-1", date(2025, 5, 1), date(2025, 5, 3))
    assert [case.issue_time.date().isoformat() for case in plan.cases] == [
        "2025-05-01",
        "2025-05-02",
        "2025-05-03",
    ]
    assert [case.data_snapshot_id for case in plan.cases] == [
        "snap-0501",
        "snap-0502",
        "snap-0503",
    ]


def test_f_mode_plan_rejects_day_without_legal_forecast_snapshot(repository):
    planner = ReplayPlanner(
        repository,
        resolver=FakeResolver({"2025-05-01": "snap-0501", "2025-05-03": "snap-0503"}),
    )
    with pytest.raises(DataAccessViolation, match="no legal forcing"):
        planner.plan("task-1", date(2025, 5, 1), date(2025, 5, 3))


def test_sampled_plan_can_span_long_final_window_without_enumerating_every_day(repository):
    issue_days = (date(2025, 1, 1), date(2025, 6, 1), date(2025, 12, 28))
    planner = ReplayPlanner(
        repository,
        resolver=FakeResolver(
            {day.isoformat(): f"snap-{index}" for index, day in enumerate(issue_days)}
        ),
    )
    plan = planner.plan_issues("task-1", issue_days)
    assert tuple(case.issue_time.date() for case in plan.cases) == issue_days
    assert tuple(case.data_snapshot_id for case in plan.cases) == (
        "snap-0",
        "snap-1",
        "snap-2",
    )


def test_sampled_plan_rejects_duplicate_or_unsorted_issue_days(repository):
    planner = ReplayPlanner(repository, resolver=FakeResolver({}))
    with pytest.raises(ValueError, match="duplicate"):
        planner.plan_issues("task-1", (date(2025, 1, 1), date(2025, 1, 1)))
    with pytest.raises(ValueError, match="sorted"):
        planner.plan_issues("task-1", (date(2025, 1, 2), date(2025, 1, 1)))
