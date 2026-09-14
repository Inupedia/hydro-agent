from dataclasses import dataclass

import pytest

from hydro_agent.agent.contracts import (
    ActionCode,
    AgentDecision,
    EvidencePacket,
    ProblemHypothesis,
)
from hydro_agent.agent.tools import ForecastHandler, FreezeToolHandler, ToolRouter, ToolUnavailable
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


class SpyFreezeService:
    def __init__(self):
        self.calls = 0

    def freeze(self, *, task_id, source_scheme_id):
        self.calls += 1
        return f"frozen-{source_scheme_id}"


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


def _freeze_decision():
    return AgentDecision(
        action=ActionCode.A10_FREEZE,
        hypothesis=ProblemHypothesis.MODEL,
        rationale_summary="Close out calibration.",
    )


def _add_resolve(repository, *, qualification_status: str, status: str = "KEEP"):
    repository.add_evidence(
        EvidencePacket(
            evidence_id=f"ev-resolve-{qualification_status.lower()}",
            task_id="task-1",
            action=ActionCode.A09_RESOLVE,
            status=status,  # type: ignore[arg-type]
            observations=(f"qualification_status={qualification_status}",),
            gates={
                "status": status,
                "qualification_status": qualification_status,
            },
            new_information_hash=f"hash-{qualification_status.lower()}",
        )
    )


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


def test_freeze_blocks_unqualified_resolve_without_consuming_final_test(repository):
    _add_resolve(repository, qualification_status="UNQUALIFIED")
    freeze = SpyFreezeService()
    packet = FreezeToolHandler(repository, freeze_service=freeze).execute(
        "task-1", _freeze_decision()
    )

    assert packet.status == "blocked"
    assert "hydrologist_manual_required" in packet.observations
    assert "calibration_handover_required" in packet.observations
    assert "final_test_not_consumed=true" in packet.observations
    assert packet.gates["handover_required"] == "true"
    assert freeze.calls == 0
    assert repository.get_task("task-1").phase == "B"


def test_freeze_allows_qualified_resolve(repository):
    _add_resolve(repository, qualification_status="QUALIFIED", status="ACCEPT")
    freeze = SpyFreezeService()
    packet = FreezeToolHandler(repository, freeze_service=freeze).execute(
        "task-1", _freeze_decision()
    )

    assert packet.status == "succeeded"
    assert freeze.calls == 1
    assert repository.get_task("task-1").phase == "F"
