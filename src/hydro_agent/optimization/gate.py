from __future__ import annotations

from hydro_agent.evaluation.gbt22482 import GbtAccuracyReport
from hydro_agent.optimization.contracts import GateDecision, GatePolicy


def _best_so_far_curve(history_primary, base_primary: float, candidate_primary: float) -> list[float]:
    """Normalize arbitrary historical Gate values into a monotone best-so-far curve."""
    curve: list[float] = []
    best = float("-inf")
    for raw in history_primary or ():
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value != value:
            continue
        best = max(best, value)
        curve.append(best)
    best = max(best, float(base_primary))
    current = max(best, float(candidate_primary))
    curve.append(current)
    return curve


def _convergence(curve: list[float], policy: GatePolicy) -> tuple[bool, float | None, float | None, float | None]:
    if len(curve) < policy.convergence_min_points:
        return False, None, None, None
    tail = curve[-policy.convergence_window :]
    if len(tail) < policy.convergence_min_points:
        return False, None, None, None
    gain = float(tail[-1] - tail[0])
    slope = float(gain / max(1, len(tail) - 1))
    span = float(max(tail) - min(tail))
    converged = (
        gain <= policy.convergence_gain_tolerance
        and abs(slope) <= policy.convergence_slope_tolerance
        and span <= policy.convergence_oscillation_tolerance
    )
    return converged, slope, gain, span


class GateEvaluator:
    """Evaluate one candidate and decide whether another calibration experiment is useful.

    The Gate is deliberately stateful through `history_primary`: hard budgets are only
    safety ceilings. Scientific stopping is driven by validation skill convergence.
    """

    def evaluate(
        self,
        base,
        candidate,
        policy: GatePolicy,
        *,
        gbt_report: GbtAccuracyReport | None = None,
        history_primary: tuple[float, ...] = (),
        prior_statuses: tuple[str, ...] = (),
        diagnosis_metrics: dict[str, float] | None = None,
    ) -> GateDecision:
        reasons: list[str] = []

        # Backward-compatible lead guardrails. Long-period Gate bundles may still expose
        # lead metrics, but the convergence decision is based on primary validation skill.
        if hasattr(base, "leads") and hasattr(candidate, "leads"):
            for base_lead, cand_lead in zip(base.leads, candidate.leads):
                if cand_lead.nse - base_lead.nse < -policy.max_single_lead_drop:
                    reasons.append("lead_guardrail")
                if base_lead.high_flow_mae > 0:
                    relative = (
                        cand_lead.high_flow_mae - base_lead.high_flow_mae
                    ) / base_lead.high_flow_mae
                    if relative > policy.max_high_flow_mae_relative_increase:
                        reasons.append("high_flow_guardrail")

        base_primary = float(base.primary_score)
        candidate_primary = float(candidate.primary_score)
        primary_delta = candidate_primary - base_primary
        improved = primary_delta > 1e-12
        meaningful_gain = primary_delta >= policy.min_primary_delta

        curve = _best_so_far_curve(history_primary, base_primary, candidate_primary)
        converged, slope, gain, span = _convergence(curve, policy)
        best_primary = curve[-1]

        scheme_grade = gbt_report.scheme_grade if gbt_report is not None else None
        gbt_summary = gbt_report.summary if gbt_report is not None else None
        gbt_ok = bool(gbt_report is not None and gbt_report.meets_min_grade)
        fallback_skill_ok = bool(
            gbt_report is None
            and candidate_primary >= policy.accept_primary_floor
            and candidate_primary >= policy.min_candidate_primary
        )

        diagnosis_metrics = diagnosis_metrics or {}
        forcing_warning = float(diagnosis_metrics.get("forcing_adequacy_warning", 0.0)) >= 0.5
        recent_failures = [s for s in prior_statuses[-policy.structural_warning_patience :] if s == "ROLLBACK"]
        repeated_failure = len(recent_failures) >= policy.structural_warning_patience

        # 1) Physical/lead guardrail violation: never promote a harmful candidate.
        if reasons:
            if forcing_warning and repeated_failure and best_primary < policy.accept_primary_floor:
                status = "STRUCTURAL_LIMIT"
                reasons.extend(("forcing_or_structure_warning", "repeated_validation_failure"))
                should_stop = True
            else:
                status = "ROLLBACK"
                should_stop = False
            adopt_candidate = False

        # 2) Final quality target met. Gate ends the search immediately.
        elif gbt_ok or fallback_skill_ok:
            status = "ACCEPT"
            adopt_candidate = improved or candidate_primary >= base_primary
            should_stop = True
            reasons.append("gbt_scheme_grade_ok" if gbt_ok else "nse_good_enough_fallback")
            if scheme_grade:
                reasons.append(f"scheme_grade={scheme_grade}")

        # 3) Best-so-far validation curve has flattened. More random search is no longer
        #    justified merely because budget remains.
        elif converged:
            adopt_candidate = improved
            should_stop = True
            if forcing_warning and best_primary < policy.accept_primary_floor:
                status = "STRUCTURAL_LIMIT"
                reasons.extend(("validation_curve_plateau", "forcing_or_structure_warning"))
            else:
                status = "CONVERGED"
                reasons.append("validation_curve_plateau")
            if gbt_report is not None and not gbt_ok:
                reasons.append("converged_below_required_gbt_grade")

        # 4) Candidate genuinely improves held-out performance: promote it to the new
        #    baseline and let the agent re-diagnose before choosing the next experiment.
        elif improved:
            status = "CONTINUE"
            adopt_candidate = True
            should_stop = False
            reasons.append("meaningful_validation_gain" if meaningful_gain else "small_validation_gain")
            if gbt_report is not None and not gbt_ok:
                reasons.append("improved_but_below_required_gbt_grade")

        # 5) No held-out gain. Roll back and require a fresh diagnosis/experiment.
        else:
            status = "ROLLBACK"
            adopt_candidate = False
            should_stop = False
            reasons.append("no_validation_gain")
            if forcing_warning:
                reasons.append("forcing_or_structure_warning")

        return GateDecision(
            status=status,  # type: ignore[arg-type]
            base_scheme_id=base.scheme_id,
            candidate_scheme_id=candidate.scheme_id,
            reasons=tuple(dict.fromkeys(reasons)),
            primary_delta=float(primary_delta),
            scheme_grade=scheme_grade,
            gbt_summary=gbt_summary,
            adopt_candidate=adopt_candidate,
            should_stop=should_stop,
            best_primary=float(best_primary),
            convergence_slope=slope,
            convergence_gain=gain,
            convergence_span=span,
            history_points=len(curve),
        )
