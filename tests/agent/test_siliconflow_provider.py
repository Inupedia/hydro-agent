from pydantic import SecretStr

from hydro_agent.agent.contracts import (
    ActionCode,
    AgentDecision,
    BudgetSummary,
    HydroContext,
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
        task=TaskSummary(
            task_id="task-1",
            basin_id="camels_13235000",
            phase="B",
            forcing_mode="R",
        ),
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


def test_extract_json_repairs_truncated_object():
    text = (
        "[thinking]\nnext gate\n[/thinking]\n"
        '{"action":"A08_GATE","hypothesis":"MODEL","strategy_id":null,'
        '"rationale_summary":"候选已生成，进入独立验证 Gate。'
    )
    payload = _extract_json(text)
    assert payload["action"] == "A08_GATE"
    assert payload["hypothesis"] == "MODEL"


def test_normalize_preserves_legal_scientific_optimize_choice():
    payload = normalize_decision_payload(
        {
            "action": "A07_OPTIMIZE",
            "hypothesis": "MODEL",
            "strategy_id": "xaj-local-refine-v1",
            "param_groups": ["evap", "runoff"],
            "objective": "water_balance",
            "rationale_summary": "P2 先修多年水量平衡。",
        },
        safe_actions={"A06_DIAGNOSE", "A07_OPTIMIZE", "A08_GATE"},
    )
    assert payload["action"] == "A07_OPTIMIZE"
    assert payload["strategy_id"] == "xaj-local-refine-v1"
    assert payload["param_groups"] == ["evap", "runoff"]
    assert payload["objective"] == "water_balance"


def test_normalize_accepts_all_phase_objectives():
    for objective in ("water_balance", "recession", "routing_event", "joint"):
        payload = normalize_decision_payload(
            {
                "action": "A07_OPTIMIZE",
                "hypothesis": "MODEL",
                "strategy_id": "xaj-bounded-v1",
                "param_groups": ["runoff"],
                "objective": objective,
                "rationale_summary": "phase experiment",
            },
            safe_actions={"A07_OPTIMIZE"},
        )
        assert payload["objective"] == objective


def test_normalize_maps_invalid_hypothesis_into_enum():
    payload = normalize_decision_payload(
        {
            "action": "A01_CHECK_DATA",
            "hypothesis": "Verifying forcing and observation availability has been recorded yet.",
            "strategy_id": None,
            "rationale_summary": "",
        }
    )
    assert payload["hypothesis"] in {h.value for h in ProblemHypothesis}
    assert payload["hypothesis"] != (
        "Verifying forcing and observation availability has been recorded yet."
    )
    assert "Verifying forcing" in payload["rationale_summary"]
    decision = AgentDecision.model_validate(payload)
    assert decision.hypothesis in ProblemHypothesis


def test_normalize_remaps_hydrologist_manual_to_bounded():
    payload = normalize_decision_payload(
        {
            "action": "A07_OPTIMIZE",
            "hypothesis": "MODEL",
            "strategy_id": "xaj-hydrologist-manual-v1",
            "rationale_summary": "try manual",
        },
        safe_actions={"A07_OPTIMIZE"},
    )
    assert payload["strategy_id"] == "xaj-bounded-v1"


def test_fallback_uses_phase_available_objective_instead_of_global_nse():
    from hydro_agent.agent.providers.siliconflow import _fallback_payload

    view = _view().model_copy(
        update={
            "permissions": PermissionSummary(
                safe_actions=(ActionCode.A07_OPTIMIZE,),
                paused=False,
            ),
            "hydro": HydroContext(
                calibration_phase="P2_WATER_BALANCE",
                available_param_groups=("evap", "runoff"),
                available_objectives=("water_balance",),
            ),
        }
    )
    payload = _fallback_payload(view, raw_text="invalid model output")
    assert payload["action"] == "A07_OPTIMIZE"
    assert payload["objective"] == "water_balance"
    assert payload["param_groups"] == ["evap", "runoff"]


def test_siliconflow_provider_injects_activated_skills():
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
    provider.decide(_view())
    system = fake.calls[0]["messages"][0]["content"]
    assert "Activated Agent Skills" in system
    assert "data-check" in system


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
