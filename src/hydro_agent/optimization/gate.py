from hydro_agent.evaluation.gbt22482 import GbtAccuracyReport
from hydro_agent.optimization.contracts import GateDecision, GatePolicy


class GateEvaluator:
    """Evaluate adoption and absolute qualification on independent development evidence."""

    def evaluate(
        self,
        base,
        candidate,
        policy: GatePolicy,
        *,
        gbt_report: GbtAccuracyReport | None = None,
    ) -> GateDecision:
        base_by_lead = {item.lead: item for item in base.leads}
        candidate_by_lead = {item.lead: item for item in candidate.leads}
        if not base_by_lead or set(base_by_lead) != set(candidate_by_lead):
            raise ValueError("Gate requires identical evaluated leads for base and candidate")

        adoption_reasons: list[str] = []
        guardrail_failed = False
        for lead in sorted(base_by_lead):
            base_lead = base_by_lead[lead]
            cand_lead = candidate_by_lead[lead]
            if base_lead.sample_count != cand_lead.sample_count:
                raise ValueError(f"Gate lead-{lead} sample count mismatch")
            if cand_lead.nse - base_lead.nse < -policy.max_single_lead_drop:
                adoption_reasons.append(f"lead_{lead}_guardrail")
                guardrail_failed = True
            if base_lead.high_flow_mae > 0:
                relative = (
                    cand_lead.high_flow_mae - base_lead.high_flow_mae
                ) / base_lead.high_flow_mae
                if relative > policy.max_high_flow_mae_relative_increase:
                    adoption_reasons.append(f"lead_{lead}_high_flow_guardrail")
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
