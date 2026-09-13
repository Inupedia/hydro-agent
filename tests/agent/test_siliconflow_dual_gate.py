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
from hydro_agent.agent.providers.siliconflow import _nse_calibration_progress


def _resolved_view(qualification_status: str) -> WorldStateView:
    evidence = (
        EvidenceSummary(
            evidence_id="ev-opt",
            action=ActionCode.A07_OPTIMIZE,
            status="succeeded",
            new_information_hash="h-opt",
        ),
        EvidenceSummary(
            evidence_id="ev-gate",
            action=ActionCode.A08_GATE,
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
            action=ActionCode.A09_RESOLVE,
            status="KEEP" if qualification_status != "QUALIFIED" else "ACCEPT",
            new_information_hash="h-resolve",
            gates={
                "status": (
                    "KEEP" if qualification_status != "QUALIFIED" else "ACCEPT"
                ),
                "gate_status": "ACCEPT",
                "adoption_status": "ADOPT",
                "qualification_status": qualification_status,
                "candidate_adopted": "true",
            },
        ),
        EvidenceSummary(
            evidence_id="ev-diagnose",
            action=ActionCode.A06_DIAGNOSE,
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
        scheme=SchemeSummary(
            scheme_id="scheme-adopted", status="candidate", content_hash="h"
        ),
        permissions=PermissionSummary(
            safe_actions=(ActionCode.A07_OPTIMIZE, ActionCode.A10_FREEZE), paused=False
        ),
        budget=BudgetSummary(
            agent_rounds_remaining=10,
            optimization_cycles_remaining=2,
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
    result = _nse_calibration_progress(
        view,
        {
            "action": "A10_FREEZE",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "NSE is high",
        },
        safe_actions={"A07_OPTIMIZE", "A10_FREEZE"},
        nse_good_enough=0.7,
    )
    assert result["action"] == "A07_OPTIMIZE"
    assert "不能绕过 Gate" in result["rationale_summary"]


def test_not_evaluated_gate_also_requires_more_evidence():
    view = _resolved_view("NOT_EVALUATED")
    result = _nse_calibration_progress(
        view,
        {
            "action": "A10_FREEZE",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "NSE is high",
        },
        safe_actions={"A07_OPTIMIZE", "A10_FREEZE"},
        nse_good_enough=0.7,
    )
    assert result["action"] == "A07_OPTIMIZE"


def test_qualified_gate_freezes_even_if_llm_requests_more_search():
    view = _resolved_view("QUALIFIED")
    result = _nse_calibration_progress(
        view,
        {
            "action": "A07_OPTIMIZE",
            "hypothesis": "MODEL",
            "strategy_id": "xaj-bounded-v1",
            "rationale_summary": "search more",
        },
        safe_actions={"A07_OPTIMIZE", "A10_FREEZE"},
        nse_good_enough=0.7,
    )
    assert result["action"] == "A10_FREEZE"
    assert "资格评价" in result["rationale_summary"]
