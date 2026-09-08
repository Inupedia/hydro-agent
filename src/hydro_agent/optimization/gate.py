from hydro_agent.optimization.contracts import GateDecision, GatePolicy


class GateEvaluator:
    def evaluate(self, base, candidate, policy: GatePolicy) -> GateDecision:
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
        if reasons:
            status = "ROLLBACK"
        elif primary_delta >= policy.min_primary_delta:
            status = "ACCEPT"
        else:
            status = "KEEP"
            reasons.append("insufficient_primary_delta")
        return GateDecision(
            status=status,  # type: ignore[arg-type]
            base_scheme_id=base.scheme_id,
            candidate_scheme_id=candidate.scheme_id,
            reasons=tuple(dict.fromkeys(reasons)),
            primary_delta=primary_delta,
        )
