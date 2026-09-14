"""XAJ calibration runtime: scientific strategy + pluggable numerical optimizer."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

from hydro_agent.evaluation.hydrograph import build_comparison, write_bundle
from hydro_agent.evaluation.metrics import kge, nse
from hydro_agent.execution.contracts import ExecutionRequest
from hydro_agent.optimization.dds import optimize_dds
from hydro_agent.optimization.morris import screen_morris
from hydro_agent.optimization.param_groups import normalize_param_groups, resolve_param_names
from hydro_agent.optimization.sceua import optimize_sceua
from hydro_agent.optimization.search_evidence import analyze_search_boundaries
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry

from .calibration_state import (
    load_dds_checkpoint,
    load_evaluation_cache,
    load_morris_checkpoint,
    load_screening_result,
    persist_evaluation,
    save_dds_checkpoint,
    save_morris_checkpoint,
    save_screening_result,
)
from .contracts import XajScheme
from .conversion import load_xaj_inputs
from .upstream import MODEL_SHA256, MODEL_VERSION, load_param_ranges, simulate


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


def _sample_vector(rng, names, bounds) -> dict[str, float]:
    parameters = {}
    for name in names:
        low, high = bounds[name]
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


def _peak_score(obs: list[float], sim: list[float]) -> float:
    peak_obs = max(obs)
    peak_sim = max(sim)
    if peak_obs <= 0:
        return float("-inf")
    return float(1.0 - min(1.0, abs(peak_sim - peak_obs) / peak_obs))


def _objective_score(obs: list[float], sim: list[float], objective: str) -> float:
    if objective == "nse":
        return float(nse(obs, sim))
    if objective == "peak":
        return _peak_score(obs, sim)
    if objective == "composite":
        # Backward-compatible objective name, but no longer an ad-hoc weighted
        # mixture of NSE/one global peak/volume/timing. KGE is a standard whole-
        # series efficiency criterion that jointly reflects correlation,
        # variability and bias; peak/timing behaviour remains explicit evidence
        # and Gate guardrails instead of being hidden inside arbitrary weights.
        return float(kge(obs, sim))
    raise ValueError(f"unsupported objective: {objective}")


def _search_bounds(
    *,
    tunable_names: tuple[str, ...],
    ranges: dict[str, tuple[float, float]],
    base_parameters: dict[str, float],
    local_scale: float | None,
) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for name in tunable_names:
        low, high = (float(v) for v in ranges[name])
        if local_scale is not None:
            center = float(base_parameters[name])
            span = (high - low) * float(local_scale)
            low = max(low, center - span)
            high = min(high, center + span)
        if high <= low:
            raise ValueError(f"invalid search bounds for {name}: {low}..{high}")
        out[name] = (low, high)
    return out


def _canonical_tunable(
    values: dict[str, float], bounds: dict[str, tuple[float, float]]
) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, value in values.items():
        low, high = bounds[name]
        clipped = min(max(float(value), low), high)
        if name == "L":
            clipped = float(min(max(int(round(clipped)), int(round(low))), int(round(high))))
        out[name] = clipped
    return out


def _screening_trajectories(*, requested: int, dimension: int, evaluation_budget: int) -> int:
    """Cap Morris work so at least half (and at least 32 calls) remains for search."""

    if requested <= 0 or dimension <= 4:
        return 0
    optimizer_reserve = min(evaluation_budget, max(32, evaluation_budget // 2))
    screening_allowance = max(0, evaluation_budget - optimizer_reserve)
    by_budget = screening_allowance // (dimension + 1)
    return max(0, min(requested, by_budget))


def _screening_active_names(
    payload: dict[str, object], tunable_names: tuple[str, ...]
) -> tuple[str, ...]:
    universe = tuple(str(name) for name in payload.get("parameter_universe") or ())
    if universe != tunable_names:
        raise ValueError("persisted Morris result parameter universe mismatch")
    active = tuple(str(name) for name in payload.get("active_parameters") or ())
    if not active or any(name not in set(tunable_names) for name in active):
        raise ValueError("persisted Morris result active-parameter mismatch")
    return active


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
    if strategy.optimizer == "manual":
        raise ValueError("manual strategy must not enter numerical calibration runtime")

    objective = str(request.parameters.get("objective") or strategy.objective)
    if objective not in {"nse", "peak", "composite"}:
        raise ValueError(f"unsupported objective: {objective}")
    raw_groups = request.parameters.get("param_groups")
    groups = strategy.param_groups if raw_groups is None else normalize_param_groups(raw_groups)

    scheme, basin, dates, inputs = load_xaj_inputs(workspace)
    streamflow = _load_streamflow(workspace)
    ranges = load_param_ranges()
    if set(ranges) != set(scheme.PARAMETER_ORDER):
        raise ValueError("upstream parameter set mismatch")

    all_names = tuple(scheme.PARAMETER_ORDER)
    tunable_set = set(resolve_param_names(groups))
    tunable_names = tuple(name for name in all_names if name in tunable_set)
    if not tunable_names:
        raise ValueError("no tunable XAJ parameters resolved from param_groups")

    base_parameters = {name: float(value) for name, value in scheme.parameters.items()}
    bounds = _search_bounds(
        tunable_names=tunable_names,
        ranges=ranges,
        base_parameters=base_parameters,
        local_scale=strategy.local_scale,
    )

    # Each completed physical model execution is content-addressed in the
    # workspace, including runs that cannot produce a finite objective. After a
    # worker restart, score_fn can therefore replay optimizer state without
    # re-running or under-counting an already evaluated XAJ parameter set.
    cache = load_evaluation_cache(workspace)
    restored_model_evaluations = len(cache)
    model_evaluations = len(cache)

    def evaluate(values: dict[str, float]) -> float | None:
        nonlocal model_evaluations
        tuned = _canonical_tunable(values, bounds)
        merged = dict(base_parameters)
        merged.update(tuned)
        key = tuple((name, float(merged[name])) for name in all_names)
        cached = cache.get(key)
        if cached is not None:
            return cached[0]

        try:
            candidate_scheme = XajScheme(
                model_id="xaj",
                warmup_days=scheme.warmup_days,
                parameters=merged,
                routing=scheme.routing,
            )
        except Exception:
            return None

        # Keep the teacher-workflow storage-capacity sanity constraint.
        if not 90 <= sum(candidate_scheme.parameters[k] for k in ("UM", "LM", "DM")) <= 220:
            return None

        try:
            full_values = simulate(candidate_scheme, basin, inputs, include_warmup=True)
        except ValueError:
            return None

        values_after_warmup = full_values[scheme.warmup_days :]
        sim_dates = dates[scheme.warmup_days :]
        obs: list[float] = []
        sim: list[float] = []
        for day, runoff in zip(sim_dates, values_after_warmup):
            if day not in streamflow:
                continue
            obs.append(float(streamflow[day]))
            sim.append(float(runoff))

        persisted_score: float | None = None
        if len(obs) >= 2:
            try:
                score = _objective_score(obs, sim, objective)
            except ValueError:
                score = float("nan")
            if np.isfinite(score):
                persisted_score = float(score)

        entry = (
            persisted_score,
            [float(v) for v in full_values],
            {name: float(value) for name, value in candidate_scheme.parameters.items()},
        )
        persist_evaluation(
            workspace,
            key=key,
            score=persisted_score,
            full_values=entry[1],
            parameters=entry[2],
        )
        cache[key] = entry
        model_evaluations = len(cache)
        return persisted_score

    initial_tunable = {name: base_parameters[name] for name in tunable_names}
    active_names = tunable_names
    sensitivity_evidence: dict[str, object] = {
        "method": strategy.sensitivity_method,
        "status": "not_run",
        "parameter_universe": list(tunable_names),
        "active_parameters": list(tunable_names),
        "screened_out_parameters": [],
        "model_evaluations": 0,
    }
    screening_model_evaluations = 0
    screening_score_calls = 0
    morris_resume = False
    screening_result_restored = False

    if strategy.sensitivity_method == "morris":
        trajectories = _screening_trajectories(
            requested=strategy.sensitivity_trajectories,
            dimension=len(tunable_names),
            evaluation_budget=strategy.evaluation_budget,
        )
        if trajectories > 0:
            persisted_screening = load_screening_result(workspace)
            if persisted_screening is not None:
                active_names = _screening_active_names(persisted_screening, tunable_names)
                sensitivity_evidence = dict(persisted_screening)
                screening_model_evaluations = int(
                    sensitivity_evidence.get("model_evaluations") or 0
                )
                screening_score_calls = int(sensitivity_evidence.get("score_calls") or 0)
                screening_result_restored = True
            else:
                morris_checkpoint = load_morris_checkpoint(workspace)
                morris_resume = morris_checkpoint is not None
                screening = screen_morris(
                    bounds=bounds,
                    score_fn=evaluate,
                    trajectories=trajectories,
                    levels=strategy.sensitivity_levels,
                    random_seed=strategy.random_seed + 101,
                    min_relative_mu_star=strategy.sensitivity_min_relative_mu_star,
                    min_effects_per_parameter=strategy.sensitivity_min_effects,
                    min_active_parameters=strategy.min_active_parameters,
                    active_parameter_limit=strategy.active_parameter_limit,
                    resume_from=morris_checkpoint,
                    checkpoint_fn=lambda state: save_morris_checkpoint(workspace, state),
                )
                screening_model_evaluations = len(cache)
                screening_score_calls = screening.score_calls
                active_names = screening.active_parameters or tunable_names
                sensitivity_evidence = screening.as_dict()
                sensitivity_evidence.update(
                    {
                        "status": "completed",
                        "parameter_universe": list(tunable_names),
                        "model_evaluations": screening_model_evaluations,
                    }
                )
                save_screening_result(workspace, sensitivity_evidence)
        else:
            sensitivity_evidence["status"] = "skipped_budget_or_low_dimension"

    active_bounds = {name: bounds[name] for name in active_names}
    initial_active = {name: base_parameters[name] for name in active_names}
    optimizer_budget = strategy.evaluation_budget - screening_model_evaluations
    if optimizer_budget < 1:
        raise ValueError("sensitivity screening exhausted calibration evaluation budget")

    trace: list[dict[str, float | int]] = []
    selected_source = strategy.optimizer
    dds_resume = False

    if strategy.optimizer == "dds":
        dds_checkpoint = load_dds_checkpoint(workspace)
        dds_resume = dds_checkpoint is not None
        opt = optimize_dds(
            bounds=active_bounds,
            score_fn=evaluate,
            evaluation_budget=optimizer_budget,
            random_seed=strategy.random_seed,
            initial_parameters=initial_active,
            resume_from=dds_checkpoint,
            checkpoint_fn=lambda state: save_dds_checkpoint(workspace, state),
        )
        best_tunable = _canonical_tunable(opt.best_parameters, active_bounds)
        best_score = float(opt.best_score)
        trace = [
            {"evaluation": int(evaluation), "best_score": float(score)}
            for evaluation, score in opt.improvement_history
        ]
        optimizer_calls = int(opt.evaluations)
    elif strategy.optimizer == "sce-ua":
        opt = optimize_sceua(
            bounds=active_bounds,
            score_fn=evaluate,
            evaluation_budget=optimizer_budget,
            random_seed=strategy.random_seed,
            initial_parameters=initial_active,
        )
        best_tunable = _canonical_tunable(opt.best_parameters, active_bounds)
        best_score = float(opt.best_score)
        trace = [
            {"evaluation": int(evaluation), "best_score": float(score)}
            for evaluation, score in opt.improvement_history
        ]
        optimizer_calls = int(opt.evaluations)
    elif strategy.optimizer == "random-search":
        rng = np.random.default_rng(strategy.random_seed)
        candidates = [initial_active]
        while len(candidates) < optimizer_budget:
            candidates.append(_sample_vector(rng, active_names, active_bounds))
        best_tunable = dict(initial_active)
        best_score = float("-inf")
        optimizer_calls = 0
        for index, values in enumerate(candidates):
            raw = evaluate(values)
            optimizer_calls += 1
            score = float(raw) if raw is not None else float("-inf")
            if score > best_score:
                best_score = score
                best_tunable = _canonical_tunable(values, active_bounds)
                trace.append({"evaluation": index + 1, "best_score": score})
    else:
        raise ValueError(f"unsupported optimizer: {strategy.optimizer}")

    best_merged = dict(base_parameters)
    best_merged.update(best_tunable)
    best_key = tuple((name, float(best_merged[name])) for name in all_names)
    best_cached = cache.get(best_key)
    if best_cached is None:
        raw = evaluate(best_tunable)
        if raw is None:
            raise ValueError("best calibration candidate became unevaluable")
        best_cached = cache[best_key]
    cached_best_score, best_full, best_parameters = best_cached
    if cached_best_score is None:
        raise ValueError("best calibration candidate has non-finite objective")
    best_score = float(cached_best_score)

    baseline_tunable = _canonical_tunable(initial_tunable, bounds)
    baseline_merged = dict(base_parameters)
    baseline_merged.update(baseline_tunable)
    baseline_key = tuple((name, float(baseline_merged[name])) for name in all_names)
    baseline_cached = cache.get(baseline_key)
    if baseline_cached is None:
        raw = evaluate(baseline_tunable)
        if raw is None:
            raise ValueError("baseline XAJ scheme is not evaluable")
        baseline_cached = cache[baseline_key]
    _, baseline_full, _ = baseline_cached

    model_evaluations = len(cache)
    if model_evaluations > strategy.evaluation_budget:
        raise RuntimeError(
            f"calibration exceeded hard evaluation budget: {model_evaluations}>{strategy.evaluation_budget}"
        )

    absolute_bounds = {name: tuple(float(v) for v in ranges[name]) for name in active_names}
    boundary_evidence = analyze_search_boundaries(
        values=best_tunable,
        search_bounds=active_bounds,
        absolute_bounds=absolute_bounds,
    )

    delta = {
        key: float(best_parameters[key]) - float(base_parameters[key])
        for key in best_parameters
        if key in base_parameters
        and abs(float(best_parameters[key]) - float(base_parameters[key])) > 1e-12
    }
    calibrated = bool(delta)
    objective_metric = "kge" if objective == "composite" else objective
    screened_out = tuple(name for name in tunable_names if name not in set(active_names))
    resumed_from_workspace = bool(
        restored_model_evaluations or morris_resume or screening_result_restored or dds_resume
    )

    candidate_payload = {
        "model_id": "xaj",
        "warmup_days": scheme.warmup_days,
        "parameters": best_parameters,
        "routing": scheme.routing.model_dump(),
        "model_version": MODEL_VERSION,
        "base_scheme_id": request.scheme_id,
        "strategy_id": strategy.strategy_id,
        "optimizer": strategy.optimizer,
        "objective": objective,
        "objective_metric": objective_metric,
        "param_groups": list(groups),
        "parameter_universe": list(tunable_names),
        "active_parameters": list(active_names),
        "screened_out_parameters": list(screened_out),
        "sensitivity_method": strategy.sensitivity_method,
        "sensitivity_evidence": sensitivity_evidence,
        "evaluation_budget": strategy.evaluation_budget,
        "screening_model_evaluations": screening_model_evaluations,
        "optimizer_budget": optimizer_budget,
        "search_boundary_evidence": boundary_evidence.as_dict(),
        "resumed_from_workspace": resumed_from_workspace,
    }
    result = {
        "model_id": "xaj",
        "scheme_id": request.scheme_id,
        "data_snapshot_id": request.data_snapshot_id,
        "strategy_id": strategy.strategy_id,
        "optimizer": strategy.optimizer,
        "evaluation_budget": strategy.evaluation_budget,
        "optimizer_budget": optimizer_budget,
        "optimizer_calls": optimizer_calls,
        "screening_score_calls": screening_score_calls,
        "screening_model_evaluations": screening_model_evaluations,
        "model_evaluations": model_evaluations,
        "restored_model_evaluations": restored_model_evaluations,
        "resumed_from_workspace": resumed_from_workspace,
        "morris_resumed": morris_resume,
        "dds_resumed": dds_resume,
        # Backward-compatible aliases used by existing reports/tests.
        "evaluated_candidates": model_evaluations,
        "requested_candidates": strategy.evaluation_budget,
        "model_version": MODEL_VERSION,
        "model_source_sha256": MODEL_SHA256,
        "selected_candidate_index": 0 if not calibrated else -1,
        "selected_candidate_source": "baseline" if not calibrated else selected_source,
        "objective": objective,
        "objective_metric": objective_metric,
        "param_groups": list(groups),
        "parameter_universe": list(tunable_names),
        "active_parameters": list(active_names),
        "screened_out_parameters": list(screened_out),
        "sensitivity_method": strategy.sensitivity_method,
        "sensitivity_evidence": sensitivity_evidence,
        "objective_value": float(best_score),
        "candidate_parameters": best_parameters,
        "optimization_trace": trace,
        "search_bounds": {name: list(bound) for name, bound in active_bounds.items()},
        "screening_bounds": {name: list(bound) for name, bound in bounds.items()},
        "absolute_bounds": {name: list(bound) for name, bound in absolute_bounds.items()},
        "search_boundary_evidence": boundary_evidence.as_dict(),
        "calibrated": calibrated,
    }

    output_dir = workspace / "output"
    if len(baseline_full) == len(dates) and len(best_full) == len(dates):
        start = (
            dates[scheme.warmup_days].isoformat()
            if len(dates) > scheme.warmup_days
            else dates[0].isoformat()
        )
        comparison = build_comparison(
            kind="calibration",
            dates=list(dates),
            observed=streamflow,
            warmup_days=scheme.warmup_days,
            evaluated_window="calibration",
            baseline=baseline_full,
            candidate=best_full,
            gate_status=None,
            frozen_is_candidate=False,
            parameter_delta=delta,
            windows={
                "calibration": f"{start}..{dates[-1].isoformat()}",
                "warmup": (
                    f"{dates[0].isoformat()}.."
                    f"{dates[min(scheme.warmup_days, len(dates)) - 1].isoformat()}"
                ),
            },
        )
        artifacts = write_bundle(output_dir, comparison, stem="calibration-comparison")
        result["hydrograph_artifacts"] = artifacts
        result["baseline_metrics"] = comparison["baseline_metrics"]
        result["candidate_metrics"] = comparison["candidate_metrics"]

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
