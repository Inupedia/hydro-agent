from dataclasses import dataclass

import pytest

from hydro_agent.agent.contracts import ActionCode, AgentDecision, ProblemHypothesis
from hydro_agent.agent.tools import ForecastHandler, ToolRouter, ToolUnavailable
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
