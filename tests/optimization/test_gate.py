from hydro_agent.optimization.contracts import (
    CalibrationStrategy,
    EvaluationBundle,
    GatePolicy,
    LeadMetrics,
)
from hydro_agent.optimization.gate import GateEvaluator


def test_calibration_strategy_supports_deep_bounded_search_budget():
    strategy = CalibrationStrategy(
        strategy_id="xaj-bounded-v1",
        max_candidates=320,
        random_seed=20260908,
        objective="nse",
    )
    assert strategy.max_candidates == 320


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


def test_generic_gate_rolls_back_lead_regression():
    base = _bundle("scheme-base", [0.5, 0.5, 0.5], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.8, 0.8, 0.2], [1.0, 1.0, 1.0])
    decision = GateEvaluator().evaluate(base, candidate, GatePolicy())
    assert decision.status == "ROLLBACK"
    assert "lead_guardrail" in decision.reasons


def test_generic_gate_keeps_candidate_below_absolute_skill_floor():
    base = _bundle("scheme-base", [0.1, 0.1, 0.1], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.2, 0.2, 0.2], [0.9, 0.9, 0.9])
    decision = GateEvaluator().evaluate(base, candidate, GatePolicy())
    assert decision.status == "KEEP"


def test_generic_gate_can_accept_nse_fallback_without_gbt_report():
    base = _bundle("scheme-base", [0.40, 0.40, 0.40], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.55, 0.55, 0.55], [0.9, 0.9, 0.9])
    decision = GateEvaluator().evaluate(base, candidate, GatePolicy(), gbt_report=None)
    assert decision.status == "ACCEPT"
    assert "nse_good_enough_fallback" in decision.reasons
