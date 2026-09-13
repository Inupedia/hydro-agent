from hydro_agent.evaluation.gbt22482 import GbtAccuracyReport
from hydro_agent.optimization.contracts import GateDecision, GatePolicy


class GateEvaluator:
    """Evaluate two independent questions for a calibration candidate.

    Adoption asks whether the candidate is a meaningful, non-harmful improvement
    over the current working scheme. Qualification asks whether the candidate has
    already reached the preregistered absolute/standard target. Keeping these
    questions separate lets an improving but not-yet-qualified candidate become
    the baseline for the next controlled experiment.
    """

    def evaluate(
        self,
        base,
        candidate,
        policy: GatePolicy,
        *,
        gbt_report: GbtAccuracyReport | None = None,
    ) -> GateDecision:
        adoption_reasons: list[str] = []
        guardrail_failed = False
        for base_lead, cand_lead in zip(base.leads, candidate.leads):
            if cand_lead.nse - base_lead.nse < -policy.max_single_lead_drop:
                adoption_reasons.append("lead_guardrail")
                guardrail_failed = True
            if base_lead.high_flow_mae > 0:
                relative = (
                    cand_lead.high_flow_mae - base_lead.high_flow_mae
                ) / base_lead.high_flow_mae
                if relative > policy.max_high_flow_mae_relative_increase:
                    adoption_reasons.append("high_flow_guardrail")
                    guardrail_failed = True

        primary_delta = float(candidate.primary_score - base.primary_score)
        if guardrail_failed:
            status = "ROLLBACK"
            adoption_status = "REJECT"
        elif primary_delta >= policy.min_primary_delta:
            status = "ACCEPT"
            adoption_status = "ADOPT"
            adoption_reasons.append("meaningful_primary_improvement")
        else:
            status = "KEEP"
            adoption_status = "KEEP"
            adoption_reasons.append("insufficient_primary_improvement")

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
                qualification_reasons.append("gbt_scheme_grade_ok")
                qualification_reasons.append(f"scheme_grade={gbt_report.scheme_grade}")
            else:
                qualification_status = "UNQUALIFIED"
                qualification_reasons.append("insufficient_gbt_scheme_grade")
                qualification_reasons.append(f"scheme_grade={gbt_report.scheme_grade}")
                qualification_reasons.append(f"min_scheme_grade={policy.min_scheme_grade}")
        elif candidate.primary_score >= policy.accept_primary_floor:
            qualification_status = "QUALIFIED"
            qualification_reasons.append("primary_floor_ok")
        else:
            qualification_status = "UNQUALIFIED"
            qualification_reasons.append("insufficient_primary_skill")

        reasons = tuple(dict.fromkeys((*adoption_reasons, *qualification_reasons)))
        return GateDecision(
            status=status,  # type: ignore[arg-type]
            base_scheme_id=base.scheme_id,
            candidate_scheme_id=candidate.scheme_id,
            reasons=reasons,
            primary_delta=primary_delta,
            adoption_status=adoption_status,  # type: ignore[arg-type]
            qualification_status=qualification_status,  # type: ignore[arg-type]
            qualification_reasons=tuple(dict.fromkeys(qualification_reasons)),
            scheme_grade=scheme_grade,
            gbt_summary=gbt_summary,
        )
