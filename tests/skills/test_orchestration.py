from hydro_agent.optimization.calibration_scientist import (
    CalibrationPlan,
    DiagnosisHypothesis,
    EvidenceInterpretation,
)
from hydro_agent.skills import (
    EVIDENCE_REVIEW_SKILL_ID,
    EXPERIMENT_DESIGN_SKILL_ID,
    RESULT_REVIEW_SKILL_ID,
    XAJ_DIAGNOSIS_SKILL_ID,
    SkillRegistry,
)
from hydro_agent.skills.orchestration import SkillOrchestrator


def test_invoke_skill_chain_produces_typed_contracts_and_audits():
    orchestrator = SkillOrchestrator(SkillRegistry(), model="unit-test")
    diagnosis = {
        "hypothesis": "TIMING",
        "phenomenon": "洪峰偏晚、退水偏快",
        "recommended_strategy_id": "xaj-local-refine-v1",
        "recommended_param_groups": ["routing"],
        "recommended_objective": "nse",
        "hypotheses": [{"id": "TIMING", "strength": 0.8}],
        "metrics": {"nse": 0.35, "peak_timing_lag_leads": 1.0},
        "notes": ["held-out diagnosis"],
    }

    plan, invocations = orchestrator.plan_calibration(diagnosis)

    assert isinstance(plan, CalibrationPlan)
    assert plan.parameter_groups == ("routing",)
    assert plan.tunes_raw_parameter_vector is False
    assert [item.skill_id for item in invocations] == [
        EVIDENCE_REVIEW_SKILL_ID,
        XAJ_DIAGNOSIS_SKILL_ID,
        EXPERIMENT_DESIGN_SKILL_ID,
    ]
    assert [item.output_contract for item in invocations] == [
        "EvidenceInterpretation",
        "DiagnosisHypothesis",
        "CalibrationPlan",
    ]
    assert EvidenceInterpretation.model_validate(invocations[0].output)
    assert DiagnosisHypothesis.model_validate(invocations[1].output)
    assert invocations[0].audit["output_contract"] == "EvidenceInterpretation"
    assert invocations[1].audit["skill_sha256"]
    assert invocations[2].audit["loaded_references"] is not None


def test_invoke_skill_result_review_contract():
    orchestrator = SkillOrchestrator(model="unit-test")
    review, inv = orchestrator.review_calibration(
        diagnosis={
            "hypothesis": "MODEL",
            "phenomenon": "误差模式不清晰",
            "recommended_strategy_id": "xaj-bounded-v1",
            "recommended_param_groups": ["evap", "runoff", "routing"],
            "recommended_objective": "nse",
        },
        gate_status="KEEP",
        reasons=("insufficient_primary_improvement",),
    )
    assert inv.skill_id == RESULT_REVIEW_SKILL_ID
    assert inv.output_contract == "ExperimentReview"
    assert review.hypothesis_status == "inconclusive"
    assert review.recommended_next_experiment == "re-diagnose"


def test_plan_from_diagnosis_uses_orchestrator_path():
    from hydro_agent.optimization.calibration_scientist import plan_from_diagnosis

    plan = plan_from_diagnosis(
        {
            "hypothesis": "MODEL",
            "phenomenon": "PBIAS=18%",
            "recommended_strategy_id": "xaj-water-balance-v1",
            "recommended_param_groups": ["evap", "runoff"],
            "recommended_objective": "composite",
            "metrics": {"pbias_percent": 18.0},
        }
    )
    assert plan.evidence_interpretation is not None
    assert plan.diagnosis_hypothesis is not None
    assert plan.diagnosis_hypothesis.process_layer in {"evap", "runoff", "mixed"}
