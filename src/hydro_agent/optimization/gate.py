from __future__ import annotations

from statistics import median
from typing import Any

from hydro_agent.evaluation.gbt22482 import GbtAccuracyReport
from hydro_agent.optimization.contracts import (
    GateDecision,
    GatePolicy,
    ResearchGateDecision,
)


def _lead_guardrails(base, candidate, policy: GatePolicy) -> tuple[list[str], bool]:
    base_by_lead = {item.lead: item for item in base.leads}
    candidate_by_lead = {item.lead: item for item in candidate.leads}
    if not base_by_lead or set(base_by_lead) != set(candidate_by_lead):
        raise ValueError("Gate requires identical evaluated leads for base and candidate")

    reasons: list[str] = []
    failed = False
    for lead in sorted(base_by_lead):
        base_lead = base_by_lead[lead]
        cand_lead = candidate_by_lead[lead]
        if base_lead.sample_count != cand_lead.sample_count:
            raise ValueError(f"Gate lead-{lead} sample count mismatch")
        if cand_lead.nse - base_lead.nse < -policy.max_single_lead_drop:
            reasons.append(f"lead_{lead}_guardrail")
            failed = True
        if base_lead.high_flow_mae > 0:
            relative = (
                cand_lead.high_flow_mae - base_lead.high_flow_mae
            ) / base_lead.high_flow_mae
            if relative > policy.max_high_flow_mae_relative_increase:
                reasons.append(f"lead_{lead}_high_flow_guardrail")
                failed = True
    return reasons, failed


def _event_rows(raw: object) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, list):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        event_id = str(item.get("event_id") or f"event-{index + 1:03d}")
        rows[event_id] = item
    return rows


def _event_guardrails(
    event_comparison: dict[str, object] | None,
    policy: GatePolicy,
) -> tuple[str, ...]:
    if not event_comparison:
        return ()
    base = _event_rows(event_comparison.get("base"))
    candidate = _event_rows(event_comparison.get("candidate"))
    ids = tuple(sorted(set(base) & set(candidate)))
    if len(ids) < policy.min_event_guardrail_count:
        return ()

    specs = (
        ("peak_relative_error", policy.max_event_peak_error_increase, "event_peak_guardrail"),
        ("timing_lag_steps", policy.max_event_timing_error_increase, "event_timing_guardrail"),
        ("volume_relative_error", policy.max_event_volume_error_increase, "event_volume_guardrail"),
    )
    reasons: list[str] = []
    materially_worsened = 0
    comparable_events = 0

    for key, tolerance, reason in specs:
        base_values: list[float] = []
        candidate_values: list[float] = []
        for event_id in ids:
            b = base[event_id].get(key)
            c = candidate[event_id].get(key)
            if isinstance(b, (int, float)) and isinstance(c, (int, float)):
                base_values.append(abs(float(b)))
                candidate_values.append(abs(float(c)))
        if len(base_values) >= policy.min_event_guardrail_count:
            if median(candidate_values) - median(base_values) > tolerance + 1e-12:
                reasons.append(reason)

    for event_id in ids:
        comparisons = 0
        worsened = False
        for key, tolerance, _reason in specs:
            b = base[event_id].get(key)
            c = candidate[event_id].get(key)
            if not isinstance(b, (int, float)) or not isinstance(c, (int, float)):
                continue
            comparisons += 1
            if abs(float(c)) - abs(float(b)) > tolerance + 1e-12:
                worsened = True
        if comparisons:
            comparable_events += 1
            materially_worsened += int(worsened)

    if comparable_events >= policy.min_event_guardrail_count:
        fraction = materially_worsened / comparable_events
        if fraction > policy.max_materially_worsened_event_fraction + 1e-12:
            reasons.append("materially_worsened_event_fraction_guardrail")
    return tuple(dict.fromkeys(reasons))


