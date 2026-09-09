#!/usr/bin/env python3
"""Agent-free XAJ academy workflow using academy/xaj.py directly.

The script intentionally keeps every modelling decision visible: learners read
station weights, standardize daily forcing, choose parameters, call Model.step,
perform a small deterministic random-search calibration, and save a reviewable
case.  It never imports Qwen-Agent and never reads .env.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "work" / ".matplotlib"))
(ROOT / "work" / ".matplotlib").mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

import xaj


DEFAULT_RAW = ROOT / "examples" / "data"
DEFAULT_BOUNDS = ROOT / "parameter_bounds.yaml"


def load_yaml(path: str | Path) -> dict[str, Any]:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML/JSON object")
    return value


def save_yaml(value: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return target


def _read_daily_csv(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", b"", 0, 1, f"cannot decode {path}")


def prepare_daily_data(raw_dir: str | Path) -> tuple[pd.DataFrame, dict[str, float]]:
    """Manually create the canonical time/P/E/Q table from the formal daily files."""
    raw = Path(raw_dir).resolve()
    station_path = raw / "ST_STNM.xlsx"
    daily_paths = sorted((raw / "日数据").glob("*.csv"))
    if not station_path.is_file():
        raise FileNotFoundError(f"station metadata not found: {station_path}")
    if not daily_paths:
        raise FileNotFoundError(f"no daily CSV files found under: {raw / '日数据'}")

    stations = pd.read_excel(station_path)
    required_station_columns = {"站名", "权重"}
    if not required_station_columns.issubset(stations.columns):
        raise ValueError(f"ST_STNM.xlsx requires columns {sorted(required_station_columns)}")
    weights = {
        str(row["站名"]): float(row["权重"])
        for _, row in stations[["站名", "权重"]].dropna().iterrows()
    }
    if not weights or any(value < 0 for value in weights.values()):
        raise ValueError("station weights must be present and nonnegative")
    if abs(sum(weights.values()) - 1.0) > 1e-6:
        raise ValueError(f"station weights must sum to 1.0, got {sum(weights.values()):g}")

    standardized: list[pd.DataFrame] = []
    for path in daily_paths:
        frame = _read_daily_csv(path)
        required = {"时间", "蒸发", "流量", *weights}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
        time_text = frame["时间"].astype(str).str.strip().str.strip("#")
        result = pd.DataFrame({"time": pd.to_datetime(time_text, errors="coerce")})
        rain_columns = frame[list(weights)].apply(pd.to_numeric, errors="coerce")
        result["precipitation"] = rain_columns.mul(pd.Series(weights)).sum(
            axis=1, min_count=len(weights)
        )
        result["evaporation"] = pd.to_numeric(frame["蒸发"], errors="coerce")
        result["discharge"] = pd.to_numeric(frame["流量"], errors="coerce")
        if result.isna().any().any():
            counts = {key: int(value) for key, value in result.isna().sum().items() if value}
            raise ValueError(f"{path.name} contains invalid or missing values: {counts}")
        if (result[["precipitation", "evaporation", "discharge"]] < 0).any().any():
            raise ValueError(f"{path.name} contains negative hydrological values")
        standardized.append(result)

    observed = (
        pd.concat(standardized, ignore_index=True)
        .sort_values("time")
        .reset_index(drop=True)
    )
    if observed["time"].duplicated().any():
        raise ValueError("daily data contains duplicate timestamps")
    differences = observed["time"].diff().dropna().dt.total_seconds() / 3600.0
    if len(differences) and not np.allclose(differences.to_numpy(), 24.0):
        bad = int(np.count_nonzero(~np.isclose(differences.to_numpy(), 24.0)))
        raise ValueError(f"daily data is not continuous at 24 h; {bad} gaps found")
    return observed, weights


def _shapefile_record_count(path: Path) -> int | None:
    """Count SHP records from the public binary layout, without a GIS package."""
    if not path.is_file():
        return None
    data = path.read_bytes()
    if len(data) < 100 or struct.unpack(">i", data[:4])[0] != 9994:
        raise ValueError(f"invalid shapefile header: {path}")
    count = 0
    offset = 100
    while offset + 8 <= len(data):
        content_words = struct.unpack(">i", data[offset + 4 : offset + 8])[0]
        record_size = 8 + content_words * 2
        if content_words < 2 or offset + record_size > len(data):
            raise ValueError(f"invalid shapefile record: {path}")
        count += 1
        offset += record_size
    return count


def analyze_computational_units(
    raw_dir: str | Path, area_km2: float, station_weights: dict[str, float]
) -> dict[str, Any]:
    """Explain whether the available evidence supports lumped or multi-unit XAJ."""
    raw = Path(raw_dir).resolve()
    gis = raw / "GIS图层"
    polygon_count = _shapefile_record_count(gis / "分区.shp")
    river_reach_count = _shapefile_record_count(gis / "流域河网.shp")
    station_point_count = _shapefile_record_count(gis / "流域站网.shp")
    station_table = pd.read_excel(raw / "ST_STNM.xlsx")
    station_types = station_table.get("站类", pd.Series(dtype=str)).astype(str).str.upper()
    outlet_flow_count = int(station_types.str.contains("ZQ", regex=False).sum())

    # This runner is deliberately the lumped baseline, not a general verdict on
    # whether the basin can be partitioned. A single gauge does NOT prohibit
    # native multi-unit common-outlet routing with constrained/shared parameters.
    decision = "single_lumped_unit"
    recommended_count = 1
    reasons = [
        f"分区图层包含{polygon_count if polygon_count is not None else '未知'}个面要素。",
        f"当前有{len(station_weights)}个雨量站，但只有1套全流域站点权重。",
        f"站表中识别到{outlet_flow_count}个ZQ流量控制站，不足以独立率定多个内部单元。",
        f"流域面积约{area_km2:g} km²，应关注空间异质性，但面积大并不能单独证明必须划分。",
        "本次目标是用连续日资料完成教学率定，采用单一集总单元更便于识别参数和解释结果。",
        "单一出口不是多单元计算的禁用条件；DEM划分和单元权重构建见分布式教学教程。",
    ]
    return {
        "decision": decision,
        "recommended_unit_count": recommended_count,
        "scope": "single-unit baseline runner, not a basin-wide partitioning prohibition",
        "confidence": "baseline_choice",
        "evidence": {
            "basin_area_km2": float(area_km2),
            "partition_polygon_records": polygon_count,
            "river_reach_records": river_reach_count,
            "station_point_records": station_point_count,
            "rain_gauge_count": len(station_weights),
            "outlet_flow_station_count": outlet_flow_count,
            "unit_specific_rainfall_weight_matrices": 0,
        },
        "reasons": reasons,
        "model_capability": {
            "xaj_supports_multiple_units": True,
            "interface": "xaj.Model(params=[...]); Model.step(rain=[...], evaporation=[...])",
            "current_tutorial_implementation": "one parameter set and one basin-average P/E series",
        },
        "reconsider_multiple_units_when": [
            "DEM分水岭产生了有明确汇流关系的多个子流域边界",
            "可以为每个单元构建独立的面雨量和蒸发输入",
            "单元不重叠且面积闭合，并明确采用独立汇至共同出口还是河网串联路由",
            "有内部流量站、参数区域化依据或其他约束，能降低多单元参数异参同效",
            "短历时强降雨的空间分布对次洪预报影响显著",
        ],
        "academy_conclusion": (
            "本次采用1个集总XAJ计算单元；多单元应作为后续课程，"
            "分布式课程已提供dem_xaj_lab.py，在单元边界、单元降雨、出口汇流和参数约束齐备后实施。"
        ),
    }


def parameter_defaults(bounds: dict[str, Any]) -> dict[str, float]:
    return {
        str(name).upper(): float(specification["default"])
        for name, specification in (bounds.get("parameters") or {}).items()
    }


def native_parameter(values: dict[str, float], area_km2: float):
    """Map readable academy parameters to xaj.py's original lowercase fields."""
    native_values: dict[str, Any] = {
        "rivid": 1,
        "area": float(area_km2),
        "dp": int(round(values.get("DP", 0))),
        "ke": float(values.get("KE", 1.0)),
        "xe": float(values.get("XE", 0.20)),
    }
    for name in ("KC B C IMP WM WUM WLM SM EX KG KI CG CI CS LAG").split():
        value: Any = values[name]
        native_values[name.lower()] = int(round(value)) if name == "LAG" else float(value)
    return xaj.make_parameter(native_values, xaj.DAY)


