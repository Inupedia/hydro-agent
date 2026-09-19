import pytest

from hydro_agent.agent.contracts import (
    ActionCode,
    BudgetSummary,
    EvidenceSummary,
    ExperienceContext,
    HydroContext,
    ModelSummary,
    PermissionSummary,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.agent.providers.calibration_scientist import CalibrationScientistDecisionProvider
from hydro_agent.optimization.campaign import CampaignSnapshot


def _view(
    *,
    latest_action: ActionCode,
    latest_status: str,
    hydro: HydroContext,
    latest_gates: dict[str, str] | None = None,
    optimization_cycles_remaining: int = 4,
) -> WorldStateView:
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
                ActionCode.A02_VALIDATE_SCHEME,
                ActionCode.A03_FORECAST,
                ActionCode.A04_DIAGNOSE,
                ActionCode.A05_OPTIMIZE,
                ActionCode.A06_GATE,
                ActionCode.A07_RESOLVE,
                ActionCode.A08_FREEZE,
            )
        ),
        budget=BudgetSummary(
            agent_rounds_remaining=15,
            optimization_cycles_remaining=optimization_cycles_remaining,
            max_agent_rounds=20,
            max_optimization_cycles=4,
        ),
        evidence_summary=(
            EvidenceSummary(
                evidence_id="ev-1",
                action=latest_action,
                status=latest_status,
                new_information_hash="hash-1",
                gates=latest_gates or {},
            ),
        ),
        latest_forecast_id="forecast-1",
        needs_follow_up=True,
        hydro=hydro,
    )


def test_provider_turns_diagnosis_into_group_level_dds_experiment():
    hydro = HydroContext(
        diagnosis={
            "hypothesis": "MODEL",
            "phenomenon": "PBIAS=18%",
            "recommended_action": "A05_OPTIMIZE",
            "recommended_strategy_id": "xaj-water-balance-v1",
            "recommended_param_groups": "evap,runoff",
            "recommended_objective": "composite",
            "metrics": {"pbias_percent": 18.0},
        }
    )
    decision = CalibrationScientistDecisionProvider().decide(
        _view(latest_action=ActionCode.A04_DIAGNOSE, latest_status="succeeded", hydro=hydro)
    )

    assert decision.action == ActionCode.A05_OPTIMIZE
    assert decision.strategy_id == "xaj-water-balance-v1"
    assert decision.param_groups == ("evap", "runoff")
    assert decision.objective == "nse"
    assert decision.activated_skill_ids == (
        "hydrologic-evidence-review",
        "xaj-calibration-diagnosis",
        "calibration-experiment-design",
    )
    assert [item["output_contract"] for item in decision.activated_skills_audit] == [
        "EvidenceInterpretation",
        "DiagnosisHypothesis",
        "CalibrationPlan",
    ]


def test_provider_only_uses_unverified_seed_prior_when_campaign_opts_in():
    diagnosis = {
        "hypothesis": "MODEL",
        "phenomenon": "PBIAS=18%",
        "recommended_action": "A05_OPTIMIZE",
        "recommended_strategy_id": "xaj-bounded-v1",
        "recommended_param_groups": "evap,runoff,routing",
        "recommended_objective": "nse",
        "metrics": {"nse": 0.42, "pbias_percent": 18.0},
    }
    provider = CalibrationScientistDecisionProvider()

    disabled = provider.decide(
        _view(
            latest_action=ActionCode.A04_DIAGNOSE,
            latest_status="succeeded",
            hydro=HydroContext(diagnosis=diagnosis),
        )
    )
    enabled = provider.decide(
        _view(
            latest_action=ActionCode.A04_DIAGNOSE,
            latest_status="succeeded",
            hydro=HydroContext(
                diagnosis=diagnosis,
                allow_unverified_expert_priors=True,
            ),
        )
    )

    assert disabled.param_groups == ("evap", "runoff", "routing")
    assert "expert.water_balance_first" not in disabled.rationale_summary
    assert enabled.param_groups == ("evap", "runoff")
    assert "expert.water_balance_first" in enabled.rationale_summary
    assert enabled.objective == "nse"


def _resolved_hydro(*, campaign: CampaignSnapshot | None = None) -> HydroContext:
    return HydroContext(campaign=campaign or CampaignSnapshot(mode="convergence"))


