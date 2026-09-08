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


class StubOptimizeHandler:
    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        return EvidencePacket(
            evidence_id="ev-optimize",
            task_id=task_id,
            action_run_id=None,
            action=ActionCode.A07_OPTIMIZE,
            status="succeeded",
            observations=("optimize_ok",),
            metrics={"objective_value": 0.5},
            new_information_hash="hash-optimize",
        )


def test_new_evidence_changes_next_decision(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repository = HydroRepository(db)
    repository.create_task(task_id="task-1", basin_id="b1", phase="B", forcing_mode="R")
    repository.create_scheme(
        scheme_id="scheme-base",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={"parameters": {"K": 0.7}},
        content_hash="h",
    )
    scripted_provider = ScriptedDecisionProvider()
    scripted_provider.queue(
        [
            AgentDecision(
                action=ActionCode.A05_FORECAST,
                hypothesis=ProblemHypothesis.MODEL,
                strategy_id=None,
                rationale_summary="Run the base forecast.",
            ),
            AgentDecision(
                action=ActionCode.A07_OPTIMIZE,
                hypothesis=ProblemHypothesis.MODEL,
                strategy_id="xaj-bounded-v1",
                rationale_summary="Forecast evidence supports a bounded model test.",
            ),
        ]
    )
    tools = ToolRouter()
    tools.register(ActionCode.A05_FORECAST, StubForecastHandler())
    tools.register(ActionCode.A07_OPTIMIZE, StubOptimizeHandler())
    agent_runtime = AgentRuntime(
        repository,
        provider=scripted_provider,
        tools=tools,
        world_state=WorldStateBuilder(repository),
    )
    first = agent_runtime.run_round("task-1")
    second = agent_runtime.run_round("task-1")
    assert first.evidence_id != second.evidence_id
    assert repository.list_evidence("task-1")[-1].action == "A07_OPTIMIZE"
    assert (
        scripted_provider.seen_views[1].evidence_summary
        != scripted_provider.seen_views[0].evidence_summary
    )
    assert scripted_provider.seen_views[1].evidence_summary[-1].evidence_id == "ev-forecast"
    state = repository.get_task_state("task-1")
    assert state.optimization_cycles_used == 1
    assert state.agent_rounds_used == 2
