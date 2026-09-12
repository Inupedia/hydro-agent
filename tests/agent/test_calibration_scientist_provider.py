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
from hydro_agent.agent.providers.calibration_scientist import CalibrationScientistDecisionProvider


def _view(*, latest_action: ActionCode, latest_status: str, hydro: HydroContext) -> WorldStateView:
    return WorldStateView(
        task=TaskSummary(
            task_id="task-1",
            basin_id="yaogu",
            phase="B",
            forcing_mode="R",
            allow_optimization=True,
        ),
        model=ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate", "validate")),
        scheme=SchemeSummary(scheme_id="scheme-base", status="validated", content_hash="abc"),
        permissions=PermissionSummary(
            safe_actions=(
                ActionCode.A03_VALIDATE_SCHEME,
                ActionCode.A05_FORECAST,
                ActionCode.A06_DIAGNOSE,
                ActionCode.A07_OPTIMIZE,
                ActionCode.A08_GATE,
                ActionCode.A09_RESOLVE,
                ActionCode.A10_FREEZE,
            )
        ),
        budget=BudgetSummary(
            agent_rounds_remaining=15,
            optimization_cycles_remaining=4,
            max_agent_rounds=20,
            max_optimization_cycles=4,
        ),
        evidence_summary=(
            EvidenceSummary(
                evidence_id="ev-1",
                action=latest_action,
                status=latest_status,
                new_information_hash="hash-1",
            ),
        ),
        latest_forecast_id="forecast-1",
        needs_follow_up=True,
        hydro=hydro,
    )


def test_provider_turns_diagnosis_into_group_level_sceua_experiment():
    hydro = HydroContext(
        diagnosis={
            "hypothesis": "MODEL",
            "phenomenon": "PBIAS=18%",
            "recommended_action": "A07_OPTIMIZE",
            "recommended_strategy_id": "xaj-water-balance-v1",
            "recommended_param_groups": "evap,runoff",
            "recommended_objective": "composite",
            "metrics": {"pbias_percent": 18.0},
        }
    )
    provider = CalibrationScientistDecisionProvider()
    decision = provider.decide(
        _view(latest_action=ActionCode.A06_DIAGNOSE, latest_status="succeeded", hydro=hydro)
    )

    assert decision.action == ActionCode.A07_OPTIMIZE
    assert decision.strategy_id == "xaj-water-balance-v1"
    assert decision.param_groups == ("evap", "runoff")
    assert decision.objective == "composite"


def test_provider_reflects_rollback_into_rediagnosis_before_second_experiment():
    view = _view(
        latest_action=ActionCode.A09_RESOLVE,
        latest_status="ROLLBACK",
        hydro=HydroContext(),
    ).model_copy(
        update={
            "budget": BudgetSummary(
                agent_rounds_remaining=12,
                optimization_cycles_remaining=3,
                max_agent_rounds=20,
                max_optimization_cycles=4,
            )
        }
    )
    provider = CalibrationScientistDecisionProvider(max_experiments=2)
    decision = provider.decide(view)
    assert decision.action == ActionCode.A06_DIAGNOSE
    assert "新 Evidence" in decision.rationale_summary
