from hydro_agent.evaluation.gbt22482 import GbtAccuracyReport
from hydro_agent.optimization.contracts import GateDecision, GatePolicy


class GateEvaluator:
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
            # The standard is a knowledge dependency, not a numeric fallback in
            # Gate code. If the deterministic GB/T report is missing, the safe
            # outcome is KEEP until the knowledge-backed evaluation is available.
            if gbt_report is None:
                status = "KEEP"
                reasons.append("missing_standard_evaluation")
            elif gbt_report.meets_min_grade:
                status = "ACCEPT"
                reasons.append("gbt_scheme_grade_ok")
                reasons.append(f"scheme_grade={gbt_report.scheme_grade}")
            else:
                status = "KEEP"
                reasons.append("insufficient_gbt_scheme_grade")
                reasons.append(f"scheme_grade={gbt_report.scheme_grade}")
                reasons.append(f"min_scheme_grade={policy.min_scheme_grade}")
        elif candidate.primary_score >= policy.accept_primary_floor:
            # Non-standard research policies may still use a numeric floor. This
            # branch is intentionally unreachable for require_gbt_grade=True.
            status = "ACCEPT"
            reasons.append("primary_floor_ok")
        else:
            status = "KEEP"
            reasons.append("insufficient_primary_skill")
            if primary_delta >= policy.min_primary_delta:
                reasons.append("primary_improved_but_below_policy_floor")

        return GateDecision(
            status=status,  # type: ignore[arg-type]
            base_scheme_id=base.scheme_id,
            candidate_scheme_id=candidate.scheme_id,
            reasons=tuple(dict.fromkeys(reasons)),
            primary_delta=primary_delta,
            scheme_grade=scheme_grade,
            gbt_summary=gbt_summary,
        )
