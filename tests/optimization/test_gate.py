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
        max_candidates=32,
        random_seed=20260908,
        objective="nse",
    )
    assert strategy.max_candidates == 32
    assert strategy.random_seed == 20260908


def test_gate_policy_requires_explicit_thresholds():
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
        min_candidate_primary=0.0,
    )
    assert policy.min_primary_delta == 0.01
    assert policy.min_candidate_primary == 0.0
    assert policy.require_gbt_grade is True
    assert policy.min_scheme_grade == "丙"


def _bundle(scheme_id, nses, high_flow_maes):
    leads = tuple(
        LeadMetrics(lead=i, nse=nses[i - 1], mae=1.0, bias=0.0, high_flow_mae=high_flow_maes[i - 1])
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
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
    )
    decision = GateEvaluator().evaluate(base, candidate, policy)
    assert decision.status == "ROLLBACK"
    assert "lead_guardrail" in decision.reasons


def test_relative_nse_gain_alone_keeps_under_gbt_policy():
    base = _bundle("scheme-base", [0.20, 0.20, 0.20], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.35, 0.35, 0.35], [1.0, 1.0, 1.0])
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
        accept_primary_floor=0.5,
        require_gbt_grade=True,
    )
    decision = GateEvaluator().evaluate(base, candidate, policy)
    assert decision.status == "KEEP"
    assert "insufficient_gbt_or_nse" in decision.reasons


def test_nse_floor_fallback_accepts_without_gbt_report():
    base = _bundle("scheme-base", [0.40, 0.40, 0.40], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.55, 0.55, 0.55], [1.0, 1.0, 1.0])
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
        accept_primary_floor=0.5,
        require_gbt_grade=True,
    )
    decision = GateEvaluator().evaluate(base, candidate, policy, gbt_report=None)
    assert decision.status == "ACCEPT"
    assert "nse_good_enough_fallback" in decision.reasons


def test_large_relative_gain_still_keeps_when_absolute_skill_is_poor():
    base = _bundle("scheme-base", [-300.0, -300.0, -300.0], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [-220.0, -220.0, -220.0], [1.0, 1.0, 1.0])
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
        min_candidate_primary=0.0,
    )
    decision = GateEvaluator().evaluate(base, candidate, policy)
    assert decision.status == "KEEP"
