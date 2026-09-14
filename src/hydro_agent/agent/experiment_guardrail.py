"""Deterministic ExperimentPlan guardrail for A07 decisions."""

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
        if item.action == ActionCode.A06_DIAGNOSE:
            return item
    return None


def apply_experiment_plan_guardrail(
    view: WorldStateView,
    decision: AgentDecision,
    *,
    planner: ExperimentPlanner | None = None,
) -> AgentDecision:
    """Replace free-form A07 choices with an evidence-conditioned registered plan.

    The LLM still decides whether optimization is warranted. Once A07 is chosen,
    strategy/groups are selected from persisted diagnosis and prior trial outcomes.
    A fixed search policy keeps the preregistered campaign objective immutable;
    adaptive search lets the persisted hydrologic diagnosis choose the numerical
    objective while the independent development Gate remains the comparison ruler.
    """

    if decision.action != ActionCode.A07_OPTIMIZE:
        return decision
    available = tuple(view.hydro.available_strategies)
    if not available:
        return decision

    diagnosis = dict(view.hydro.diagnosis or {})
    diagnostic_objective = str(diagnosis.get("recommended_objective") or "").strip()
    objective_is_locked = view.hydro.search_objective_policy == "fixed"
    if objective_is_locked:
        # Diagnosis may identify an error pattern, but a fixed campaign keeps the
        # numerical scoring ruler identical across every optimization experiment.
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
    policy_reason = (
        "campaign_objective_locked" if objective_is_locked else "adaptive_search_objective"
    )
    plan = plan.model_copy(
        update={"reason_codes": tuple(dict.fromkeys((*plan.reason_codes, policy_reason)))}
    )
    effective_objective = runtime_objective(plan.objective)
    reason_text = ",".join(plan.reason_codes) or "registered_plan"
    rationale = decision.rationale_summary
    audit_suffix = (
        f" [plan={plan.plan_id}; objective={effective_objective}; "
        f"policy={view.hydro.search_objective_policy}; reasons={reason_text}]"
    )
    if (
        objective_is_locked
        and diagnostic_objective
        and diagnostic_objective != view.hydro.campaign_objective
    ):
        audit_suffix += f" [diagnostic_objective_ignored={diagnostic_objective}]"
    if not objective_is_locked and decision.objective and decision.objective != effective_objective:
        audit_suffix += f" [proposed_objective_overridden={decision.objective}]"
    if audit_suffix not in rationale:
        rationale = (rationale + audit_suffix)[:600]

    return decision.model_copy(
        update={
            "strategy_id": plan.strategy_id,
            "param_groups": plan.param_groups,
            "objective": effective_objective,
            "rationale_summary": rationale,
            "experiment_plan_id": plan.plan_id,
            "experiment_signature": plan.experiment_signature,
            "experiment_reason_codes": plan.reason_codes,
            "experiment_evidence_refs": plan.evidence_refs,
        }
    )