def test_provider_reflects_rollback_into_rediagnosis_while_campaign_running():
    view = _view(
        latest_action=ActionCode.A07_RESOLVE,
        latest_status="ROLLBACK",
        latest_gates={
            "status": "ROLLBACK",
            "gate_status": "ROLLBACK",
            "adoption_status": "REJECT",
            "qualification_status": "UNQUALIFIED",
            "candidate_adopted": "false",
        },
        hydro=_resolved_hydro(),
    )
    decision = CalibrationScientistDecisionProvider().decide(view)
    assert decision.action == ActionCode.A04_DIAGNOSE
    assert "Campaign 尚无停止证据" in decision.rationale_summary
    assert decision.activated_skill_ids == ("calibration-result-review",)
    assert decision.activated_skills_audit[0]["output_contract"] == "ExperimentReview"


def test_provider_continues_after_adoption_when_candidate_is_unqualified():
    view = _view(
        latest_action=ActionCode.A07_RESOLVE,
        latest_status="KEEP",
        latest_gates={
            "status": "KEEP",
            "gate_status": "ACCEPT",
            "adoption_status": "ADOPT",
            "qualification_status": "UNQUALIFIED",
            "candidate_adopted": "true",
        },
        hydro=_resolved_hydro(),
    )
    decision = CalibrationScientistDecisionProvider().decide(view)
    assert decision.action == ActionCode.A04_DIAGNOSE
    assert "已采用改进候选" in decision.rationale_summary


def test_convergence_mode_keeps_searching_after_qualification_until_campaign_stops():
    view = _view(
        latest_action=ActionCode.A07_RESOLVE,
        latest_status="ACCEPT",
        latest_gates={
            "status": "ACCEPT",
            "gate_status": "ACCEPT",
            "adoption_status": "ADOPT",
            "qualification_status": "QUALIFIED",
            "candidate_adopted": "true",
        },
        hydro=_resolved_hydro(
            campaign=CampaignSnapshot(
                mode="convergence",
                release_candidate_scheme_id="scheme-base",
                can_continue_search=True,
            )
        ),
    )
    decision = CalibrationScientistDecisionProvider().decide(view)
    assert decision.action == ActionCode.A04_DIAGNOSE
    assert "Campaign 尚无停止证据" in decision.rationale_summary


def test_provider_closes_out_only_when_campaign_has_explicit_stop_reason():
    view = _view(
        latest_action=ActionCode.A07_RESOLVE,
        latest_status="KEEP",
        latest_gates={
            "status": "KEEP",
            "gate_status": "ACCEPT",
            "adoption_status": "ADOPT",
            "qualification_status": "UNQUALIFIED",
            "candidate_adopted": "true",
        },
        hydro=_resolved_hydro(
            campaign=CampaignSnapshot(
                mode="convergence",
                trial_count=4,
                resolved_trial_count=4,
                total_model_evaluations=2048,
                stop_reason="BUDGET_EXHAUSTED",
                can_continue_search=False,
            )
        ),
    )
    decision = CalibrationScientistDecisionProvider().decide(view)
    assert decision.action == ActionCode.A08_FREEZE
    assert "Campaign stop=BUDGET_EXHAUSTED" in decision.rationale_summary
    assert "converged=false" in decision.rationale_summary


def test_failed_optimize_is_rediagnosed_without_gate():
    view = _view(
        latest_action=ActionCode.A05_OPTIMIZE,
        latest_status="failed",
        hydro=HydroContext(),
    )
    assert CalibrationScientistDecisionProvider().decide(view).action == ActionCode.A04_DIAGNOSE


@pytest.mark.parametrize("mode", ["convergence", "target_quality"])
@pytest.mark.parametrize("latest_action", [ActionCode.A04_DIAGNOSE, ActionCode.A07_RESOLVE])
def test_research_modes_ignore_legacy_cycle_count(mode, latest_action):
    view = _view(
        latest_action=latest_action,
        latest_status="succeeded" if latest_action == ActionCode.A04_DIAGNOSE else "KEEP",
        hydro=HydroContext(campaign=CampaignSnapshot(mode=mode)),
        optimization_cycles_remaining=0,
    )
    expected = (
        ActionCode.A05_OPTIMIZE
        if latest_action == ActionCode.A04_DIAGNOSE
        else ActionCode.A04_DIAGNOSE
    )
    assert CalibrationScientistDecisionProvider().decide(view).action == expected



