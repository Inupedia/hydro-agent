from __future__ import annotations

import pytest

from hydro_agent.optimization.experiments import (
    ExperimentPlanner,
    HydrologicHypothesis,
    TrialLedger,
    TrialRecord,
    canonical_objective,
    infer_trial_outcome,
    runtime_objective,
)


def _hypothesis(*refs: str) -> HydrologicHypothesis:
    return HydrologicHypothesis(
        hypothesis_id="h-peak",
        category="MODEL",
        phenomenon="洪峰持续低估",
        testable_claim="调整产汇流参数可改善洪峰而不破坏整体过程线",
        evidence_refs=refs,
        target_metrics=("peak_relative_error", "kge"),
    )


def test_legacy_composite_is_only_a_kge_compatibility_alias():
    assert canonical_objective("composite") == "kge"
    assert canonical_objective("kge") == "kge"
    assert runtime_objective("kge") == "composite"
    with pytest.raises(ValueError, match="unsupported objective"):
        canonical_objective("magic-score")


def test_planner_uses_diagnosis_instead_of_unused_strategy_rotation():
    planner = ExperimentPlanner()
    plan = planner.plan(
        hypothesis=_hypothesis("ev-a06"),
        diagnosis={
            "recommended_strategy_id": "xaj-peak-bias-v1",
            "recommended_param_groups": ["runoff", "routing"],
            "recommended_objective": "composite",
        },
        available_strategies=(
            "xaj-bounded-v1",
            "xaj-peak-bias-v1",
            "xaj-local-refine-v1",
        ),
    )

    assert plan.strategy_id == "xaj-peak-bias-v1"
    assert plan.objective == "kge"
    assert plan.param_groups == ("runoff", "routing")
    assert plan.evidence_refs == ("ev-a06",)
    assert "diagnosis_recommendation" in plan.reason_codes


def test_boundary_evidence_is_reason_to_broaden_search():
    plan = ExperimentPlanner().plan(
        hypothesis=_hypothesis("ev-gate"),
        diagnosis={
            "recommended_strategy_id": "xaj-local-refine-v1",
            "local_boundary_hits": ["SM", "KI"],
        },
        available_strategies=("xaj-local-refine-v1", "xaj-broadened-refine-v1"),
    )

    assert plan.strategy_id == "xaj-broadened-refine-v1"
    assert "local_boundary_hit" in plan.reason_codes


def test_refuted_repeated_trial_can_widen_without_novelty_rotation():
    planner = ExperimentPlanner()
    first = planner.plan(
        hypothesis=_hypothesis("ev-1"),
        diagnosis={"recommended_param_groups": ["evap", "runoff", "routing"]},
        available_strategies=("xaj-hydro-composite-v1", "xaj-broadened-refine-v1"),
    )
    rejected = TrialRecord(
        trial_id="trial-1",
        plan_id=first.plan_id,
        experiment_signature=first.experiment_signature,
        strategy_id=first.strategy_id,
        development_gate="ROLLBACK",
        adoption_status="REJECT",
        qualification_status="UNQUALIFIED",
        hypothesis_outcome="refuted",
    )
    second = planner.plan(
        hypothesis=_hypothesis("ev-2"),
        diagnosis={"recommended_param_groups": ["evap", "runoff", "routing"]},
        available_strategies=("xaj-hydro-composite-v1", "xaj-broadened-refine-v1"),
        prior_trials=(rejected,),
    )

    assert second.strategy_id == "xaj-broadened-refine-v1"
    assert "refuted_trial_widen_search" in second.reason_codes


def test_trial_ledger_is_append_only_and_serializable():
    record = TrialRecord(
        trial_id="trial-1",
        plan_id="plan-1",
        experiment_signature="sig-1",
        strategy_id="xaj-bounded-v1",
        model_evaluations=100,
    )
    ledger = TrialLedger()
    ledger.append(record)

    assert ledger.records == (record,)
    assert ledger.as_dict()["trials"][0]["trial_id"] == "trial-1"
    with pytest.raises(ValueError, match="duplicate trial_id"):
        ledger.append(record)


def test_trial_outcome_is_based_on_independent_gate_evidence():
    assert (
        infer_trial_outcome(
            adoption_status="ADOPT", qualification_status="UNQUALIFIED", primary_delta=0.1
        )
        == "supported"
    )
    assert (
        infer_trial_outcome(
            adoption_status="REJECT", qualification_status="UNQUALIFIED", primary_delta=-0.1
        )
        == "refuted"
    )
    assert (
        infer_trial_outcome(
            adoption_status="KEEP", qualification_status="UNQUALIFIED", primary_delta=0.0
        )
        == "inconclusive"
    )
