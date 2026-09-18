from pydantic import SecretStr

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
    _diagnosis_calibration_progress,
    _extract_json,
    normalize_decision_payload,
)
from hydro_agent.llm.client import Completion
from hydro_agent.llm.settings import LLMSettings
from hydro_agent.skills import SkillRegistry
from hydro_agent.skills.manager import SkillManager


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
        permissions=PermissionSummary(safe_actions=(ActionCode.A03_FORECAST,), paused=False),
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
        '{"action":"A06_GATE","hypothesis":"MODEL","strategy_id":null,'
        '"rationale_summary":"候选已生成，进入独立验证 Gate。'
    )
    payload = _extract_json(text)
    assert payload["action"] == "A06_GATE"
    assert payload["hypothesis"] == "MODEL"


def test_normalize_does_not_force_freeze_after_resolve():
    payload = normalize_decision_payload(
        {
            "action": "A05_OPTIMIZE",
            "hypothesis": "MODEL",
            "strategy_id": "xaj-peak-bias-v1",
            "rationale_summary": "Gate KEEP 后继续按诊断策略再试一轮",
        },
        safe_actions={
            "A04_DIAGNOSE",
            "A05_OPTIMIZE",
            "A06_GATE",
            "A07_RESOLVE",
            "A08_FREEZE",
        },
        evidence_actions=("A06_GATE", "A07_RESOLVE"),
    )
    assert payload["action"] == "A05_OPTIMIZE"
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
    assert (
        payload["hypothesis"]
        != "Verifying forcing and observation availability has been recorded yet."
    )
    assert "Verifying forcing" in payload["rationale_summary"]
    decision = AgentDecision.model_validate(payload)
    assert decision.hypothesis in ProblemHypothesis


def test_normalize_repairs_misspelled_audit_field_and_drops_extra_keys():
    payload = normalize_decision_payload(
        {
            "action": "A03_FORECAST",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "Run audited base forecast.",
            "observation_zzh": "当前缺少基准预报证据。",
            "unexpected_field": "must not reach strict validation",
        }
    )

    assert payload["observation_zh"] == "当前缺少基准预报证据。"
    assert "observation_zzh" not in payload
    assert "unexpected_field" not in payload
    decision = AgentDecision.model_validate(payload)
    assert decision.observation_zh == "当前缺少基准预报证据。"


def test_normalize_remaps_hydrologist_manual_to_bounded():
    payload = normalize_decision_payload(
        {
            "action": "A05_OPTIMIZE",
            "hypothesis": "MODEL",
            "strategy_id": "xaj-hydrologist-manual-v1",
            "rationale_summary": "try manual",
        },
        safe_actions={"A05_OPTIMIZE"},
    )
    assert payload["strategy_id"] == "xaj-bounded-v1"


def test_nse_progress_calibrates_when_nse_poor():
    from hydro_agent.agent.contracts import EvidenceSummary, HydroContext

    view = _view().model_copy(
        update={
            "permissions": PermissionSummary(
                safe_actions=(
                    ActionCode.A04_DIAGNOSE,
                    ActionCode.A05_OPTIMIZE,
                    ActionCode.A06_GATE,
                    ActionCode.A08_FREEZE,
                ),
                paused=False,
            ),
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="ev-1",
                    action=ActionCode.A04_DIAGNOSE,
                    status="succeeded",
                    new_information_hash="h1",
                    metrics={"nse": -1.2},
                ),
            ),
            "hydro": HydroContext(
                diagnosis={
                    "hypothesis": "MODEL",
                    "recommended_action": "A05_OPTIMIZE",
                    "recommended_strategy_id": "xaj-peak-bias-v1",
                    "metrics": {"nse": -1.2},
                }
            ),
        }
    )
    out = _diagnosis_calibration_progress(
        view,
        {
            "action": "A08_FREEZE",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "looks ok",
        },
        safe_actions={"A05_OPTIMIZE", "A08_FREEZE", "A06_GATE"},
    )
    assert out["action"] == "A05_OPTIMIZE"
    # Guardrail forces A05 while preserving the fresh diagnosis direction; the
    # SkillOrchestrator subsequently validates and binds it to a typed plan.
    assert out["strategy_id"] == "xaj-peak-bias-v1"


