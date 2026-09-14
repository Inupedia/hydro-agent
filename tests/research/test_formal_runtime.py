from datetime import date, datetime
from types import SimpleNamespace

from hydro_agent.agent.contracts import ActionCode, AgentDecision, ProblemHypothesis
from hydro_agent.research.formal_runtime import (
    PreregisteredReplayHandler,
    PreregisteredValidationGate,
    _continuous_hydro_series,
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


def test_formal_gate_uses_continuous_hydro_for_qualification(monkeypatch):
    base = SimpleNamespace(scheme_id="base", primary_score=0.1, leads=())
    candidate = SimpleNamespace(scheme_id="candidate", primary_score=0.2, leads=())
    sampled_hydro = object()
    continuous_hydro = object()

    monkeypatch.setattr(
        "hydro_agent.workbench.validation_gate.RealValidationGate.bundles",
        lambda self, task_id: (base, candidate, sampled_hydro),
    )
    monkeypatch.setattr(
        "hydro_agent.research.formal_runtime._continuous_hydro_series",
        lambda **kwargs: continuous_hydro,
    )
    repository = SimpleNamespace(
        get_scheme=lambda scheme_id: SimpleNamespace(
            scheme_id=scheme_id,
            config_json={"model_id": "xaj", "warmup_days": 1, "parameters": {}},
        )
    )
    gate = PreregisteredValidationGate(
        repository=repository,
        forecast_service=RecordingForecastService(),
        source=SimpleNamespace(),
        policy=SimpleNamespace(),
        task_configs={
            "task-1": {
                "development_start_date": "1999-01-01",
                "development_end_date": "2001-12-31",
                "development_rolling_issue_limit": 4,
            }
        },
    )

    got_base, got_candidate, got_hydro = gate.bundles("task-1")

    assert got_base is base
    assert got_candidate is candidate
    assert got_hydro is continuous_hydro
    assert got_hydro is not sampled_hydro


def test_continuous_hydro_series_preserves_real_chronology(monkeypatch):
    params = {
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
    days = [date(1998, 12, 31), date(1999, 1, 1), date(1999, 1, 2), date(1999, 1, 3)]
    source = SimpleNamespace(
        basin={"basin_id": "b", "area_km2": 1000.0},
        forcing_rows=[
            SimpleNamespace(valid_date=day, precipitation_mm_day=1.0, pet_mm_day=0.5)
            for day in days
        ],
        flow_rows=[
            SimpleNamespace(valid_date=day, discharge_m3s=10.0 + i, eligible_for_scoring=True)
            for i, day in enumerate(days[1:])
        ],
    )
    monkeypatch.setattr(
        "hydro_agent.research.formal_runtime.simulate",
        lambda scheme, basin, forcing, include_warmup: [1.0, 11.0, 12.0, 13.0],
    )

    series = _continuous_hydro_series(
        source=source,
        scheme_config={"warmup_days": 1, "parameters": params},
        start=date(1999, 1, 1),
        end=date(1999, 1, 3),
    )

    assert series.obs == (10.0, 11.0, 12.0)
    assert series.sim == (11.0, 12.0, 13.0)
    assert [stamp.date() for stamp in series.times or ()] == days[1:]
    assert series.area_km2 == 1000.0
