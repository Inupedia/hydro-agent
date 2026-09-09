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
    _nse_calibration_progress,
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


def test_extract_json_repairs_truncated_object():
    text = (
        '[thinking]\nnext gate\n[/thinking]\n'
        '{"action":"A08_GATE","hypothesis":"MODEL","strategy_id":null,'
        '"rationale_summary":"候选已生成，进入独立验证 Gate。'
    )
    payload = _extract_json(text)
    assert payload["action"] == "A08_GATE"
    assert payload["hypothesis"] == "MODEL"


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


def test_nse_progress_calibrates_when_nse_poor():
    from hydro_agent.agent.contracts import EvidenceSummary, HydroContext

    view = _view().model_copy(
        update={
            "permissions": PermissionSummary(
                safe_actions=(
                    ActionCode.A06_DIAGNOSE,
                    ActionCode.A07_OPTIMIZE,
                    ActionCode.A08_GATE,
                    ActionCode.A10_FREEZE,
                ),
                paused=False,
            ),
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="ev-1",
                    action=ActionCode.A06_DIAGNOSE,
                    status="succeeded",
                    new_information_hash="h1",
                    metrics={"nse": -1.2},
                ),
            ),
            "hydro": HydroContext(
                diagnosis={
                    "hypothesis": "MODEL",
                    "recommended_action": "A07_OPTIMIZE",
                    "recommended_strategy_id": "xaj-peak-bias-v1",
                    "metrics": {"nse": -1.2},
                }
            ),
        }
    )
    out = _nse_calibration_progress(
        view,
        {
            "action": "A10_FREEZE",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "looks ok",
        },
        safe_actions={"A07_OPTIMIZE", "A10_FREEZE", "A08_GATE"},
    )
    assert out["action"] == "A07_OPTIMIZE"
    assert out["strategy_id"] == "xaj-peak-bias-v1"


def test_nse_progress_freezes_when_nse_good_enough():
    from hydro_agent.agent.contracts import EvidenceSummary, HydroContext

    view = _view().model_copy(
        update={
            "permissions": PermissionSummary(
                safe_actions=(ActionCode.A07_OPTIMIZE, ActionCode.A10_FREEZE),
                paused=False,
            ),
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="ev-1",
                    action=ActionCode.A06_DIAGNOSE,
                    status="succeeded",
                    new_information_hash="h1",
                    metrics={"nse": 0.72},
                ),
            ),
            "hydro": HydroContext(diagnosis={"metrics": {"nse": 0.72}}),
        }
    )
    out = _nse_calibration_progress(
        view,
        {"action": "A07_OPTIMIZE", "hypothesis": "MODEL", "strategy_id": "xaj-bounded-v1", "rationale_summary": "x"},
        safe_actions={"A07_OPTIMIZE", "A10_FREEZE"},
    )
    assert out["action"] == "A10_FREEZE"


def test_nse_progress_respects_custom_threshold():
    from hydro_agent.agent.contracts import EvidenceSummary, HydroContext

    view = _view().model_copy(
        update={
            "permissions": PermissionSummary(
                safe_actions=(ActionCode.A07_OPTIMIZE, ActionCode.A10_FREEZE),
                paused=False,
            ),
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="ev-1",
                    action=ActionCode.A06_DIAGNOSE,
                    status="succeeded",
                    new_information_hash="h1",
                    metrics={"nse": 0.45},
                ),
            ),
            "hydro": HydroContext(diagnosis={"metrics": {"nse": 0.45}}),
        }
    )
    # 0.45 < 0.5 → still calibrate
    out_low = _nse_calibration_progress(
        view,
        {"action": "A10_FREEZE", "hypothesis": "MODEL", "strategy_id": None, "rationale_summary": "x"},
        safe_actions={"A07_OPTIMIZE", "A10_FREEZE"},
        nse_good_enough=0.5,
    )
    assert out_low["action"] == "A07_OPTIMIZE"
    # 0.45 >= 0.4 → freeze when threshold lowered
    out_high = _nse_calibration_progress(
        view,
        {"action": "A07_OPTIMIZE", "hypothesis": "MODEL", "strategy_id": "xaj-bounded-v1", "rationale_summary": "x"},
        safe_actions={"A07_OPTIMIZE", "A10_FREEZE"},
        nse_good_enough=0.4,
    )
    assert out_high["action"] == "A10_FREEZE"


def test_nse_progress_freezes_when_opt_budget_exhausted_after_keep():
    from hydro_agent.agent.contracts import EvidenceSummary, HydroContext

    view = _view().model_copy(
        update={
            "budget": BudgetSummary(
                agent_rounds_remaining=8,
                optimization_cycles_remaining=0,
                max_agent_rounds=20,
                max_optimization_cycles=4,
            ),
            "permissions": PermissionSummary(
                safe_actions=(ActionCode.A07_OPTIMIZE, ActionCode.A10_FREEZE, ActionCode.A08_GATE),
                paused=False,
            ),
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="ev-opt",
                    action=ActionCode.A07_OPTIMIZE,
                    status="succeeded",
                    new_information_hash="h-opt",
                ),
                EvidenceSummary(
                    evidence_id="ev-gate",
                    action=ActionCode.A08_GATE,
                    status="KEEP",
                    new_information_hash="h-gate",
                ),
                EvidenceSummary(
                    evidence_id="ev-resolve",
                    action=ActionCode.A09_RESOLVE,
                    status="succeeded",
                    new_information_hash="h-resolve",
                ),
            ),
            "hydro": HydroContext(diagnosis={"metrics": {"nse": 0.1}}),
        }
    )
    out = _nse_calibration_progress(
        view,
        {
            "action": "A01_CHECK_DATA",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "wander",
        },
        # A07 not safe once opt cycles are gone — mirrors PermissionGate.
        safe_actions={"A10_FREEZE", "A08_GATE"},
    )
    assert out["action"] == "A10_FREEZE"


def test_nse_progress_freezes_when_round_reserve_hit_after_keep():
    from hydro_agent.agent.contracts import EvidenceSummary, HydroContext

    view = _view().model_copy(
        update={
            "budget": BudgetSummary(
                agent_rounds_remaining=3,
                optimization_cycles_remaining=2,
                max_agent_rounds=20,
                max_optimization_cycles=4,
            ),
            "permissions": PermissionSummary(
                safe_actions=(ActionCode.A10_FREEZE, ActionCode.A08_GATE, ActionCode.A09_RESOLVE),
                paused=False,
            ),
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="ev-gate",
                    action=ActionCode.A08_GATE,
                    status="KEEP",
                    new_information_hash="h-gate",
                ),
                EvidenceSummary(
                    evidence_id="ev-resolve",
                    action=ActionCode.A09_RESOLVE,
                    status="succeeded",
                    new_information_hash="h-resolve",
                ),
            ),
            "hydro": HydroContext(diagnosis={"metrics": {"nse": 0.05}}),
        }
    )
    out = _nse_calibration_progress(
        view,
        {"action": "A10_FREEZE", "hypothesis": "MODEL", "strategy_id": None, "rationale_summary": "x"},
        safe_actions={"A10_FREEZE", "A08_GATE", "A09_RESOLVE"},
    )
    assert out["action"] == "A10_FREEZE"


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