def test_diagnosis_progress_freezes_when_dc_bing_floor_met():
    from hydro_agent.agent.contracts import EvidenceSummary, HydroContext

    view = _view().model_copy(
        update={
            "permissions": PermissionSummary(
                safe_actions=(ActionCode.A05_OPTIMIZE, ActionCode.A08_FREEZE),
                paused=False,
            ),
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="ev-1",
                    action=ActionCode.A04_DIAGNOSE,
                    status="succeeded",
                    new_information_hash="h1",
                    metrics={"nse": 0.72},
                ),
            ),
            "hydro": HydroContext(diagnosis={"metrics": {"nse": 0.72}}),
        }
    )
    out = _diagnosis_calibration_progress(
        view,
        {
            "action": "A05_OPTIMIZE",
            "hypothesis": "MODEL",
            "strategy_id": "xaj-bounded-v1",
            "rationale_summary": "x",
        },
        safe_actions={"A05_OPTIMIZE", "A08_FREEZE"},
    )
    assert out["action"] == "A08_FREEZE"


def test_nse_progress_respects_custom_threshold():
    from hydro_agent.agent.contracts import EvidenceSummary, HydroContext

    view = _view().model_copy(
        update={
            "permissions": PermissionSummary(
                safe_actions=(ActionCode.A05_OPTIMIZE, ActionCode.A08_FREEZE),
                paused=False,
            ),
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="ev-1",
                    action=ActionCode.A04_DIAGNOSE,
                    status="succeeded",
                    new_information_hash="h1",
                    metrics={"nse": 0.45},
                ),
            ),
            "hydro": HydroContext(diagnosis={"metrics": {"nse": 0.45}}),
        }
    )
    # 0.45 < 0.5 → still calibrate
    out_low = _diagnosis_calibration_progress(
        view,
        {
            "action": "A08_FREEZE",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "x",
        },
        safe_actions={"A05_OPTIMIZE", "A08_FREEZE"},
        dc_bing_floor=0.5,
    )
    assert out_low["action"] == "A05_OPTIMIZE"
    # 0.45 >= 0.4 → freeze when threshold lowered
    out_high = _diagnosis_calibration_progress(
        view,
        {
            "action": "A05_OPTIMIZE",
            "hypothesis": "MODEL",
            "strategy_id": "xaj-bounded-v1",
            "rationale_summary": "x",
        },
        safe_actions={"A05_OPTIMIZE", "A08_FREEZE"},
        dc_bing_floor=0.4,
    )
    assert out_high["action"] == "A08_FREEZE"


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
                safe_actions=(ActionCode.A05_OPTIMIZE, ActionCode.A08_FREEZE, ActionCode.A06_GATE),
                paused=False,
            ),
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="ev-opt",
                    action=ActionCode.A05_OPTIMIZE,
                    status="succeeded",
                    new_information_hash="h-opt",
                ),
                EvidenceSummary(
                    evidence_id="ev-gate",
                    action=ActionCode.A06_GATE,
                    status="KEEP",
                    new_information_hash="h-gate",
                ),
                EvidenceSummary(
                    evidence_id="ev-resolve",
                    action=ActionCode.A07_RESOLVE,
                    status="succeeded",
                    new_information_hash="h-resolve",
                ),
            ),
            "hydro": HydroContext(diagnosis={"metrics": {"nse": 0.1}}),
        }
    )
    out = _diagnosis_calibration_progress(
        view,
        {
            "action": "A01_CHECK_DATA",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "wander",
        },
        # A05 not safe once opt cycles are gone — mirrors PermissionGate.
        safe_actions={"A08_FREEZE", "A06_GATE"},
    )
    assert out["action"] == "A08_FREEZE"


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
                safe_actions=(ActionCode.A08_FREEZE, ActionCode.A06_GATE, ActionCode.A07_RESOLVE),
                paused=False,
            ),
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="ev-gate",
                    action=ActionCode.A06_GATE,
                    status="KEEP",
                    new_information_hash="h-gate",
                ),
                EvidenceSummary(
                    evidence_id="ev-resolve",
                    action=ActionCode.A07_RESOLVE,
                    status="succeeded",
                    new_information_hash="h-resolve",
                ),
            ),
            "hydro": HydroContext(diagnosis={"metrics": {"nse": 0.05}}),
        }
    )
    out = _diagnosis_calibration_progress(
        view,
        {
            "action": "A08_FREEZE",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "x",
        },
        safe_actions={"A08_FREEZE", "A06_GATE", "A07_RESOLVE"},
    )
    assert out["action"] == "A08_FREEZE"


def test_nse_progress_closes_the_latest_cycle_not_any_old_cycle():
    from hydro_agent.agent.contracts import EvidenceSummary

    evidence = tuple(
        EvidenceSummary(
            evidence_id=f"ev-{index}",
            action=action,
            status=status,
            new_information_hash=f"h-{index}",
        )
        for index, (action, status) in enumerate(
            (
                (ActionCode.A05_OPTIMIZE, "succeeded"),
                (ActionCode.A06_GATE, "KEEP"),
                (ActionCode.A07_RESOLVE, "KEEP"),
                (ActionCode.A04_DIAGNOSE, "succeeded"),
                (ActionCode.A05_OPTIMIZE, "succeeded"),
            )
        )
    )
    view = _view().model_copy(update={"evidence_summary": evidence})
    out = _diagnosis_calibration_progress(
        view,
        {"action": "A08_FREEZE", "hypothesis": "MODEL", "rationale_summary": "x"},
        safe_actions={"A06_GATE"},
    )
    assert out["action"] == "A06_GATE"


