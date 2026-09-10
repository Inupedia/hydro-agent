from hydro_agent.optimization.contracts import (
    CalibrationStrategy,
    EvaluationBundle,
    GatePolicy,
    LeadMetrics,
)
from hydro_agent.optimization.gate import GateEvaluator


def test_calibration_strategy_has_hard_budget_and_seed():
    strategy = CalibrationStrategy(
        strategy_id="xaj-bounded-v1",
        max_candidates=320,
        random_seed=20260908,
        objective="nse",
    )
    assert strategy.max_candidates == 320
    assert strategy.random_seed == 20260908


def test_gate_policy_has_convergence_controls():
    policy = GatePolicy()
    assert policy.require_gbt_grade is True
    assert policy.min_scheme_grade == "丙"
    assert policy.convergence_window == 4
    assert policy.convergence_min_points == 3
    assert policy.convergence_gain_tolerance > 0
    assert policy.convergence_slope_tolerance > 0


def _bundle(scheme_id, nses, high_flow_maes):
    leads = tuple(
        LeadMetrics(
            lead=i,
            nse=nses[i - 1],
            mae=1.0,
            bias=0.0,
            high_flow_mae=high_flow_maes[i - 1],
        )
        for i in (1, 2, 3)
    )
    return EvaluationBundle(
        scheme_id=scheme_id,
        leads=leads,
        primary_score=sum(nses) / 3.0,
    )


def test_guardrail_failure_rolls_back_even_when_average_improves():
    base = _bundle("scheme-base", [0.5, 0.5, 0.5], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.8, 0.8, 0.2], [1.0, 1.0, 1.0])
    decision = GateEvaluator().evaluate(base, candidate, GatePolicy())
    assert decision.status == "ROLLBACK"
    assert decision.adopt_candidate is False
    assert "lead_guardrail" in decision.reasons


def test_improvement_below_final_grade_is_promoted_and_continues():
    base = _bundle("scheme-base", [0.20, 0.20, 0.20], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.35, 0.35, 0.35], [0.9, 0.9, 0.9])
    decision = GateEvaluator().evaluate(base, candidate, GatePolicy(), history_primary=(0.10,))
    assert decision.status == "CONTINUE"
    assert decision.adopt_candidate is True
    assert decision.should_stop is False
    assert decision.best_primary == candidate.primary_score


def test_nse_floor_fallback_accepts_without_gbt_report():
    base = _bundle("scheme-base", [0.40, 0.40, 0.40], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.55, 0.55, 0.55], [0.9, 0.9, 0.9])
    decision = GateEvaluator().evaluate(base, candidate, GatePolicy(), gbt_report=None)
    assert decision.status == "ACCEPT"
    assert decision.adopt_candidate is True
    assert decision.should_stop is True
    assert "nse_good_enough_fallback" in decision.reasons


def test_validation_curve_plateau_stops_even_with_budget_remaining():
    base = _bundle("scheme-base", [0.487, 0.487, 0.487], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.488, 0.488, 0.488], [0.99, 0.99, 0.99])
    decision = GateEvaluator().evaluate(
        base,
        candidate,
        GatePolicy(),
        history_primary=(0.482, 0.485, 0.487),
    )
    assert decision.status == "CONVERGED"
    assert decision.should_stop is True
    assert decision.adopt_candidate is True
    assert decision.convergence_gain is not None
    assert decision.convergence_gain <= GatePolicy().convergence_gain_tolerance


def test_low_plateau_with_forcing_warning_becomes_structural_limit():
    base = _bundle("scheme-base", [0.12, 0.12, 0.12], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.121, 0.121, 0.121], [0.99, 0.99, 0.99])
    decision = GateEvaluator().evaluate(
        base,
        candidate,
        GatePolicy(),
        history_primary=(0.115, 0.119, 0.120),
        diagnosis_metrics={"forcing_adequacy_warning": 1.0},
    )
    assert decision.status == "STRUCTURAL_LIMIT"
    assert decision.should_stop is True
    assert "forcing_or_structure_warning" in decision.reasons


def test_repeated_guardrail_failures_plus_forcing_warning_stop_search():
    base = _bundle("scheme-base", [0.10, 0.10, 0.10], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.08, 0.08, 0.08], [1.3, 1.3, 1.3])
    decision = GateEvaluator().evaluate(
        base,
        candidate,
        GatePolicy(structural_warning_patience=2),
        history_primary=(0.10, 0.10),
        prior_statuses=("ROLLBACK", "ROLLBACK"),
        diagnosis_metrics={"forcing_adequacy_warning": 1.0},
    )
    assert decision.status == "STRUCTURAL_LIMIT"
    assert decision.adopt_candidate is False
    assert decision.should_stop is True


def test_negative_nse_can_still_climb_instead_of_freezing_bad_base():
    base = _bundle("scheme-base", [-2.0, -2.0, -2.0], [10.0, 10.0, 10.0])
    candidate = _bundle("scheme-cand", [-1.2, -1.2, -1.2], [8.0, 8.0, 8.0])
    decision = GateEvaluator().evaluate(base, candidate, GatePolicy(), history_primary=(-3.0,))
    assert decision.status == "CONTINUE"
    assert decision.adopt_candidate is True
    assert decision.best_primary == -1.2
