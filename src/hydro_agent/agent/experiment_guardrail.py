"""Deterministic ExperimentPlan guardrail for A05 decisions."""

from __future__ import annotations

from hydro_agent.agent.contracts import ActionCode, AgentDecision, WorldStateView
from hydro_agent.optimization.experiments import (
    ExperimentPlanner,
    HydrologicHypothesis,
    runtime_objective,
)
from hydro_agent.optimization.ledger import TrialLedgerBuilder


def _latest_diagnosis(view: WorldStateView):
    for item in reversed(view.evidence_summary):
        if item.action == ActionCode.A04_DIAGNOSE:
            return item
    return None


def apply_experiment_plan_guardrail(
    view: WorldStateView,
    decision: AgentDecision,
    *,
    planner: ExperimentPlanner | None = None,
) -> AgentDecision:
    """Replace novelty-based A05 choices with an evidence-conditioned registered plan.

    The provider decides whether optimization is warranted. Once A05 is chosen,
    a typed Skill plan is preserved when present, then checked against registered
    strategies and prior-trial boundary evidence. The campaign workbench still owns
    the objective. If planning context is unavailable, the original legal decision
    is retained rather than inventing evidence.
    """

    if decision.action != ActionCode.A05_OPTIMIZE:
        return decision
    available = tuple(view.hydro.available_strategies)
    if not available:
        return decision

    diagnosis = dict(view.hydro.diagnosis or {})
    diagnostic_objective = str(diagnosis.get("recommended_objective") or "").strip()
    skill_plan_bound = "calibration-experiment-design" in decision.activated_skill_ids
    if skill_plan_bound:
        if decision.strategy_id in available:
            diagnosis["recommended_strategy_id"] = decision.strategy_id
        if decision.param_groups:
            diagnosis["recommended_param_groups"] = list(decision.param_groups)
    # A diagnosis/expert prior may say which error pattern deserves attention,
    # but cannot swap the scoring ruler between experiments. The workbench value
    # is pre-registered in WorldStateBuilder and defaults to the historical NSE.
    diagnosis["recommended_objective"] = view.hydro.campaign_objective

    diagnosis_row = _latest_diagnosis(view)
    evidence_refs = (diagnosis_row.evidence_id,) if diagnosis_row is not None else ()
    phenomenon = str(
        diagnosis.get("phenomenon")
        or diagnosis.get("hypothesis")
        or decision.rationale_summary
        or "模型率定证据需要进一步验证"
    )
    hypothesis_id = (
        f"h-{diagnosis_row.evidence_id}"
        if diagnosis_row is not None
        else f"h-{view.last_information_hash or 'current'}"
    )
    target_metrics: list[str] = []
    recommended_objective = str(diagnosis.get("recommended_objective") or "").strip()
    if recommended_objective:
        target_metrics.append(
            "kge" if recommended_objective == "composite" else recommended_objective
        )
    metrics = diagnosis.get("metrics") if isinstance(diagnosis.get("metrics"), dict) else {}
    for key in ("nse", "kge", "pbias_percent", "peak_ratio", "peak_timing_lag_days"):
        if key in metrics and key not in target_metrics:
            target_metrics.append(key)

    hypothesis = HydrologicHypothesis(
        hypothesis_id=hypothesis_id[:96],
        category=decision.hypothesis.value,
        phenomenon=phenomenon[:400],
        testable_claim=(
            "候选方案必须在独立 development Gate 中验证该诊断假设；final_test 不参与实验选择。"
        ),
        evidence_refs=evidence_refs,
        target_metrics=tuple(target_metrics),
    )
    prior_trials = TrialLedgerBuilder().build(view.evidence_summary).records
    plan = (planner or ExperimentPlanner()).plan(
        hypothesis=hypothesis,
        diagnosis=diagnosis,
        available_strategies=available,
        prior_trials=prior_trials,
        planner="agent",
    )
    plan = plan.model_copy(
        update={
            "reason_codes": tuple(
                dict.fromkeys(
                    (
                        *plan.reason_codes,
                        *(("skill_contract_preserved",) if skill_plan_bound else ()),
                        "campaign_objective_locked",
                    )
                )
            )
        }
    )
    reason_text = ",".join(plan.reason_codes) or "registered_plan"
    rationale = decision.rationale_summary
    audit_suffix = (
        f" [plan={plan.plan_id}; objective={view.hydro.campaign_objective}; "
        f"reasons={reason_text}]"
    )
    if diagnostic_objective and diagnostic_objective != view.hydro.campaign_objective:
        audit_suffix += f" [diagnostic_objective_ignored={diagnostic_objective}]"
    if audit_suffix not in rationale:
        rationale = (rationale + audit_suffix)[:600]

    return decision.model_copy(
        update={
            "strategy_id": plan.strategy_id,
            "param_groups": plan.param_groups,
            "objective": runtime_objective(plan.objective),
            "rationale_summary": rationale,
            "experiment_plan_id": plan.plan_id,
            "experiment_signature": plan.experiment_signature,
            "experiment_reason_codes": plan.reason_codes,
            "experiment_evidence_refs": plan.evidence_refs,
        }
    )
