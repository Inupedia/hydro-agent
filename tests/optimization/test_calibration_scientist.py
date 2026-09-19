from hydro_agent.optimization.calibration_scientist import (
    DiagnosisHypothesis,
    form_diagnosis_hypothesis,
    interpret_evidence,
    plan_from_diagnosis,
    reflect_on_gate,
    review_experiment,
)
from hydro_agent.optimization.contracts import DirectionalProbeResult


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



def _diagnosis_packet(events, *, pbias_percent=0.0):
    return {
        "window": "calibration",
        "overall": {
            "status": "available",
            "sample_count": 30,
            "metrics": {"nse": 0.42, "pbias_percent": pbias_percent},
            "notes": [],
        },
        "water_balance": {
            "status": "available",
            "sample_count": 30,
            "metrics": {"pbias_percent": pbias_percent},
            "notes": [],
        },
        "flow_regimes": {},
        "fdc": {"status": "available", "sample_count": 30, "metrics": {}, "notes": []},
        "seasons": {},
        "years": {},
        "flood_events": events,
        "data_quality": {
            "total_count": 30,
            "valid_count": 30,
            "dropped_count": 0,
            "coverage": 1.0,
            "dropped_by_reason": {},
        },
        "basin_attributes": {},
    }


def _event(event_id, *, timing_lag, volume_error, peak_error=-0.1):
    return {
        "event_id": event_id,
        "start": "2026-06-01",
        "end": "2026-06-05",
        "basis": "rainfall_runoff",
        "rain_start": "2026-06-01",
        "rain_end": "2026-06-03",
        "status": "available",
        "sample_count": 5,
        "metrics": {
            "peak_relative_error": peak_error,
            "peak_timing_lag_steps": timing_lag,
            "volume_relative_error": volume_error,
            "rising_limb_mae": 1.2,
            "recession_mae": 0.9,
        },
        "notes": [],
    }


def test_diagnosis_hypothesis_carries_direction_without_raw_parameter_values():
    hypothesis = DiagnosisHypothesis(
        hypothesis_id="routing-too-slow",
        confidence=0.82,
        phenomenon="多场洪水峰现偏晚且洪量接近无偏",
        process_layer="routing",
        parameter_groups=("routing",),
        direction="accelerate_routing",
        direction_confidence=0.78,
        direction_evidence_ids=("event-001", "event-004"),
        verification_required=True,
    )

    dumped = hypothesis.model_dump()
    assert dumped["direction"] == "accelerate_routing"
    assert dumped["direction_evidence_ids"] == ("event-001", "event-004")
    assert "parameter_values" not in dumped


def test_packet_repeated_late_peaks_with_neutral_volume_forms_accelerate_routing():
    diagnosis = {
        "hypothesis": "TIMING",
        "phenomenon": "多场洪水洪量接近无偏，但峰现普遍偏晚",
        "recommended_strategy_id": "xaj-local-refine-v1",
        "recommended_param_groups": ["routing"],
        "recommended_objective": "nse",
        "hypotheses": [{"id": "TIMING", "strength": 0.84}],
        "diagnosis_packet": _diagnosis_packet(
            [
                _event("event-001", timing_lag=1.0, volume_error=0.02),
                _event("event-002", timing_lag=2.0, volume_error=-0.03),
                _event("event-003", timing_lag=1.0, volume_error=0.01),
            ]
        ),
    }

    reading = interpret_evidence(diagnosis)
    hypothesis = form_diagnosis_hypothesis(reading, diagnosis)

    assert hypothesis.process_layer == "routing"
    assert hypothesis.direction == "accelerate_routing"
    assert hypothesis.direction_confidence > 0.5
    assert hypothesis.direction_evidence_ids == ("event-001", "event-002", "event-003")
    assert "repeated_late_peaks" in hypothesis.diagnostic_signature
    assert hypothesis.verification_required is True


def test_conflicting_event_direction_is_recorded_and_reduces_direction_confidence():
    diagnosis = {
        "hypothesis": "TIMING",
        "phenomenon": "多数洪水偏晚，但存在相反场次",
        "recommended_param_groups": ["routing"],
        "hypotheses": [{"id": "TIMING", "strength": 0.9}],
        "diagnosis_packet": _diagnosis_packet(
            [
                _event("event-001", timing_lag=1.0, volume_error=0.01),
                _event("event-002", timing_lag=1.0, volume_error=-0.02),
                _event("event-003", timing_lag=-1.0, volume_error=0.00),
            ]
        ),
    }

    hypothesis = form_diagnosis_hypothesis(interpret_evidence(diagnosis), diagnosis)

    assert hypothesis.direction == "accelerate_routing"
    assert "event-003" in hypothesis.contradictory_evidence_ids
    assert hypothesis.direction_confidence < hypothesis.confidence


def test_no_matching_process_signature_keeps_direction_unknown():
    diagnosis = {
        "hypothesis": "MODEL",
        "phenomenon": "过程误差没有稳定方向",
        "recommended_param_groups": ["runoff", "routing"],
        "diagnosis_packet": _diagnosis_packet(
            [
                _event("event-001", timing_lag=0.0, volume_error=0.08),
                _event("event-002", timing_lag=0.0, volume_error=-0.08),
            ]
        ),
    }

    hypothesis = form_diagnosis_hypothesis(interpret_evidence(diagnosis), diagnosis)

    assert hypothesis.direction == "unknown"
    assert hypothesis.direction_evidence_ids == ()



def test_refuted_direction_forces_rediagnosis_instead_of_optimizer_search():
    hypothesis = DiagnosisHypothesis(
        hypothesis_id="routing-too-slow",
        confidence=0.8,
        phenomenon="峰现持续偏晚",
        process_layer="routing",
        parameter_groups=("routing",),
        direction="accelerate_routing",
        direction_confidence=0.75,
        direction_evidence_ids=("event-001", "event-002"),
        verification_required=True,
    )
    plan = plan_from_hypothesis(
        hypothesis,
        {
            "model_id": "xaj",
            "recommended_strategy_id": "xaj-local-refine-v1",
            "recommended_param_groups": ["routing"],
            "recommended_objective": "nse",
        },
        direction_verification=DirectionalProbeResult(
            requested_direction="accelerate_routing",
            status="refuted",
            parameter_effects=(),
            contradictory_parameters=("L",),
            evidence_ids=("event-001", "event-002"),
        ),
    )

    assert plan.next_step == "re-diagnose"
    assert plan.direction_verification_status == "refuted"
    assert plan.direction_evidence_ids == ("event-001", "event-002")
