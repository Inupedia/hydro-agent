from hydro_agent.optimization.contracts import (
    CalibrationStrategy,
    EvaluationBundle,
    GatePolicy,
    LeadMetrics,
)
from hydro_agent.optimization.gate import GateEvaluator, ResearchGateEvaluator


def test_calibration_strategy_has_hard_budget_and_seed():
    strategy = CalibrationStrategy(
        strategy_id="xaj-bounded-v1",
        max_candidates=512,
        random_seed=20260908,
        objective="nse",
        optimizer="dds",
    )
    assert strategy.evaluation_budget == 512
    assert strategy.random_seed == 20260908
    assert strategy.optimizer == "dds"


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
    assert decision.adoption_status == "REJECT"
    assert "lead_3_guardrail" in decision.reasons


def test_meaningful_gain_is_adopted_even_before_standard_qualification():
    base = _bundle("scheme-base", [0.20, 0.20, 0.20], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.35, 0.35, 0.35], [1.0, 1.0, 1.0])
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
        require_gbt_grade=True,
    )
    decision = GateEvaluator().evaluate(base, candidate, policy, gbt_report=None)
    assert decision.status == "ACCEPT"
    assert decision.adoption_status == "ADOPT"
    assert decision.qualification_status == "NOT_EVALUATED"
    assert "meaningful_primary_improvement" in decision.reasons
    assert "missing_standard_evaluation" in decision.qualification_reasons


def test_small_gain_is_not_adopted_even_when_candidate_is_absolutely_usable():
    base = _bundle("scheme-base", [0.55, 0.55, 0.55], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.555, 0.555, 0.555], [1.0, 1.0, 1.0])
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
        accept_primary_floor=0.5,
        require_gbt_grade=False,
    )
    decision = GateEvaluator().evaluate(base, candidate, policy)
    assert decision.status == "KEEP"
    assert decision.adoption_status == "KEEP"
    assert decision.qualification_status == "QUALIFIED"


def test_large_relative_gain_can_be_adopted_while_still_unqualified():
    base = _bundle("scheme-base", [-300.0, -300.0, -300.0], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [-220.0, -220.0, -220.0], [1.0, 1.0, 1.0])
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
        min_candidate_primary=0.0,
    )
    decision = GateEvaluator().evaluate(base, candidate, policy)
    assert decision.status == "ACCEPT"
    assert decision.adoption_status == "ADOPT"
    assert decision.qualification_status == "UNQUALIFIED"
    assert "insufficient_absolute_skill" in decision.qualification_reasons



def test_missing_standard_evaluation_does_not_block_research_adoption():
    base = _bundle("scheme-base", [0.30, 0.30, 0.30], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.60, 0.60, 0.60], [0.9, 0.9, 0.9])
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
        min_candidate_primary=0.0,
    )

    decision = ResearchGateEvaluator().evaluate(base, candidate, policy=policy)

    assert decision.adoption_status == "ADOPT"
    assert decision.research_qualification == "QUALIFIED"
    assert "missing_standard_evaluation" not in decision.reasons


def test_research_gate_reports_event_guardrails_without_composite_score():
    base = _bundle("scheme-base", [0.40, 0.40, 0.40], [1.0, 1.0, 1.0])
    candidate = _bundle("scheme-cand", [0.60, 0.60, 0.60], [1.0, 1.0, 1.0])
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
        min_candidate_primary=0.0,
        max_event_peak_error_increase=0.05,
        max_event_timing_error_increase=1.0,
        max_event_volume_error_increase=0.05,
        max_materially_worsened_event_fraction=0.40,
    )
    comparison = {
        "base": [
            {"event_id": "e1", "peak_relative_error": 0.10, "timing_lag_steps": 1.0, "volume_relative_error": 0.02},
            {"event_id": "e2", "peak_relative_error": -0.10, "timing_lag_steps": 1.0, "volume_relative_error": -0.02},
        ],
        "candidate": [
            {"event_id": "e1", "peak_relative_error": 0.25, "timing_lag_steps": 3.0, "volume_relative_error": 0.12},
            {"event_id": "e2", "peak_relative_error": -0.22, "timing_lag_steps": 3.0, "volume_relative_error": -0.11},
        ],
    }

    decision = ResearchGateEvaluator().evaluate(
        base, candidate, policy=policy, event_comparison=comparison
    )

    assert decision.status == "ROLLBACK"
    assert "event_peak_guardrail" in decision.event_guardrail_reasons
    assert "event_timing_guardrail" in decision.event_guardrail_reasons
    assert "event_volume_guardrail" in decision.event_guardrail_reasons
    assert "materially_worsened_event_fraction_guardrail" in decision.event_guardrail_reasons
    assert not hasattr(decision, "composite_score")
