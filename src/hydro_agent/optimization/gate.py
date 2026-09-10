from hydro_agent.evaluation.gbt22482 import GbtAccuracyReport, grade_meets_min
from hydro_agent.optimization.contracts import GateDecision, GatePolicy


class GateEvaluator:
    """Generic forecast-candidate Gate; staged calibration uses calibration.phase_gate."""

    def evaluate(
        self,
        base,
        candidate,
        policy: GatePolicy,
        *,
        gbt_report: GbtAccuracyReport | None = None,
    ) -> GateDecision:
        reasons: list[str] = []
        for base_lead, cand_lead in zip(base.leads, candidate.leads):
            if cand_lead.nse - base_lead.nse < -policy.max_single_lead_drop:
                reasons.append("lead_guardrail")
            if base_lead.high_flow_mae > 0:
                relative = (
                    cand_lead.high_flow_mae - base_lead.high_flow_mae
                ) / base_lead.high_flow_mae
                if relative > policy.max_high_flow_mae_relative_increase:
                    reasons.append("high_flow_guardrail")
        primary_delta = float(candidate.primary_score - base.primary_score)
        scheme_grade = gbt_report.scheme_grade if gbt_report is not None else None
        gbt_summary = gbt_report.summary if gbt_report is not None else None

        if reasons:
            status = "ROLLBACK"
        elif candidate.primary_score < policy.min_candidate_primary:
            status = "KEEP"
            reasons.append("insufficient_absolute_skill")
        elif policy.require_gbt_grade:
            if gbt_report is not None and gbt_report.meets_min_grade:
                status = "ACCEPT"
                reasons.append("gbt_scheme_grade_ok")
                reasons.append(f"scheme_grade={gbt_report.scheme_grade}")
            elif gbt_report is not None:
                status = "KEEP"
                reasons.append("insufficient_gbt_scheme_grade")
                reasons.append(f"scheme_grade={gbt_report.scheme_grade}")
                reasons.append(f"min_scheme_grade={policy.min_scheme_grade}")
            elif candidate.primary_score >= policy.accept_primary_floor:
                status = "ACCEPT"
                reasons.append("nse_good_enough_fallback")
            else:
                status = "KEEP"
                reasons.append("insufficient_gbt_or_nse")
        elif candidate.primary_score >= policy.accept_primary_floor:
            status = "ACCEPT"
            reasons.append("nse_good_enough")
        else:
            status = "KEEP"
            reasons.append("insufficient_gbt_scheme_grade")
            if primary_delta >= policy.min_primary_delta:
                reasons.append("nse_improved_but_below_gbt_grade")

        if scheme_grade is None and gbt_report is None:
            grade_meets_min(
                "丙" if candidate.primary_score >= 0.5 else "不合格",
                policy.min_scheme_grade,
            )

        return GateDecision(
            status=status,  # type: ignore[arg-type]
            base_scheme_id=base.scheme_id,
            candidate_scheme_id=candidate.scheme_id,
            reasons=tuple(dict.fromkeys(reasons)),
            primary_delta=primary_delta,
            scheme_grade=scheme_grade,
            gbt_summary=gbt_summary,
        )
