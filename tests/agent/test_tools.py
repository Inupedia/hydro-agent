from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from hydro_agent.agent.contracts import ActionCode, AgentDecision, ProblemHypothesis
from hydro_agent.agent.tools import ForecastHandler, OptimizeHandler, ToolRouter, ToolUnavailable
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


@dataclass
class FakeForecast:
    forecast_id: str = "fc-1"
    action_run_id: str = "run-fc-1"
    lead_values: dict | None = None
    artifact_ids: tuple = ("a1",)

    def __post_init__(self):
        if self.lead_values is None:
            self.lead_values = {1: 1.0, 2: 2.0, 3: 3.0}


class SpyForecastService:
    def __init__(self):
        self.calls = 0

    def forecast(self, **kwargs):
        self.calls += 1
        return FakeForecast()


class FakeCalibrationService:
    def calibrate(self, **kwargs):
        return SimpleNamespace(
            action_run_id="run-cal-1",
            strategy_id="xaj-bounded-v1",
            base_scheme_id="scheme-base",
            candidate_parameters={"K": 0.8},
            objective_value=0.42,
            objective="nse",
            param_groups=("evap",),
            artifact_ids=("cal-result",),
            result_payload={
                "optimizer": "dds",
                "evaluation_budget": 64,
                "model_evaluations": 61,
                "execution_attempts": 2,
                "resume_attempts": 1,
                "restored_model_evaluations": 17,
                "resumed_from_workspace": True,
                "objective_metric": "nse",
                "search_boundary_evidence": {
                    "local_hits": [],
                    "absolute_hits": [],
                },
            },
        )


class FakeCandidateService:
    def __init__(self):
        self.payload = None

    def register_candidate(self, *, base_scheme_id, action_run_id, calibration_payload):
        self.payload = calibration_payload
        return "scheme-candidate"


@pytest.fixture
def repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    repo.create_task(task_id="task-1", basin_id="b1", phase="B", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-base",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={"parameters": {"K": 0.7}},
        content_hash="h",
    )
    repo.ensure_task_state("task-1", current_scheme_id="scheme-base")
    return repo


@pytest.fixture
def spy_forecast_service():
    return SpyForecastService()


@pytest.fixture
def forecast_decision():
    return AgentDecision(
        action=ActionCode.A05_FORECAST,
        hypothesis=ProblemHypothesis.MODEL,
        rationale_summary="Run the base forecast.",
    )


@pytest.fixture
def tool_router(repository, spy_forecast_service):
    router = ToolRouter()
    router.register(
        ActionCode.A05_FORECAST,
        ForecastHandler(
            repository,
            forecast_service=spy_forecast_service,
            issue_time="2020-05-01T00:00:00Z",
            policy=object(),
        ),
    )
    return router


def test_forecast_action_calls_forecast_service_not_sandbox_directly(
    tool_router, forecast_decision, spy_forecast_service
):
    evidence = tool_router.execute("task-1", forecast_decision)
    assert spy_forecast_service.calls == 1
    assert evidence.action == ActionCode.A05_FORECAST
    assert evidence.status == "succeeded"


def test_unregistered_action_raises_tool_unavailable(tool_router):
    decision = AgentDecision(
        action=ActionCode.A06_DIAGNOSE,
        hypothesis=ProblemHypothesis.UNKNOWN,
        rationale_summary="Diagnose without a registered tool.",
    )
    with pytest.raises(ToolUnavailable):
        tool_router.execute("task-1", decision)


def test_optimize_evidence_exposes_resume_audit_fields(repository):
    candidates = FakeCandidateService()
    handler = OptimizeHandler(
        repository,
        calibration_service=FakeCalibrationService(),
        candidate_service=candidates,
        calibration_snapshot_id="snap-cal",
        validation_snapshot_id=None,
        policy=object(),
    )
    decision = AgentDecision(
        action=ActionCode.A07_OPTIMIZE,
        hypothesis=ProblemHypothesis.MODEL,
        strategy_id="xaj-bounded-v1",
        param_groups=("evap",),
        objective="nse",
        rationale_summary="Run the preregistered calibration experiment.",
    )

    packet = handler.execute("task-1", decision)

    assert packet.status == "succeeded"
    assert packet.gates["execution_attempts"] == "2"
    assert packet.gates["resume_attempts"] == "1"
    assert packet.gates["restored_model_evaluations"] == "17"
    assert packet.gates["resumed_from_workspace"] == "true"
    assert packet.metrics["resume_attempts"] == 1.0
    assert "resumed_from_workspace=true" in packet.observations
    assert candidates.payload["resume_attempts"] == 1
    assert candidates.payload["resumed_from_workspace"] is True
