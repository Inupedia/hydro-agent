from __future__ import annotations

from collections.abc import Callable, Mapping
from math import isfinite

from hydro_agent.optimization.contracts import DirectionalProbeResult, ParameterDirectionalEffect

Evaluation = Mapping[str, object]
EvaluateFn = Callable[[dict[str, float]], Evaluation]


def _num(payload: Evaluation, key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, (int, float)) and isfinite(float(value)):
        return float(value)
    return None


def _objective_delta(candidate: Evaluation, baseline: Evaluation) -> float | None:
    a, b = _num(candidate, "objective_value"), _num(baseline, "objective_value")
    return None if a is None or b is None else a - b


def _supports(direction: str, baseline: Evaluation, candidate: Evaluation) -> tuple[bool, bool, dict[str, float]]:
    timing0, timing1 = _num(baseline, "peak_timing_lag_steps"), _num(candidate, "peak_timing_lag_steps")
    volume0, volume1 = _num(baseline, "volume_relative_error"), _num(candidate, "volume_relative_error")
    high0, high1 = _num(baseline, "high_flow_relative_error"), _num(candidate, "high_flow_relative_error")
    peak0, peak1 = _num(baseline, "peak_relative_error"), _num(candidate, "peak_relative_error")
    rise0, rise1 = _num(baseline, "rising_limb_mae"), _num(candidate, "rising_limb_mae")
    rec0, rec1 = _num(baseline, "recession_mae"), _num(candidate, "recession_mae")
    change: dict[str, float] = {}

    def guard(candidate_value, baseline_value, allowance):
        if candidate_value is None or baseline_value is None:
            return True
        return abs(candidate_value) <= abs(baseline_value) + allowance

    improved = False
    worsened = False
    if direction in {"accelerate_routing", "delay_routing"} and timing0 is not None and timing1 is not None:
        change["peak_timing_abs_lag_delta"] = abs(timing1) - abs(timing0)
        improved = abs(timing1) + 1e-12 < abs(timing0)
        worsened = abs(timing1) > abs(timing0) + 1e-12
        improved = improved and guard(volume1, volume0, 0.05) and guard(high1, high0, 0.05)
    elif direction in {"increase_water_loss", "decrease_water_loss"} and volume0 is not None and volume1 is not None:
        change["volume_abs_error_delta"] = abs(volume1) - abs(volume0)
        improved = abs(volume1) + 1e-12 < abs(volume0)
        worsened = abs(volume1) > abs(volume0) + 1e-12
        improved = improved and guard(timing1, timing0, 1.0)
    elif direction in {"increase_runoff_response", "decrease_runoff_response"} and peak0 is not None and peak1 is not None:
        change["peak_abs_error_delta"] = abs(peak1) - abs(peak0)
        improved = abs(peak1) + 1e-12 < abs(peak0)
        worsened = abs(peak1) > abs(peak0) + 1e-12
        improved = improved and guard(volume1, volume0, 0.05)
    elif direction == "increase_fast_component" and rise0 is not None and rise1 is not None:
        change["rising_limb_mae_delta"] = rise1 - rise0
        improved, worsened = rise1 < rise0, rise1 > rise0
    elif direction == "increase_slow_component" and rec0 is not None and rec1 is not None:
        change["recession_mae_delta"] = rec1 - rec0
        improved, worsened = rec1 < rec0, rec1 > rec0
    return improved, worsened, change


def run_directional_probe(*, baseline: dict[str, float], bounds: dict[str, tuple[float, float]],
                          parameters: tuple[str, ...], relative_step: float, evaluate: EvaluateFn,
                          requested_direction: str) -> DirectionalProbeResult:
    if not 0 < relative_step <= 1:
        raise ValueError("relative_step must be in (0, 1]")
    base_eval = evaluate(dict(baseline))
    effects = []
    supporting, contradictory, evidence = [], [], []

    for name in parameters:
        if name not in baseline or name not in bounds:
            raise ValueError(f"missing baseline/bounds for {name}")
        low, high = bounds[name]
        if high <= low:
            raise ValueError(f"invalid bounds for {name}")
        step = relative_step * (high - low)
        neg_value = max(low, baseline[name] - step)
        pos_value = min(high, baseline[name] + step)
        neg_params, pos_params = dict(baseline), dict(baseline)
        neg_params[name], pos_params[name] = neg_value, pos_value
        neg_eval, pos_eval = evaluate(neg_params), evaluate(pos_params)
        n_support, n_worse, n_change = _supports(requested_direction, base_eval, neg_eval)
        p_support, p_worse, p_change = _supports(requested_direction, base_eval, pos_eval)
        if n_support or p_support:
            supporting.append(name)
            chosen = n_change if n_support and not p_support else p_change
        elif n_worse or p_worse:
            contradictory.append(name)
            chosen = p_change or n_change
        else:
            chosen = p_change or n_change
        for payload in (neg_eval, pos_eval):
            ids = payload.get("evidence_ids")
            if isinstance(ids, (list, tuple)):
                evidence.extend(str(x) for x in ids)
        effects.append(ParameterDirectionalEffect(
            parameter=name,
            negative_delta=_objective_delta(neg_eval, base_eval),
            positive_delta=_objective_delta(pos_eval, base_eval),
            expected_signature_change=chosen,
        ))

    if supporting and not contradictory:
        status = "supported"
    elif contradictory and not supporting:
        status = "refuted"
    else:
        status = "inconclusive"
    return DirectionalProbeResult(
        requested_direction=requested_direction,
        status=status,
        parameter_effects=tuple(effects),
        supporting_parameters=tuple(supporting),
        contradictory_parameters=tuple(contradictory),
        evidence_ids=tuple(dict.fromkeys(evidence)),
    )
