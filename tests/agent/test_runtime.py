from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket, ProblemHypothesis
from hydro_agent.agent.providers.scripted import ScriptedDecisionProvider
from hydro_agent.agent.runtime import AgentRuntime
from hydro_agent.agent.tools import ToolRouter
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


class StubForecastHandler:
    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        return EvidencePacket(
            evidence_id="ev-forecast",
            task_id=task_id,
            action_run_id=None,
            action=ActionCode.A05_FORECAST,
            status="succeeded",
            observations=("forecast_ok",),
            metrics={"lead_1": 1.0},
            new_information_hash="hash-forecast",
        )


def test_agent_runtime_uses_langgraph_orchestrator():
    assert AgentRuntime.orchestrator == "langgraph"


def test_runtime_persists_decision_and_evidence(tmp_path):
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
    provider = ScriptedDecisionProvider(
        [
            AgentDecision(
                action=ActionCode.A05_FORECAST,
                hypothesis=ProblemHypothesis.MODEL,
                rationale_summary="Run the base forecast.",
            )
        ]
    )
    router = ToolRouter()
    router.register(ActionCode.A05_FORECAST, StubForecastHandler())
    runtime = AgentRuntime(
        repo, provider=provider, tools=router, world_state=WorldStateBuilder(repo)
    )
    packet = runtime.run_round("task-1")
    assert packet.evidence_id == "ev-forecast"
    assert repo.list_evidence("task-1")[-1].action == "A05_FORECAST"
    state = repo.get_task_state("task-1")
    assert state.agent_rounds_used == 1
    assert state.last_information_hash == "hash-forecast"
