from hydro_agent.agent.contracts import (
    ActionCode,
    AgentDecision,
    BudgetSummary,
    ModelSummary,
    PermissionSummary,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.agent.providers.openai_responses import OpenAIResponsesDecisionProvider


class FakeResponsesAPI:
    def __init__(self):
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)

        class Response:
            output_parsed = AgentDecision(
                action=ActionCode.A05_FORECAST,
                hypothesis="MODEL",
                rationale_summary="Choose a forecast from safe actions.",
            )

        return Response()


class FakeOpenAIClient:
    def __init__(self):
        self.responses = FakeResponsesAPI()


def test_provider_uses_structured_agent_decision():
    fake_openai_client = FakeOpenAIClient()
    world_view = WorldStateView(
        task=TaskSummary(task_id="task-1", basin_id="b1", phase="B", forcing_mode="R"),
        model=ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate")),
        scheme=SchemeSummary(scheme_id="scheme-base", status="base", content_hash="h"),
        permissions=PermissionSummary(safe_actions=(ActionCode.A05_FORECAST,), paused=False),
        budget=BudgetSummary(
            agent_rounds_remaining=20,
            optimization_cycles_remaining=4,
            max_agent_rounds=20,
            max_optimization_cycles=4,
        ),
    )
    provider = OpenAIResponsesDecisionProvider(model="test-model", client=fake_openai_client)
    decision = provider.decide(world_view)
    assert decision.action == ActionCode.A05_FORECAST
    call = fake_openai_client.responses.calls[0]
    assert call["text_format"] is AgentDecision
