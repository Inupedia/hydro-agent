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
    )
    assert policy.min_primary_delta == 0.01


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


def test_small_valid_improvement_keeps_base():
    base = _bundle("scheme-base", [0.50, 0.50, 0.50], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.505, 0.505, 0.505], [1.0, 1.0, 1.0])
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
    )
    decision = GateEvaluator().evaluate(base, candidate, policy)
    assert decision.status == "KEEP"


def test_sufficient_safe_improvement_accepts():
    base = _bundle("scheme-base", [0.50, 0.50, 0.50], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.60, 0.60, 0.60], [1.0, 1.0, 1.0])
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
    )
    decision = GateEvaluator().evaluate(base, candidate, policy)
    assert decision.status == "ACCEPT"
