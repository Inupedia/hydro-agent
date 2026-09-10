from __future__ import annotations

from hydro_agent.calibration.contracts import (
    CalibrationPhase,
    HydrologicGatePolicy,
    PhaseGateDecision,
    PhaseGateStatus,
)


def _m(metrics: dict[str, float], key: str, default: float = 0.0) -> float:
    try:
        return float(metrics.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _ratio(value: float, threshold: float) -> float:
    if threshold <= 0:
        return 0.0 if value <= 0 else float("inf")
    return float(value / threshold)


class HydrologicPhaseGate:
    """Judge hydrologic phase quality; search convergence is handled separately."""

    def __init__(self, policy: HydrologicGatePolicy | None = None):
        self.policy = policy or HydrologicGatePolicy()

    def evaluate(
        self,
        *,
        phase: CalibrationPhase,
        base_scheme_id: str,
        candidate_scheme_id: str,
        experiment_id: str,
        base_metrics: dict[str, float],
        candidate_metrics: dict[str, float],
        development_grade_ok: bool = False,
    ) -> PhaseGateDecision:
        if phase == CalibrationPhase.WATER_BALANCE:
            return self._water_balance(base_scheme_id, candidate_scheme_id, experiment_id, base_metrics, candidate_metrics)
        if phase == CalibrationPhase.SOURCE_RECESSION:
            return self._source_recession(base_scheme_id, candidate_scheme_id, experiment_id, base_metrics, candidate_metrics)
        if phase == CalibrationPhase.ROUTING_EVENT:
            return self._routing_event(base_scheme_id, candidate_scheme_id, experiment_id, base_metrics, candidate_metrics)
        if phase == CalibrationPhase.JOINT_REFINE:
            return self._joint_refine(base_scheme_id, candidate_scheme_id, experiment_id, base_metrics, candidate_metrics)
        if phase == CalibrationPhase.DEVELOPMENT_VALIDATION:
            return self._development_validation(base_scheme_id, candidate_scheme_id, experiment_id, candidate_metrics, development_grade_ok)
        raise ValueError(f"phase {phase} is not a calibration Gate phase")

    def _decision(self, *, phase, status, base_id, candidate_id, experiment_id, metric, value, higher, adopt=False, advance=False, stop=False, reasons=(), metrics=None):
        return PhaseGateDecision(
            phase=phase,
            status=status,
            base_scheme_id=base_id,
            candidate_scheme_id=candidate_id,
            experiment_id=experiment_id,
            adopt_candidate=adopt,
            advance_phase=advance,
            stop_search=stop,
            progress_metric=metric,
            progress_value=float(value),
            higher_is_better=higher,
            reasons=tuple(reasons),
            metrics=metrics or {},
        )

    def _event_evidence_ok(self, metrics: dict[str, float]) -> bool:
        return _m(metrics, "flood_event_count") >= float(self.policy.min_flood_events)

    def _water_loss(self, metrics: dict[str, float]) -> float:
        p = self.policy
        return max(
            _ratio(_m(metrics, "volume_rel_error"), p.water_balance_rel_error),
            _ratio(_m(metrics, "annual_volume_bias_mae"), p.annual_water_balance_mae),
            _ratio(_m(metrics, "seasonal_volume_bias_mae"), p.seasonal_water_balance_mae),
        )

    def _water_balance(self, base_id, candidate_id, experiment_id, base, candidate):
        base_loss = self._water_loss(base)
        candidate_loss = self._water_loss(candidate)
        improved = candidate_loss + 1e-12 < base_loss
        passed = candidate_loss <= 1.0
        status = PhaseGateStatus.PHASE_PASS if passed else (PhaseGateStatus.CONTINUE if improved else PhaseGateStatus.ROLLBACK)
        return self._decision(
            phase=CalibrationPhase.WATER_BALANCE,
            status=status,
            base_id=base_id,
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            metric="water_balance_constraint_ratio",
            value=candidate_loss,
            higher=False,
            adopt=improved or passed,
            advance=passed,
            reasons=("water_balance_pass" if passed else "water_balance_improved" if improved else "water_balance_not_improved",),
            metrics={"base_phase_loss": base_loss, "candidate_phase_loss": candidate_loss},
        )

    def _source_recession(self, base_id, candidate_id, experiment_id, base, candidate):
        p = self.policy
        base_loss = max(
            _ratio(_m(base, "recession_relative_error"), p.recession_relative_error),
            _ratio(_m(base, "event_recession_rel_error_median"), p.recession_relative_error),
        )
        candidate_loss = max(
            _ratio(_m(candidate, "recession_relative_error"), p.recession_relative_error),
            _ratio(_m(candidate, "event_recession_rel_error_median"), p.recession_relative_error),
        )
        upstream_ok = _m(candidate, "volume_rel_error") <= _m(base, "volume_rel_error") + p.max_water_balance_regression
        improved = candidate_loss + 1e-12 < base_loss and upstream_ok
        passed = candidate_loss <= 1.0 and upstream_ok
        reasons = []
        if not upstream_ok:
            reasons.append("water_balance_regression")
        reasons.append("recession_pass" if passed else "recession_improved" if improved else "recession_not_improved")
        return self._decision(
            phase=CalibrationPhase.SOURCE_RECESSION,
            status=PhaseGateStatus.PHASE_PASS if passed else (PhaseGateStatus.CONTINUE if improved else PhaseGateStatus.ROLLBACK),
            base_id=base_id,
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            metric="recession_constraint_ratio",
            value=candidate_loss,
            higher=False,
            adopt=improved or passed,
            advance=passed,
            reasons=reasons,
            metrics={"base_phase_loss": base_loss, "candidate_phase_loss": candidate_loss},
        )

    def _routing_loss(self, metrics: dict[str, float]) -> float:
        p = self.policy
        return max(
            _ratio(_m(metrics, "event_peak_rel_error_median"), p.flood_peak_rel_error),
            _ratio(_m(metrics, "event_peak_timing_steps_median"), p.peak_timing_steps),
            _ratio(_m(metrics, "event_volume_rel_error_median"), p.flood_volume_rel_error),
        )

    def _routing_event(self, base_id, candidate_id, experiment_id, base, candidate):
        if not self._event_evidence_ok(candidate):
            return self._decision(
                phase=CalibrationPhase.ROUTING_EVENT,
                status=PhaseGateStatus.DATA_LIMIT,
                base_id=base_id,
                candidate_id=candidate_id,
                experiment_id=experiment_id,
                metric="flood_event_count",
                value=_m(candidate, "flood_event_count"),
                higher=True,
                stop=True,
                reasons=("insufficient_representative_flood_events",),
            )
        p = self.policy
        base_loss = self._routing_loss(base)
        candidate_loss = self._routing_loss(candidate)
        upstream_ok = _m(candidate, "volume_rel_error") <= _m(base, "volume_rel_error") + p.max_water_balance_regression
        improved = candidate_loss + 1e-12 < base_loss and upstream_ok
        passed = candidate_loss <= 1.0 and upstream_ok
        reasons = []
        if not upstream_ok:
            reasons.append("water_balance_regression")
        reasons.append("routing_event_pass" if passed else "routing_event_improved" if improved else "routing_event_not_improved")
        return self._decision(
            phase=CalibrationPhase.ROUTING_EVENT,
            status=PhaseGateStatus.PHASE_PASS if passed else (PhaseGateStatus.CONTINUE if improved else PhaseGateStatus.ROLLBACK),
            base_id=base_id,
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            metric="routing_event_constraint_ratio",
            value=candidate_loss,
            higher=False,
            adopt=improved or passed,
            advance=passed,
            reasons=reasons,
            metrics={"base_phase_loss": base_loss, "candidate_phase_loss": candidate_loss},
        )

    def _joint_constraints_ok(self, metrics: dict[str, float]) -> bool:
        p = self.policy
        return (
            self._event_evidence_ok(metrics)
            and _m(metrics, "volume_rel_error") <= p.water_balance_rel_error + p.max_water_balance_regression
            and _m(metrics, "event_peak_rel_error_median") <= p.flood_peak_rel_error + p.max_event_error_regression
            and _m(metrics, "event_volume_rel_error_median") <= p.flood_volume_rel_error + p.max_event_error_regression
            and _m(metrics, "event_peak_timing_steps_median") <= p.peak_timing_steps + 1.0
        )

    def _joint_refine(self, base_id, candidate_id, experiment_id, base, candidate):
        if not self._event_evidence_ok(candidate):
            return self._decision(
                phase=CalibrationPhase.JOINT_REFINE,
                status=PhaseGateStatus.DATA_LIMIT,
                base_id=base_id,
                candidate_id=candidate_id,
                experiment_id=experiment_id,
                metric="flood_event_count",
                value=_m(candidate, "flood_event_count"),
                higher=True,
                stop=True,
                reasons=("insufficient_representative_flood_events",),
            )
        p = self.policy
        base_nse = _m(base, "nse", -1e9)
        candidate_nse = _m(candidate, "nse", -1e9)
        constraints_ok = self._joint_constraints_ok(candidate)
        improved = candidate_nse > base_nse + 1e-12 and constraints_ok
        passed = candidate_nse >= p.joint_nse_floor and _m(candidate, "kge", -1e9) >= p.joint_kge_floor and constraints_ok
        reasons = []
        if not constraints_ok:
            reasons.append("hydrologic_guardrail_failed")
        reasons.append("joint_skill_pass" if passed else "joint_skill_improved" if improved else "joint_skill_not_improved")
        return self._decision(
            phase=CalibrationPhase.JOINT_REFINE,
            status=PhaseGateStatus.PHASE_PASS if passed else (PhaseGateStatus.CONTINUE if improved else PhaseGateStatus.ROLLBACK),
            base_id=base_id,
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            metric="development_nse",
            value=candidate_nse,
            higher=True,
            adopt=improved or passed,
            advance=passed,
            reasons=reasons,
            metrics={"base_phase_loss": -base_nse, "candidate_phase_loss": -candidate_nse},
        )

    def _development_validation(self, base_id, candidate_id, experiment_id, metrics, grade_ok):
        if not self._event_evidence_ok(metrics):
            return self._decision(
                phase=CalibrationPhase.DEVELOPMENT_VALIDATION,
                status=PhaseGateStatus.DATA_LIMIT,
                base_id=base_id,
                candidate_id=candidate_id,
                experiment_id=experiment_id,
                metric="flood_event_count",
                value=_m(metrics, "flood_event_count"),
                higher=True,
                stop=True,
                reasons=("insufficient_representative_flood_events",),
            )
        p = self.policy
        physical_ok = self._joint_constraints_ok(metrics)
        statistical_ok = _m(metrics, "nse", -1e9) >= p.joint_nse_floor and _m(metrics, "kge", -1e9) >= p.joint_kge_floor
        passed = physical_ok and statistical_ok and grade_ok
        reasons = []
        if not physical_ok:
            reasons.append("development_hydrologic_constraints_failed")
        if not statistical_ok:
            reasons.append("development_skill_floor_failed")
        if not grade_ok:
            reasons.append("development_gbt_grade_failed")
        if passed:
            reasons.append("development_validation_pass")
        return self._decision(
            phase=CalibrationPhase.DEVELOPMENT_VALIDATION,
            status=PhaseGateStatus.PHASE_PASS if passed else PhaseGateStatus.PLATEAU_FAIL,
            base_id=base_id,
            candidate_id=candidate_id,
            experiment_id=experiment_id,
            metric="development_nse",
            value=_m(metrics, "nse", -1e9),
            higher=True,
            advance=passed,
            stop=True,
            reasons=reasons,
        )
