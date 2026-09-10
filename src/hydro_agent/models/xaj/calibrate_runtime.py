"""Bounded XAJ calibration runtime executed inside the sandbox."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from hydro_agent.calibration.contracts import HydrologicGatePolicy
from hydro_agent.calibration.signatures import compute_hydrologic_signatures
from hydro_agent.evaluation.metrics import nse
from hydro_agent.execution.contracts import ExecutionRequest
from hydro_agent.optimization.param_groups import normalize_param_groups, resolve_param_names
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry

from .contracts import XajScheme
from .conversion import load_xaj_inputs
from .upstream import (
    MODEL_SHA256,
    MODEL_VERSION,
    load_calibratable_params,
    load_param_ranges,
    simulate,
)

_PHASE_POLICY = HydrologicGatePolicy()
_OBJECTIVES = {
    "nse",
    "peak",
    "composite",
    "water_balance",
    "recession",
    "routing_event",
    "joint",
}


def _load_streamflow(workspace: Path) -> dict[date, float]:
    path = workspace / "input/snapshot/streamflow.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["date", "discharge_m3s"]:
            raise ValueError("invalid streamflow columns")
        rows = list(reader)
    values = {}
    for row in rows:
        day = date.fromisoformat(row["date"])
        value = float(row["discharge_m3s"])
        if day in values:
            raise ValueError("duplicate streamflow dates")
        values[day] = value
    return values


def _sample_vector(rng, names, ranges, *, base_parameters=None, local_scale=None) -> dict[str, float]:
    parameters = {}
    for name in names:
        low, high = ranges[name]
        if local_scale is not None and base_parameters is not None and name in base_parameters:
            center = float(base_parameters[name])
            span = (high - low) * float(local_scale)
            low = max(low, center - span)
            high = min(high, center + span)
            if high < low:
                low, high = high, low
        if name == "L":
            lo_i = int(round(low))
            hi_i = int(round(high))
            if hi_i < lo_i:
                raise ValueError("invalid L range")
            parameters[name] = float(rng.integers(lo_i, hi_i + 1))
        else:
            sample_low = low if low > 0 else min(high, max(low, 1e-6))
            if sample_low > high:
                sample_low = high
            parameters[name] = float(rng.uniform(sample_low, high))
    return parameters


def _derived_seed(base_seed: int, action_run_id: str) -> int:
    """Reproducible per-action seed so repeated strategies explore new candidates."""
    digest = hashlib.sha256(action_run_id.encode("utf-8")).digest()
    return (int(base_seed) ^ int.from_bytes(digest[:8], "big")) % (2**32)


def _peak_score(obs: list[float], sim: list[float]) -> float:
    peak_obs = max(obs)
    peak_sim = max(sim)
    if peak_obs <= 0:
        return float("-inf")
    return float(1.0 - min(1.0, abs(peak_sim - peak_obs) / peak_obs))


def _normalized_phase_loss(metrics: dict[str, float], objective: str) -> float:
    p = _PHASE_POLICY
    if objective == "water_balance":
        return max(
            metrics["volume_rel_error"] / p.water_balance_rel_error,
            metrics["annual_volume_bias_mae"] / p.annual_water_balance_mae,
            metrics["seasonal_volume_bias_mae"] / p.seasonal_water_balance_mae,
        )
    if objective == "recession":
        return max(
            metrics["recession_relative_error"] / p.recession_relative_error,
            metrics["event_recession_rel_error_median"] / p.recession_relative_error,
        )
    if objective == "routing_event":
        return max(
            metrics["event_peak_rel_error_median"] / p.flood_peak_rel_error,
            metrics["event_peak_timing_steps_median"] / p.peak_timing_steps,
            metrics["event_volume_rel_error_median"] / p.flood_volume_rel_error,
        )
    if objective == "joint":
        return max(
            metrics["volume_rel_error"] / (p.water_balance_rel_error + p.max_water_balance_regression),
            metrics["event_peak_rel_error_median"] / (p.flood_peak_rel_error + p.max_event_error_regression),
            metrics["event_peak_timing_steps_median"] / (p.peak_timing_steps + 1.0),
            metrics["event_volume_rel_error_median"] / (p.flood_volume_rel_error + p.max_event_error_regression),
        )
    raise ValueError(f"unsupported phase objective: {objective}")


def _objective_score(
    obs: list[float],
    sim: list[float],
    aligned_dates: list[date],
    objective: str,
) -> tuple[float, dict[str, float]]:
    nse_value = float(nse(obs, sim))
    if objective == "nse":
        return nse_value, {"nse": nse_value}
    peak_value = _peak_score(obs, sim)
    if objective == "peak":
        return peak_value, {"nse": nse_value, "peak_score": peak_value}
    if objective == "composite":
        score = float(0.5 * nse_value + 0.5 * peak_value)
        return score, {"nse": nse_value, "peak_score": peak_value}

    times = tuple(
        datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        for day in aligned_dates
    )
    signatures = compute_hydrologic_signatures(obs, sim, times=times)
    metrics = dict(signatures.metrics)
    loss = float(_normalized_phase_loss(metrics, objective))
    metrics["phase_loss"] = loss
    if objective == "joint":
        # Joint refinement is constrained optimization: maximize NSE only inside the
        # hydrologically acceptable region. Outside it, first reduce the worst violation.
        score = nse_value if loss <= 1.0 else float(-1000.0 - loss)
    else:
        score = -loss
    return float(score), metrics


def run(workspace: Path) -> dict:
    import numpy as np

    request = ExecutionRequest.model_validate_json(
        (workspace / "execution-manifest.json").read_text(encoding="utf-8")
    )
    if (
        request.model_id != "xaj"
        or request.capability != "calibrate"
        or request.policy.device != "cpu"
    ):
        raise ValueError("unsupported XAJ calibration")
    strategy_id = str(request.parameters.get("strategy_id") or "xaj-bounded-v1")
    strategy = CalibrationStrategyRegistry().get(strategy_id)
    objective = str(request.parameters.get("objective") or strategy.objective)
    if objective not in _OBJECTIVES:
        raise ValueError(f"unsupported objective: {objective}")
    raw_groups = request.parameters.get("param_groups")
    groups = strategy.param_groups if raw_groups is None else normalize_param_groups(raw_groups)
    requested_tunable = set(resolve_param_names(groups))
    calibratable = set(load_calibratable_params())
    tunable = requested_tunable & calibratable
    if not tunable:
        raise ValueError(f"no calibratable XAJ parameters in groups={groups}")

    scheme, basin, dates, inputs = load_xaj_inputs(workspace)
    streamflow = _load_streamflow(workspace)
    ranges = load_param_ranges()
    if set(ranges) != set(scheme.PARAMETER_ORDER):
        raise ValueError("upstream parameter set mismatch")
    random_seed = _derived_seed(strategy.random_seed, request.action_run_id)
    rng = np.random.default_rng(random_seed)
    names = scheme.PARAMETER_ORDER
    base_parameters = dict(scheme.parameters)
    candidates: list[dict[str, float]] = [dict(base_parameters)]
    while len(candidates) < strategy.max_candidates:
        sampled = _sample_vector(
            rng,
            names,
            ranges,
            base_parameters=base_parameters,
            local_scale=strategy.local_scale,
        )
        merged = dict(base_parameters)
        for name in tunable:
            merged[name] = sampled[name]
        candidates.append(merged)

    best_score = float("-inf")
    best_index = 0
    best_parameters = dict(base_parameters)
    best_metrics: dict[str, float] = {}
    evaluated = 0
    for index, parameters in enumerate(candidates):
        try:
            candidate_scheme = XajScheme(
                model_id="xaj",
                warmup_days=scheme.warmup_days,
                parameters=parameters,
                routing=scheme.routing,
            )
        except Exception:
            continue
        if index and not 90 <= sum(parameters[k] for k in ("UM", "LM", "DM")) <= 220:
            continue
        if float(parameters.get("KI", 0.0)) + float(parameters.get("KG", 0.0)) >= 1.0:
            continue
        try:
            values = simulate(candidate_scheme, basin, inputs)
        except ValueError:
            if index == 0:
                raise
            continue
        sim_dates = dates[scheme.warmup_days:]
        obs: list[float] = []
        sim: list[float] = []
        aligned_dates: list[date] = []
        for day, runoff in zip(sim_dates, values):
            if day not in streamflow:
                continue
            aligned_dates.append(day)
            obs.append(streamflow[day])
            sim.append(float(runoff))
        if len(obs) < 2:
            continue
        try:
            score, score_metrics = _objective_score(obs, sim, aligned_dates, objective)
        except (ValueError, KeyError, ZeroDivisionError):
            continue
        evaluated += 1
        if score > best_score:
            best_score = score
            best_index = index
            best_parameters = dict(candidate_scheme.parameters)
            best_metrics = score_metrics

    if evaluated == 0:
        raise ValueError("no evaluable calibration candidates")
    candidate_payload = {
        "model_id": "xaj",
        "warmup_days": scheme.warmup_days,
        "parameters": best_parameters,
        "routing": scheme.routing.model_dump(),
        "model_version": MODEL_VERSION,
        "base_scheme_id": request.scheme_id,
        "strategy_id": strategy.strategy_id,
        "objective": objective,
        "param_groups": list(groups),
    }
    result = {
        "model_id": "xaj",
        "scheme_id": request.scheme_id,
        "data_snapshot_id": request.data_snapshot_id,
        "strategy_id": strategy.strategy_id,
        "evaluated_candidates": evaluated,
        "requested_candidates": strategy.max_candidates,
        "model_version": MODEL_VERSION,
        "model_source_sha256": MODEL_SHA256,
        "selected_candidate_index": best_index,
        "objective": objective,
        "param_groups": list(groups),
        "tunable_parameters": [name for name in names if name in tunable],
        "random_seed": random_seed,
        "objective_value": best_score,
        "objective_metrics": best_metrics,
        "candidate_parameters": best_parameters,
    }
    (workspace / "output/candidate-scheme.json").write_text(
        json.dumps(candidate_payload, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    (workspace / "output/result.json").write_text(
        json.dumps(result, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    (workspace / "output/calibration-result.json").write_text(
        json.dumps(result, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    run(args.workspace)


if __name__ == "__main__":
    main()
