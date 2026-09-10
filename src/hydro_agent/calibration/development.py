from __future__ import annotations

from hydro_agent.calibration.contracts import CalibrationPhase, HydrologicGatePolicy


def _metric(metrics: dict[str, float], key: str, default: float = 0.0) -> float:
    try:
        return float(metrics.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def infer_rework_phase(
    metrics: dict[str, float],
    policy: HydrologicGatePolicy | None = None,
) -> CalibrationPhase:
    """Attribute development-validation failure to the earliest failed process.

    The ordering follows traditional XAJ practice: water balance -> source/recession ->
    routing/event -> joint statistical refinement. Earlier-process failures take
    precedence because later parameters must not compensate for upstream structural bias.
    """

    p = policy or HydrologicGatePolicy()

    water_failed = (
        _metric(metrics, "volume_rel_error") > p.water_balance_rel_error
        or _metric(metrics, "annual_volume_bias_mae") > p.annual_water_balance_mae
        or _metric(metrics, "seasonal_volume_bias_mae") > p.seasonal_water_balance_mae
    )
    if water_failed:
        return CalibrationPhase.WATER_BALANCE

    recession_failed = max(
        _metric(metrics, "recession_relative_error"),
        _metric(metrics, "event_recession_rel_error_median"),
    ) > p.recession_relative_error
    if recession_failed:
        return CalibrationPhase.SOURCE_RECESSION

    routing_failed = (
        _metric(metrics, "event_peak_rel_error_median") > p.flood_peak_rel_error
        or _metric(metrics, "event_peak_timing_steps_median") > p.peak_timing_steps
        or _metric(metrics, "event_volume_rel_error_median") > p.flood_volume_rel_error
    )
    if routing_failed:
        return CalibrationPhase.ROUTING_EVENT

    return CalibrationPhase.JOINT_REFINE