def test_nse_progress_rediagnoses_after_keep():
    from hydro_agent.agent.contracts import EvidenceSummary

    evidence = tuple(
        EvidenceSummary(
            evidence_id=f"ev-{index}",
            action=action,
            status=status,
            new_information_hash=f"h-{index}",
        )
        for index, (action, status) in enumerate(
            (
                (ActionCode.A04_DIAGNOSE, "succeeded"),
                (ActionCode.A05_OPTIMIZE, "succeeded"),
                (ActionCode.A06_GATE, "KEEP"),
                (ActionCode.A07_RESOLVE, "KEEP"),
            )
        )
    )
    view = _view().model_copy(update={"evidence_summary": evidence})
    out = _diagnosis_calibration_progress(
        view,
        {"action": "A05_OPTIMIZE", "hypothesis": "MODEL", "rationale_summary": "x"},
        safe_actions={"A04_DIAGNOSE"},
    )
    assert out["action"] == "A04_DIAGNOSE"


def test_siliconflow_provider_injects_activated_skills():
    settings = LLMSettings(
        api_key=SecretStr("test-key"),
        model="zai-org/GLM-5.3",
        base_url="https://api.siliconflow.cn/v1",
    )
    text = (
        '{"action":"A03_FORECAST","hypothesis":"MODEL","strategy_id":null,'
        '"rationale_summary":"Run audited base forecast."}'
    )
    fake = FakeClient(text)
    provider = SiliconFlowDecisionProvider(client=fake, settings=settings)
    decision = provider.decide(_view())
    system = fake.calls[0]["messages"][0]["content"]
    assert "Activated Agent Skills" in system
    assert "hydrology-data-review" in system
    assert "hydrology-data-review" in decision.activated_skill_ids
    assert "calibration-experiment-design" in decision.activated_skill_ids
    assert "data-check" not in system
    assert "forecast-diagnose" not in system


def test_created_user_skill_reaches_live_decision_prompt(tmp_path):
    settings = LLMSettings(
        api_key=SecretStr("test-key"),
        model="zai-org/GLM-5.3",
        base_url="https://api.siliconflow.cn/v1",
    )
    registry = SkillRegistry(user_root=tmp_path / "user")
    SkillManager(registry).save_skill(
        "hydro-peak-timing",
        """---
name: hydro-peak-timing
description: Guide peak timing diagnosis.
metadata:
  activation_stages: "diagnosis|experiment"
  activation_model_ids: "xaj"
---

# Check peak timing against the full observed hydrograph.
""",
    )
    fake = FakeClient(
        '{"action":"A03_FORECAST","hypothesis":"MODEL","strategy_id":null,'
        '"rationale_summary":"Run audited base forecast."}'
    )
    provider = SiliconFlowDecisionProvider(client=fake, settings=settings, skills=registry)
    view = _view().model_copy(update={"latest_forecast_id": "forecast-1"})
    decision = provider.decide(view)
    system = fake.calls[0]["messages"][0]["content"]
    assert "hydro-peak-timing" in decision.activated_skill_ids
    assert "# Check peak timing against the full observed hydrograph." in system


def test_siliconflow_provider_streams_deltas():
    settings = LLMSettings(
        api_key=SecretStr("test-key"),
        model="zai-org/GLM-5.3",
        base_url="https://api.siliconflow.cn/v1",
    )
    text = (
        '{"action":"A03_FORECAST","hypothesis":"MODEL","strategy_id":null,'
        '"rationale_summary":"Run audited base forecast."}'
    )
    fake = FakeClient(text)
    provider = SiliconFlowDecisionProvider(client=fake, settings=settings)
    seen = []
    decision = provider.decide(_view(), on_delta=seen.append)
    expected = AgentDecision(
        action=ActionCode.A03_FORECAST,
        hypothesis=ProblemHypothesis.MODEL,
        strategy_id=None,
        rationale_summary="Run audited base forecast.",
        activated_skill_ids=(
            "hydrology-data-review",
            "calibration-experiment-design",
        ),
    )
    assert decision.model_copy(update={"activated_skills_audit": ()}) == expected
    assert [item["skill_id"] for item in decision.activated_skills_audit] == list(
        decision.activated_skill_ids
    )
    assert all(len(item["skill_sha256"]) == 64 for item in decision.activated_skills_audit)
    assert "".join(seen) == text
