"""Bounded XAJ calibration runtime executed inside the sandbox."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

from hydro_agent.evaluation.metrics import nse
from hydro_agent.execution.contracts import ExecutionRequest
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry

from .contracts import XajScheme
from .conversion import load_xaj_inputs, runoff_mm_day_to_m3s
from .upstream import load_param_ranges, load_xaj


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
            # Keep capacities strictly positive when upstream allows a zero lower bound.
            sample_low = low if low > 0 else min(high, max(low, 1e-6))
            if sample_low > high:
                sample_low = high
            parameters[name] = float(rng.uniform(sample_low, high))
    return parameters


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
    scheme, basin, dates, inputs = load_xaj_inputs(workspace)
    streamflow = _load_streamflow(workspace)
    ranges = load_param_ranges()
    if set(ranges) != set(scheme.PARAMETER_ORDER):
        raise ValueError("upstream parameter set mismatch")
    rng = np.random.default_rng(strategy.random_seed)
    names = scheme.PARAMETER_ORDER
    candidates: list[dict[str, float]] = [dict(scheme.parameters)]
    while len(candidates) < strategy.max_candidates:
        candidates.append(
            _sample_vector(
                rng,
                names,
                ranges,
                base_parameters=scheme.parameters,
                local_scale=strategy.local_scale,
            )
        )

    xaj = load_xaj()
    best_score = float("-inf")
    best_index = 0
    best_parameters = dict(scheme.parameters)
    evaluated = 0
    for index, parameters in enumerate(candidates):
        try:
            candidate_scheme = XajScheme(
                model_id="xaj", warmup_days=scheme.warmup_days, parameters=parameters
            )
        except Exception:
            continue
        q_sim, _ = xaj(
            inputs,
            np.asarray([candidate_scheme.parameter_vector()], dtype=float),
            return_state=False,
            warmup_length=scheme.warmup_days,
            normalized_params=False,
            name="xaj",
            source_type="sources",
            source_book="HF",
            time_interval_hours=24,
        )
        values = np.asarray(q_sim).reshape(-1)
        if values.size < 1 or not np.isfinite(values).all():
            continue
        # hydromodel may return full series or post-warmup only.
        if values.size == len(dates):
            sim_dates = dates[scheme.warmup_days :]
            sim_values = values[scheme.warmup_days :]
        else:
            sim_dates = dates[-values.size :]
            sim_values = values
        obs = []
        sim = []
        for day, runoff in zip(sim_dates, sim_values):
            if day not in streamflow:
                continue
            obs.append(streamflow[day])
            sim.append(runoff_mm_day_to_m3s(float(runoff), basin.area_km2))
        if len(obs) < 2:
            continue
        try:
            score = nse(obs, sim)
        except ValueError:
            continue
        evaluated += 1
        if score > best_score:
            best_score = score
            best_index = index
            best_parameters = dict(candidate_scheme.parameters)

    if evaluated == 0:
        raise ValueError("no evaluable calibration candidates")
    candidate_payload = {
        "model_id": "xaj",
        "warmup_days": scheme.warmup_days,
        "parameters": best_parameters,
        "base_scheme_id": request.scheme_id,
        "strategy_id": strategy.strategy_id,
    }
    result = {
        "model_id": "xaj",
        "scheme_id": request.scheme_id,
        "data_snapshot_id": request.data_snapshot_id,
        "strategy_id": strategy.strategy_id,
        "evaluated_candidates": strategy.max_candidates,
        "selected_candidate_index": best_index,
        "objective": strategy.objective,
        "objective_value": best_score,
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
