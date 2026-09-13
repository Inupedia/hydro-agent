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


def test_fresh_diagnosis_recommendation_is_not_rotated_for_novelty():
    view = WorldStateView(
        task=TaskSummary(
            task_id="task-1",
            basin_id="yaogu",
            phase="B",
            forcing_mode="R",
            allow_optimization=True,
        ),
        model=ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate")),
        scheme=SchemeSummary(scheme_id="scheme-current", status="base", content_hash="h"),
        permissions=PermissionSummary(
            safe_actions=(ActionCode.A07_OPTIMIZE, ActionCode.A10_FREEZE),
            paused=False,
        ),
        budget=BudgetSummary(
            agent_rounds_remaining=12,
            optimization_cycles_remaining=2,
            max_agent_rounds=20,
            max_optimization_cycles=4,
        ),
        evidence_summary=(
            EvidenceSummary(
                evidence_id="old-opt",
                action=ActionCode.A07_OPTIMIZE,
                status="succeeded",
                new_information_hash="h-old-opt",
                gates={"strategy_id": "xaj-peak-bias-v1"},
            ),
            EvidenceSummary(
                evidence_id="fresh-diagnosis",
                action=ActionCode.A06_DIAGNOSE,
                status="succeeded",
                new_information_hash="h-diagnosis",
                metrics={"nse": 0.1},
            ),
        ),
        hydro=HydroContext(
            diagnosis={
                "hypothesis": "MODEL",
                "recommended_strategy_id": "xaj-peak-bias-v1",
                "recommended_param_groups": ["runoff", "routing"],
                "recommended_objective": "composite",
                "metrics": {"nse": 0.1},
            }
        ),
    )

    payload = _nse_calibration_progress(
        view,
        {
            "action": "A10_FREEZE",
            "hypothesis": "MODEL",
            "strategy_id": None,
            "rationale_summary": "model proposed freeze",
        },
        safe_actions={"A07_OPTIMIZE", "A10_FREEZE"},
        nse_good_enough=0.5,
    )

    assert payload["action"] == "A07_OPTIMIZE"
    assert payload["strategy_id"] == "xaj-peak-bias-v1"
    assert payload["param_groups"] == ["runoff", "routing"]
    assert payload["objective"] == "composite"
