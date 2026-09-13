from hydro_agent.agent.contracts import (
    ActionCode,
    AgentDecision,
    BudgetSummary,
    EvidenceSummary,
    HydroContext,
    ModelSummary,
    PermissionSummary,
    ProblemHypothesis,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.agent.experiment_guardrail import apply_experiment_plan_guardrail


def view(*, diagnosis, evidence=()):
    return WorldStateView(
        task=TaskSummary(
            task_id="task-1",
            basin_id="demo",
            phase="B",
            forcing_mode="R",
        ),
        model=ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate")),
        scheme=SchemeSummary(scheme_id="scheme-1", status="base", content_hash="hash"),
        permissions=PermissionSummary(safe_actions=(ActionCode.A07_OPTIMIZE,)),
        budget=BudgetSummary(
            agent_rounds_remaining=10,
            optimization_cycles_remaining=3,
            max_agent_rounds=20,
            max_optimization_cycles=4,
        ),
        evidence_summary=tuple(evidence),
        last_information_hash="info-1",
        hydro=HydroContext(
            available_strategies=(
                "xaj-bounded-v1",
                "xaj-water-balance-v1",
                "xaj-local-refine-v1",
                "xaj-broadened-refine-v1",
            ),
            diagnosis=diagnosis,
        ),
    )


def optimize_decision(strategy="xaj-local-refine-v1"):
    return AgentDecision(
        action=ActionCode.A07_OPTIMIZE,
        hypothesis=ProblemHypothesis.MODEL,
        strategy_id=strategy,
        param_groups=("evap", "runoff", "routing"),
        objective="nse",
        rationale_summary="LLM proposed an optimization experiment.",
    )


def diagnosis_row(evidence_id="ev-diag"):
    return EvidenceSummary(
        evidence_id=evidence_id,
        action=ActionCode.A06_DIAGNOSE,
        status="succeeded",
        new_information_hash="diag-hash",
        metrics={"nse": 0.1, "pbias_percent": 25.0},
    )


def test_guardrail_obeys_fresh_diagnosis_not_provider_novelty_choice():
    state = view(
        diagnosis={
            "phenomenon": "水量偏差显著，优先处理蒸散发和产流",
            "recommended_strategy_id": "xaj-water-balance-v1",
            "recommended_param_groups": ["evap", "runoff"],
            "recommended_objective": "composite",
            "metrics": {"nse": 0.1, "pbias_percent": 25.0},
        },
        evidence=(diagnosis_row(),),
    )

    planned = apply_experiment_plan_guardrail(state, optimize_decision("xaj-local-refine-v1"))

    assert planned.strategy_id == "xaj-water-balance-v1"
    assert planned.param_groups == ("evap", "runoff")
    assert planned.objective == "composite"  # runtime alias; plan itself is canonical KGE
    assert planned.experiment_plan_id
    assert planned.experiment_signature
    assert planned.experiment_evidence_refs == ("ev-diag",)
    assert "diagnosis_recommendation" in planned.experiment_reason_codes


def test_guardrail_uses_boundary_evidence_to_widen_search():
    state = view(
        diagnosis={
            "phenomenon": "候选触及局部搜索边界",
            "recommended_strategy_id": "xaj-local-refine-v1",
            "recommended_param_groups": ["evap", "runoff", "routing"],
            "local_boundary_hits": ["SM", "KI"],
        },
        evidence=(diagnosis_row(),),
    )

    planned = apply_experiment_plan_guardrail(state, optimize_decision("xaj-bounded-v1"))

    assert planned.strategy_id == "xaj-broadened-refine-v1"
    assert "local_boundary_hit" in planned.experiment_reason_codes


def test_non_optimize_decision_is_untouched():
    state = view(diagnosis={}, evidence=(diagnosis_row(),))
    decision = AgentDecision(
        action=ActionCode.A10_FREEZE,
        hypothesis=ProblemHypothesis.MODEL,
        rationale_summary="freeze",
    )
    assert apply_experiment_plan_guardrail(state, decision) is decision


def test_guardrail_fails_open_when_no_strategy_catalog_is_available():
    state = WorldStateView(
        task=TaskSummary(task_id="t", basin_id="b", phase="B", forcing_mode="R"),
        model=ModelSummary(model_id="xaj", capabilities=("calibrate",)),
        scheme=SchemeSummary(scheme_id="s", status="base", content_hash="h"),
        permissions=PermissionSummary(safe_actions=(ActionCode.A07_OPTIMIZE,)),
        budget=BudgetSummary(
            agent_rounds_remaining=5,
            optimization_cycles_remaining=1,
            max_agent_rounds=20,
            max_optimization_cycles=4,
        ),
        hydro=HydroContext(available_strategies=(), diagnosis={}),
    )
    decision = optimize_decision("xaj-bounded-v1")
    assert apply_experiment_plan_guardrail(state, decision) is decision
