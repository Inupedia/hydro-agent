from hydro_agent.optimization.calibration_scientist import (
    interpret_evidence,
    plan_from_diagnosis,
    reflect_on_gate,
    review_experiment,
)


def test_diagnosis_becomes_group_level_dds_plan():
    plan = plan_from_diagnosis(
        {
            "hypothesis": "TIMING",
            "phenomenon": "洪峰偏晚",
            "recommended_strategy_id": "xaj-local-refine-v1",
            "recommended_param_groups": ["routing"],
            "recommended_objective": "nse",
            "hypotheses": [{"id": "TIMING", "strength": 0.78}],
            "metrics": {"peak_timing_lag_leads": 1.0, "nse": 0.2},
            "notes": ["held-out diagnosis"],
        }
    )

    assert plan.hypothesis.hypothesis == "TIMING"
    assert plan.parameter_groups == ("routing",)
    assert plan.optimizer == "dds"
    assert plan.search_scope == "local"
    assert plan.evaluation_budget == 256
    assert plan.tunes_raw_parameter_vector is False
    assert not hasattr(plan, "parameters")
    assert plan.diagnosis_hypothesis is not None
    assert plan.diagnosis_hypothesis.process_layer == "routing"
    assert plan.evidence_interpretation is not None
    assert any("nse=" in item for item in plan.evidence_interpretation.metrics_summary)
    assert plan.diagnosis_hypothesis.falsification_conditions


def test_evidence_interpretation_is_model_agnostic():
    reading = interpret_evidence(
        {
            "phenomenon": "汛期 NSE 偏低",
            "metrics": {"nse": 0.41, "pbias": 12.0},
            "notes": ["高流量误差显著"],
        }
    )
    assert "汛期 NSE 偏低" in reading.dominant_patterns
    assert any(item.startswith("nse=") for item in reading.metrics_summary)
    assert "water_balance" in reading.required_evidence


def test_adopted_but_unqualified_reflects_to_rediagnose():
    plan = plan_from_diagnosis(
        {
            "hypothesis": "MODEL",
            "phenomenon": "误差模式不清晰",
            "recommended_strategy_id": "xaj-bounded-v1",
            "recommended_param_groups": ["evap", "runoff", "routing"],
            "recommended_objective": "nse",
        }
    )
    reflection = reflect_on_gate(
        plan,
        gate_status="ACCEPT",
        qualification_status="UNQUALIFIED",
        reasons=("meaningful_primary_improvement", "insufficient_gbt_scheme_grade"),
    )
    assert reflection.gate_status == "ACCEPT"
    assert reflection.qualification_status == "UNQUALIFIED"
    assert reflection.next_step == "re-diagnose"
    assert "meaningful_primary_improvement" in reflection.evidence
    review = review_experiment(
        plan,
        gate_status="ACCEPT",
        qualification_status="UNQUALIFIED",
        reasons=("meaningful_primary_improvement",),
    )
    assert review.hypothesis_status == "adopted_unqualified"
    assert review.recommended_next_experiment == "re-diagnose"


def test_keep_reflects_to_rediagnose_not_blind_retry():
    plan = plan_from_diagnosis(
        {
            "hypothesis": "MODEL",
            "phenomenon": "误差模式不清晰",
            "recommended_strategy_id": "xaj-bounded-v1",
            "recommended_param_groups": ["evap", "runoff", "routing"],
            "recommended_objective": "nse",
        }
    )
    reflection = reflect_on_gate(
        plan,
        gate_status="KEEP",
        reasons=("insufficient_primary_improvement",),
    )
    assert reflection.gate_status == "KEEP"
    assert reflection.next_step == "re-diagnose"
    assert "insufficient_primary_improvement" in reflection.evidence