def test_provider_applies_experience_before_experiment_guardrail():
    from hydro_agent.experience.retrieval import ExperienceMatch

    experience = ExperienceContext(
        skill_version=4,
        skill_hash="e" * 64,
        status="converging",
        matches=(
            ExperienceMatch(
                experience_id="EXP-XAJ-ROUTING",
                revision=3,
                category="model",
                relevance=1.0,
                transfer_weight=1.0,
                confidence=0.95,
                scope_rank=4,
                decision={"prefer_param_groups": ["routing"]},
                pattern={"peak_bias": "negative"},
                supporting_count=8,
                contradicting_count=1,
            ),
        ),
        source_revisions={"EXP-XAJ-ROUTING": 3},
        exploration_level=0.15,
    )
    hydro = HydroContext(
        diagnosis={
            "hypothesis": "MODEL",
            "phenomenon": "peak_bias=negative",
            "peak_bias": "negative",
            "recommended_action": "A05_OPTIMIZE",
            "recommended_strategy_id": "xaj-bounded-v1",
            "recommended_param_groups": "evap,runoff",
            "recommended_objective": "nse",
            "metrics": {"nse": 0.3},
        },
        experience=experience,
    )

    decision = CalibrationScientistDecisionProvider().decide(
        _view(
            latest_action=ActionCode.A04_DIAGNOSE,
            latest_status="succeeded",
            hydro=hydro,
        )
    )

    assert decision.action == ActionCode.A05_OPTIMIZE
    assert decision.param_groups == ("routing",)
    assert decision.experience_skill_version == 4
    assert decision.experience_skill_hash == "e" * 64
    assert decision.experience_refs == ("EXP-XAJ-ROUTING",)
    assert decision.experience_mode == "exploitation"
    assert any("EXP-XAJ-ROUTING:prefer=routing" in item for item in decision.experience_influence)



def test_provider_audit_exposes_packet_driven_direction_without_parameter_values():
    packet = {
        "window": "calibration",
        "overall": {
            "status": "available",
            "sample_count": 20,
            "metrics": {"nse": 0.4, "pbias_percent": 1.0},
            "notes": [],
        },
        "water_balance": {
            "status": "available",
            "sample_count": 20,
            "metrics": {"pbias_percent": 1.0},
            "notes": [],
        },
        "flow_regimes": {},
        "fdc": {"status": "available", "sample_count": 20, "metrics": {}, "notes": []},
        "seasons": {},
        "years": {},
        "flood_events": [
            {
                "event_id": "event-001",
                "start": "2026-06-01",
                "end": "2026-06-05",
                "basis": "rainfall_runoff",
                "status": "available",
                "sample_count": 5,
                "metrics": {
                    "peak_timing_lag_steps": 1.0,
                    "volume_relative_error": 0.02,
                    "peak_relative_error": -0.1,
                },
                "notes": [],
            },
            {
                "event_id": "event-002",
                "start": "2026-06-10",
                "end": "2026-06-14",
                "basis": "rainfall_runoff",
                "status": "available",
                "sample_count": 5,
                "metrics": {
                    "peak_timing_lag_steps": 1.0,
                    "volume_relative_error": -0.01,
                    "peak_relative_error": -0.08,
                },
                "notes": [],
            },
        ],
        "data_quality": {
            "total_count": 20,
            "valid_count": 20,
            "dropped_count": 0,
            "coverage": 1.0,
            "dropped_by_reason": {},
        },
        "basin_attributes": {},
    }
    hydro = HydroContext(
        diagnosis={
            "hypothesis": "TIMING",
            "phenomenon": "峰现持续偏晚，洪量接近无偏",
            "recommended_action": "A05_OPTIMIZE",
            "recommended_strategy_id": "xaj-local-refine-v1",
            "recommended_param_groups": "routing",
            "recommended_objective": "nse",
            "hypotheses": [{"id": "TIMING", "strength": 0.82}],
            "diagnosis_packet": packet,
        }
    )

    decision = CalibrationScientistDecisionProvider().decide(
        _view(latest_action=ActionCode.A04_DIAGNOSE, latest_status="succeeded", hydro=hydro)
    )

    hypothesis_output = decision.activated_skills_audit[1]["output"]
    assert hypothesis_output["direction"] == "accelerate_routing"
    assert hypothesis_output["direction_evidence_ids"] == ["event-001", "event-002"]
    assert "parameter_values" not in hypothesis_output