class ResearchGateEvaluator:
    """Decide research adoption using independent development evidence only."""

    def evaluate(
        self,
        base,
        candidate,
        policy: GatePolicy,
        *,
        event_comparison: dict[str, object] | None = None,
    ) -> ResearchGateDecision:
        lead_reasons, lead_failed = _lead_guardrails(base, candidate, policy)
        event_reasons = _event_guardrails(event_comparison, policy)
        guardrail_failed = lead_failed or bool(event_reasons)
        primary_delta = float(candidate.primary_score - base.primary_score)

        reasons = list(lead_reasons)
        reasons.extend(event_reasons)
        if guardrail_failed:
            status = "ROLLBACK"
            adoption_status = "REJECT"
        elif primary_delta >= policy.min_primary_delta:
            status = "ACCEPT"
            adoption_status = "ADOPT"
            reasons.append("meaningful_primary_improvement")
        else:
            status = "KEEP"
            adoption_status = "KEEP"
            reasons.append("insufficient_primary_improvement")

        if candidate.primary_score < policy.min_candidate_primary:
            research_qualification = "UNQUALIFIED"
            reasons.append("insufficient_absolute_skill")
        elif guardrail_failed:
            research_qualification = "UNQUALIFIED"
            reasons.append("research_guardrail_failed")
        else:
            research_qualification = "QUALIFIED"
            reasons.append("research_evidence_qualified")

        return ResearchGateDecision(
            status=status,  # type: ignore[arg-type]
            base_scheme_id=base.scheme_id,
            candidate_scheme_id=candidate.scheme_id,
            adoption_status=adoption_status,  # type: ignore[arg-type]
            research_qualification=research_qualification,  # type: ignore[arg-type]
            primary_delta=primary_delta,
            reasons=tuple(dict.fromkeys(reasons)),
            event_guardrail_reasons=event_reasons,
        )


class GateEvaluator:
    """Compatibility gate: research decision + independent standard qualification."""

    def evaluate(
        self,
        base,
        candidate,
        policy: GatePolicy,
        *,
        gbt_report: GbtAccuracyReport | None = None,
        event_comparison: dict[str, object] | None = None,
    ) -> GateDecision:
        research = ResearchGateEvaluator().evaluate(
            base,
            candidate,
            policy,
            event_comparison=event_comparison,
        )
        qualification_reasons: list[str] = []
        scheme_grade = gbt_report.scheme_grade if gbt_report is not None else None
        gbt_summary = gbt_report.summary if gbt_report is not None else None

        if candidate.primary_score < policy.min_candidate_primary:
            qualification_status = "UNQUALIFIED"
            qualification_reasons.append("insufficient_absolute_skill")
        elif policy.require_gbt_grade:
            if gbt_report is None:
                qualification_status = "NOT_EVALUATED"
                qualification_reasons.append("missing_standard_evaluation")
            elif gbt_report.meets_min_grade:
                qualification_status = "QUALIFIED"
                qualification_reasons.extend(
                    ("gbt_scheme_grade_ok", f"scheme_grade={gbt_report.scheme_grade}")
                )
            else:
                qualification_status = "UNQUALIFIED"
                qualification_reasons.extend(
                    (
                        "insufficient_gbt_scheme_grade",
                        f"scheme_grade={gbt_report.scheme_grade}",
                        f"min_scheme_grade={policy.min_scheme_grade}",
                    )
                )
        elif candidate.primary_score >= policy.accept_primary_floor:
            qualification_status = "QUALIFIED"
            qualification_reasons.append("primary_floor_ok")
        else:
            qualification_status = "UNQUALIFIED"
            qualification_reasons.append("insufficient_primary_skill")

        reasons = tuple(dict.fromkeys((*research.reasons, *qualification_reasons)))
        return GateDecision(
            status=research.status,
            base_scheme_id=research.base_scheme_id,
            candidate_scheme_id=research.candidate_scheme_id,
            reasons=reasons,
            primary_delta=research.primary_delta,
            adoption_status=research.adoption_status,
            research_qualification=research.research_qualification,
            qualification_status=qualification_status,  # type: ignore[arg-type]
            qualification_reasons=tuple(dict.fromkeys(qualification_reasons)),
            scheme_grade=scheme_grade,
            gbt_summary=gbt_summary,
        )
