from datetime import date, datetime
from types import SimpleNamespace

from hydro_agent.agent.contracts import ActionCode, AgentDecision, ProblemHypothesis
from hydro_agent.research.formal_runtime import (
    PreregisteredReplayHandler,
    PreregisteredValidationGate,
)
from hydro_agent.workbench.validation_gate import ValidationWindow


class RecordingForecastService:
    def __init__(self):
        self.calls = []

    def forecast(self, **kwargs):
        self.calls.append(kwargs)


class RecordingPlanner:
    def __init__(self):
        self.issue_days = None

    def plan_issues(self, task_id, issue_days):
        self.issue_days = tuple(issue_days)
        return SimpleNamespace(task_id=task_id, scheme_id="frozen-1", cases=())


class RecordingReplayService:
    def execute(self, plan):
        return (
            SimpleNamespace(forecast_id="fc-1"),
            SimpleNamespace(forecast_id="fc-2"),
            SimpleNamespace(forecast_id="fc-3"),
        )


class RecordingRepository:
    def __init__(self):
        self.phase = "F"

    def get_task(self, task_id):
        return SimpleNamespace(phase=self.phase)

    def set_task_phase(self, task_id, phase):
        self.phase = phase


def test_formal_gate_uses_only_preregistered_full_lead_safe_issue_days():
    forecast = RecordingForecastService()
    gate = PreregisteredValidationGate(
        repository=SimpleNamespace(),
        forecast_service=forecast,
        source=SimpleNamespace(),
        policy=SimpleNamespace(),
        task_configs={"task-1": {"development_rolling_issue_limit": 4}},
    )
    window = ValidationWindow(start=date(1999, 1, 1), end=date(2001, 12, 31))
    gate.ensure_forecasts("task-1", "scheme-1", window)

    issue_days = tuple(
        datetime.fromisoformat(call["issue_time"].replace("Z", "+00:00")).date()
        for call in forecast.calls
    )
    assert len(issue_days) == 4
    assert issue_days[0] == date(1999, 1, 1)
    assert issue_days[-1] == date(2001, 12, 28)
    assert all((window.end - day).days >= 3 for day in issue_days)


def test_formal_replay_samples_final_window_and_advances_to_read_only_evaluation():
    repository = RecordingRepository()
    planner = RecordingPlanner()
    kernel = SimpleNamespace(
        repository=repository,
        planner=planner,
        replay_service=RecordingReplayService(),
    )
    handler = PreregisteredReplayHandler(
        kernel,
        {
            "task-1": {
                "final_test_start_date": "2002-01-01",
                "final_test_end_date": "2003-12-28",
                "final_test_rolling_issue_limit": 3,
            }
        },
    )
    packet = handler.execute(
        "task-1",
        AgentDecision(
            action=ActionCode.A11_REPLAY,
            hypothesis=ProblemHypothesis.MODEL,
            rationale_summary="formal final replay",
        ),
    )

    assert planner.issue_days is not None
    assert len(planner.issue_days) == 3
    assert planner.issue_days[0] == date(2002, 1, 1)
    assert planner.issue_days[-1] == date(2003, 12, 25)
    assert repository.phase == "E"
    assert packet.status == "succeeded"
    assert packet.metrics["rolling_issue_count"] == 3.0
    assert "continuous_final_test_window_preserved=true" in packet.observations
