from hydro_agent.agent.contracts import (
    ActionCode,
    AgentDecision,
    BudgetSummary,
    ModelSummary,
    PermissionSummary,
    ProblemHypothesis,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.agent.providers.siliconflow import (
    SiliconFlowDecisionProvider,
    _extract_json,
    normalize_decision_payload,
)
from hydro_agent.llm.client import Completion
from hydro_agent.llm.settings import LLMSettings
from pydantic import SecretStr


class FakeClient:
    def __init__(self, content: str):
        self.content = content
        self.calls = []
        self.deltas = []

    def complete(self, messages, *, max_tokens=1024):
        return self.complete_stream(messages, max_tokens=max_tokens, on_delta=None)

    def complete_stream(self, messages, *, max_tokens=1024, on_delta=None):
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        for ch in self.content:
            if on_delta:
                on_delta(ch)
                self.deltas.append(ch)
        return Completion(
            model="zai-org/GLM-5.3",
            content=self.content,
            prompt_tokens=10,
            completion_tokens=20,
            wall_time_seconds=0.01,
        )


def _view() -> WorldStateView:
    return WorldStateView(
        task=TaskSummary(task_id="task-1", basin_id="camels_13235000", phase="B", forcing_mode="R"),
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


def test_extract_json_from_fenced_response():
    payload = _extract_json(
        '```json\n{"action":"A05_FORECAST","hypothesis":"MODEL","strategy_id":null,'
        '"rationale_summary":"forecast now"}\n```'
    )
    assert payload["action"] == "A05_FORECAST"


def test_normalize_does_not_force_freeze_after_resolve():
    payload = normalize_decision_payload(
        {
            "action": "A07_OPTIMIZE",
            "hypothesis": "MODEL",
            "strategy_id": "xaj-peak-bias-v1",
            "rationale_summary": "Gate KEEP 后继续按诊断策略再试一轮",
        },
        safe_actions={
            "A06_DIAGNOSE",
            "A07_OPTIMIZE",
            "A08_GATE",
            "A09_RESOLVE",
            "A10_FREEZE",
        },
        evidence_actions=("A08_GATE", "A09_RESOLVE"),
    )
    assert payload["action"] == "A07_OPTIMIZE"
    assert payload["strategy_id"] == "xaj-peak-bias-v1"
    payload = normalize_decision_payload(
        {
            "action": "A01_CHECK_DATA",
            "hypothesis": "Verifying forcing and observation availability has been recorded yet.",
            "strategy_id": None,
            "rationale_summary": "",
        }
    )
    assert payload["hypothesis"] in {h.value for h in ProblemHypothesis}
    assert payload["hypothesis"] != "Verifying forcing and observation availability has been recorded yet."
    assert "Verifying forcing" in payload["rationale_summary"]
    decision = AgentDecision.model_validate(payload)
    assert decision.hypothesis in ProblemHypothesis


def test_siliconflow_provider_streams_deltas():
    settings = LLMSettings(
        api_key=SecretStr("test-key"),
        model="zai-org/GLM-5.3",
        base_url="https://api.siliconflow.cn/v1",
    )
    text = (
        '{"action":"A05_FORECAST","hypothesis":"MODEL","strategy_id":null,'
        '"rationale_summary":"Run audited base forecast."}'
    )
    fake = FakeClient(text)
    provider = SiliconFlowDecisionProvider(client=fake, settings=settings)
    seen = []
    decision = provider.decide(_view(), on_delta=seen.append)
    assert decision == AgentDecision(
        action=ActionCode.A05_FORECAST,
        hypothesis=ProblemHypothesis.MODEL,
        strategy_id=None,
        rationale_summary="Run audited base forecast.",
    )
    assert "".join(seen) == text
