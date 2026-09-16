from hydro_agent.agent.contracts import (
    ActionCode,
    BudgetSummary,
    EvidenceSummary,
    HydroContext,
    ModelSummary,
    PermissionSummary,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.agent.providers.siliconflow import _diagnosis_calibration_progress


def _resolved_view(
    qualification_status: str,
    *,
    optimization_cycles_remaining: int = 2,
) -> WorldStateView:
    evidence = (
        EvidenceSummary(
            evidence_id="ev-opt",
            action=ActionCode.A05_OPTIMIZE,
            status="succeeded",
            new_information_hash="h-opt",
        ),
        EvidenceSummary(
            evidence_id="ev-gate",
            action=ActionCode.A06_GATE,
            status="ACCEPT",
            new_information_hash="h-gate",
            gates={
                "status": "ACCEPT",
                "adoption_status": "ADOPT",
                "qualification_status": qualification_status,
            },
        ),
        EvidenceSummary(
            evidence_id="ev-resolve",
            action=ActionCode.A07_RESOLVE,
            status="KEEP" if qualification_status != "QUALIFIED" else "ACCEPT",
            new_information_hash="h-resolve",
            gates={
                "status": ("KEEP" if qualification_status != "QUALIFIED" else "ACCEPT"),
                "gate_status": "ACCEPT",
                "adoption_status": "ADOPT",
                "qualification_status": qualification_status,
                "candidate_adopted": "true",
            },
        ),
        EvidenceSummary(
            evidence_id="ev-diagnose",
            action=ActionCode.A04_DIAGNOSE,
            status="succeeded",
            new_information_hash="h-diagnose",
            metrics={"nse": 0.9},
        ),
    )
    return WorldStateView(
        task=TaskSummary(
            task_id="task-1",
            basin_id="yaogu",
            phase="B",
            forcing_mode="R",
            allow_optimization=True,
        ),
        model=ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate")),
        scheme=SchemeSummary(scheme_id="scheme-adopted", status="candidate", content_hash="h"),
        permissions=PermissionSummary(
            safe_actions=(ActionCode.A05_OPTIMIZE, ActionCode.A08_FREEZE), paused=False
        ),
        budget=BudgetSummary(
            agent_rounds_remaining=10,
            optimization_cycles_remaining=optimization_cycles_remaining,
            max_agent_rounds=20,
            max_optimization_cycles=4,
        ),
        evidence_summary=evidence,
        latest_forecast_id="forecast-1",
        needs_follow_up=True,
        hydro=HydroContext(
            diagnosis={
                "hypothesis": "MODEL",
                "recommended_strategy_id": "xaj-water-balance-v1",
                "recommended_param_groups": ["evap", "runoff"],
                "recommended_objective": "composite",
                "metrics": {"nse": 0.9},
            }
        ),
    )


def test_high_diagnostic_nse_cannot_bypass_unqualified_gate():
    view = _resolved_view("UNQUALIFIED")
    result = _diagnosis_calibration_progress(
        view,
        {
            "action": "A08_FREEZE",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "NSE is high",
        },
        safe_actions={"A05_OPTIMIZE", "A08_FREEZE"},
        dc_bing_floor=0.7,
    )
    assert result["action"] == "A05_OPTIMIZE"
    assert "不能绕过 Gate" in result["rationale_summary"]


def test_not_evaluated_gate_also_requires_more_evidence():
    view = _resolved_view("NOT_EVALUATED")
    result = _diagnosis_calibration_progress(
        view,
        {
            "action": "A08_FREEZE",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "NSE is high",
        },
        safe_actions={"A05_OPTIMIZE", "A08_FREEZE"},
        dc_bing_floor=0.7,
    )
    assert result["action"] == "A05_OPTIMIZE"


def test_qualified_gate_freezes_even_if_llm_requests_more_search():
    view = _resolved_view("QUALIFIED")
    result = _diagnosis_calibration_progress(
        view,
        {
            "action": "A05_OPTIMIZE",
            "hypothesis": "MODEL",
            "strategy_id": "xaj-bounded-v1",
            "rationale_summary": "search more",
        },
        safe_actions={"A05_OPTIMIZE", "A08_FREEZE"},
        dc_bing_floor=0.7,
    )
    assert result["action"] == "A08_FREEZE"
    assert "资格评价" in result["rationale_summary"]


def test_unqualified_budget_exhaustion_auto_closes_without_release_approval():
    view = _resolved_view("UNQUALIFIED", optimization_cycles_remaining=0)
    result = _diagnosis_calibration_progress(
        view,
        {
            "action": "A08_FREEZE",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "close out",
        },
        safe_actions={"A08_FREEZE"},
        dc_bing_floor=0.7,
    )

    assert result["action"] == "A08_FREEZE"
    assert "自动进入研究收口" in result["rationale_summary"]
    assert "不放行发布" in result["rationale_summary"]
    assert "不合格方案仍可冻结并回放/出报告" in result["rationale_summary"]