def simulate(
    observed: pd.DataFrame, parameters: dict[str, float], area_km2: float
) -> np.ndarray:
    """Call the native stateful Model.step API once per daily forcing row."""
    model = xaj.Model([native_parameter(parameters, area_km2)], xaj.DAY)
    simulated = np.empty(len(observed), dtype=float)
    for index, row in enumerate(observed.itertuples(index=False)):
        result = model.step([float(row.precipitation)], [float(row.evaporation)])
        simulated[index] = float(result.sum_qsig)
    return simulated


def metrics(observed: np.ndarray, simulated: np.ndarray) -> dict[str, float | int | None]:
    obs = np.asarray(observed, dtype=float)
    sim = np.asarray(simulated, dtype=float)
    if len(obs) < 3 or len(obs) != len(sim):
        raise ValueError("metrics require at least three paired values")
    denominator = float(np.sum((obs - obs.mean()) ** 2))
    nse = float(1.0 - np.sum((obs - sim) ** 2) / denominator) if denominator else None
    pbias = float(100.0 * np.sum(sim - obs) / np.sum(obs)) if np.sum(obs) else None
    return {
        "count": int(len(obs)),
        "nse": nse,
        "rmse_m3s": float(np.sqrt(np.mean((sim - obs) ** 2))),
        "pbias_percent": pbias,
        "observed_peak_m3s": float(np.max(obs)),
        "simulated_peak_m3s": float(np.max(sim)),
    }


def calibrate_random_search(
    training: pd.DataFrame,
    bounds: dict[str, Any],
    area_km2: float,
    candidates: int,
    warmup_steps: int,
    seed: int,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Small transparent calibration for academy, not a production optimizer."""
    specifications = bounds.get("parameters") or {}
    names = [name.upper() for name, spec in specifications.items() if spec.get("calibrate")]
    defaults = parameter_defaults(bounds)
    rng = np.random.RandomState(seed)
    candidate_values = [defaults]
    for _ in range(max(0, int(candidates) - 1)):
        trial = dict(defaults)
        for name in names:
            spec = specifications[name]
            trial[name] = float(rng.uniform(float(spec["min"]), float(spec["max"])))
        candidate_values.append(trial)

    start = min(max(int(warmup_steps), 0), max(len(training) - 3, 0))
    best_parameters: dict[str, float] | None = None
    best_objective = float("inf")
    valid_evaluations = 0
    observed_q = training["discharge"].to_numpy(dtype=float)[start:]
    for index, trial in enumerate(candidate_values, start=1):
        try:
            simulated_q = simulate(training, trial, area_km2)[start:]
            score_metrics = metrics(observed_q, simulated_q)
            nse = score_metrics["nse"]
            if nse is None or not np.isfinite(nse):
                continue
            objective = 1.0 - float(nse) + abs(float(score_metrics["pbias_percent"] or 0)) / 500.0
        except (ValueError, FloatingPointError):
            continue
        valid_evaluations += 1
        if objective < best_objective:
            best_objective = objective
            best_parameters = trial
            print(f"candidate {index:03d}: best objective={objective:.6f}, NSE={nse:.6f}")
    if best_parameters is None:
        raise RuntimeError("no valid parameter candidate; inspect bounds and input data")
    return best_parameters, {
        "method": "deterministic-random-search",
        "requested_candidates": int(candidates),
        "valid_evaluations": valid_evaluations,
        "calibrated_parameters": names,
        "warmup_steps": start,
        "seed": int(seed),
        "objective": best_objective,
    }


def _new_case_path() -> Path:
    return ROOT / "case" / f"manual-python-{datetime.now():%Y%m%d-%H%M%S}"


def run_manual_case(args: argparse.Namespace) -> Path:
    raw_dir = Path(args.raw).resolve()
    case_dir = Path(args.case_dir).resolve() if args.case_dir else _new_case_path()
    if case_dir.exists() and any(case_dir.iterdir()):
        raise FileExistsError(f"case directory is not empty: {case_dir}")
    for relative in ("model_inputs", "parameters", "config", "results"):
        (case_dir / relative).mkdir(parents=True, exist_ok=True)

    observed, weights = prepare_daily_data(raw_dir)
    unit_analysis = analyze_computational_units(raw_dir, args.area_km2, weights)
    bounds = load_yaml(args.parameter_bounds)
    defaults = parameter_defaults(bounds)
    split_index = min(max(int(len(observed) * args.training_ratio), 3), len(observed) - 3)
    training = observed.iloc[:split_index].reset_index(drop=True)
    calibrated, calibration_report = calibrate_random_search(
        training,
        bounds,
        args.area_km2,
        args.candidates,
        args.warmup_steps,
        args.seed,
    )
    simulated = simulate(observed, calibrated, args.area_km2)
    result = observed.copy()
    result["simulated_discharge"] = simulated
    calibration_metrics = metrics(
        result["discharge"].to_numpy()[args.warmup_steps:split_index],
        simulated[args.warmup_steps:split_index],
    )
    validation_metrics = metrics(
        result["discharge"].to_numpy()[split_index:], simulated[split_index:]
    )

    observed.to_csv(case_dir / "model_inputs" / "observed.csv", index=False, encoding="utf-8-sig")
    result.to_csv(case_dir / "results" / "simulation.csv", index=False, encoding="utf-8-sig")
    save_yaml({"station_weights": weights}, case_dir / "model_inputs" / "station_weights.yaml")
    save_yaml(unit_analysis, case_dir / "config" / "computational_unit_analysis.yaml")
    save_yaml(bounds, case_dir / "parameters" / "parameter_bounds.yaml")
    save_yaml({"values": defaults}, case_dir / "parameters" / "initial_parameters.yaml")
    save_yaml({"values": calibrated}, case_dir / "parameters" / "calibrated_parameters.yaml")
    save_yaml(calibration_report, case_dir / "results" / "calibration_report.yaml")
    save_yaml(
        {"calibration": calibration_metrics, "validation": validation_metrics},
        case_dir / "results" / "metrics.yaml",
    )
    shutil.copy2(ROOT / "xaj.py", case_dir / "config" / "xaj.py")
    shutil.copy2(args.parameter_bounds, case_dir / "config" / "parameter_bounds.yaml")
    model_hash = hashlib.sha256((ROOT / "xaj.py").read_bytes()).hexdigest()
    save_yaml(
        {
            "workflow": "manual-python-no-agent",
            "raw_dir": str(raw_dir),
            "area_km2": float(args.area_km2),
            "time_step_hours": 24,
            "computational_units": unit_analysis["recommended_unit_count"],
            "computational_unit_decision": unit_analysis["decision"],
            "training_ratio": float(args.training_ratio),
            "split_index": split_index,
            "xaj_source": "config/xaj.py",
            "xaj_source_sha256": model_hash,
            "api_used": False,
            "agent_used": False,
        },
        case_dir / "manual_config.yaml",
    )

    figure, axis = plt.subplots(figsize=(12, 5))
    axis.plot(result["time"], result["discharge"], label="Observed", linewidth=1)
    axis.plot(result["time"], result["simulated_discharge"], label="Simulated", linewidth=1)
    axis.axvline(result["time"].iloc[split_index], color="black", linestyle="--", label="Validation start")
    axis.set_ylabel("Discharge (m3/s)")
    axis.set_title("Manual Python XAJ simulation")
    axis.legend()
    figure.tight_layout()
    figure.savefig(case_dir / "results" / "hydrograph.png", dpi=150)
    plt.close(figure)

    report = f"""# Manual Python XAJ case

- Agent/API used: no
- Raw data: `{raw_dir}`
- Period: {observed['time'].iloc[0]} to {observed['time'].iloc[-1]}
- Rows: {len(observed)}
- Area: {args.area_km2:g} km2
- Time step: 24 h
- Computational units: {unit_analysis['recommended_unit_count']} ({unit_analysis['decision']})
- Unit-analysis conclusion: {unit_analysis['academy_conclusion']}
- Calibration rows: {split_index}
- Validation rows: {len(observed) - split_index}
- Calibration NSE: {calibration_metrics['nse']}
- Validation NSE: {validation_metrics['nse']}

Review `model_inputs/`, `parameters/`, `manual_config.yaml`, and `results/` before interpreting the simulation.
"""
    (case_dir / "REPORT.md").write_text(report, encoding="utf-8")
    print(f"manual XAJ case created: {case_dir}")
    return case_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default=str(DEFAULT_RAW), help="raw data directory")
    parser.add_argument("--case-dir", help="new/empty output case directory")
    parser.add_argument("--parameter-bounds", default=str(DEFAULT_BOUNDS))
    parser.add_argument("--area-km2", type=float, default=1712.261)
    parser.add_argument("--training-ratio", type=float, default=0.7)
    parser.add_argument("--warmup-steps", type=int, default=30)
    parser.add_argument("--candidates", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not 0.5 <= args.training_ratio <= 0.9:
        parser.error("--training-ratio must be between 0.5 and 0.9")
    if args.area_km2 <= 0 or args.candidates < 1 or args.warmup_steps < 0:
        parser.error("area/candidates must be positive and warmup must be nonnegative")
    run_manual_case(args)


if __name__ == "__main__":
    main()
