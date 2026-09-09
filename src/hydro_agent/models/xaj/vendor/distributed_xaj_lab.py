#!/usr/bin/env python3
"""Build/replay a native, common-outlet, multi-unit XAJ academy case."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd

import xaj
from dem_xaj_lab import dump, sha256
from manual_xaj_lab import (_read_daily_csv, load_yaml, parameter_defaults,
                            prepare_daily_data, metrics)

ROOT = Path(__file__).resolve().parent


def netcdf_path(path):
    path = Path(path)
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def evaluation_metrics(observed, simulated):
    score = metrics(observed, simulated)
    score["mse_m6s2"] = float(np.mean((np.asarray(simulated) - np.asarray(observed)) ** 2))
    return score


def metric_label(score):
    def value(key):
        return "N/A" if score[key] is None else f"{score[key]:.4g}"
    return (f"NSE = {value('nse')}\nPBIAS = {value('pbias_percent')} %\n"
            f"MSE = {value('mse_m6s2')} (m³/s)²\nRMSE = {value('rmse_m3s')} m³/s")


def station_weights(labels, transform, crs, stations):
    """Raster approximation of Thiessen area weights, not centroid IDW."""
    from scipy.spatial import cKDTree
    from pyproj import Transformer
    ids = np.unique(labels[labels > 0])
    if len(ids) < 1 or not np.array_equal(ids, np.arange(1, len(ids)+1)):
        raise ValueError("Expected contiguous unit IDs starting at 1 (one or more)")
    ll = stations[["经度", "纬度"]].to_numpy(dtype=float)
    if not np.isfinite(ll).all() or (abs(ll[:,0]) > 180).any() or (abs(ll[:,1]) > 90).any():
        raise ValueError("Invalid station coordinates")
    projection = Transformer.from_crs(4326, crs, always_xy=True)
    sx, sy = projection.transform(ll[:,0], ll[:,1])
    rows, cols = np.nonzero(labels)
    xs = transform.c + (cols+.5)*transform.a + (rows+.5)*transform.b
    ys = transform.f + (cols+.5)*transform.d + (rows+.5)*transform.e
    nearest = cKDTree(np.column_stack([sx, sy])).query(np.column_stack([xs, ys]))[1]
    weights = np.zeros((len(ids), len(stations)))
    for uid in ids:
        mask = labels[rows, cols] == uid
        weights[uid-1] = np.bincount(nearest[mask], minlength=len(stations))/mask.sum()
    if not np.allclose(weights.sum(axis=1), 1):
        raise ValueError("Unit station weights must sum to one")
    return weights


def build(raw, case_dir, *, run=True):
    import rasterio
    raw, case = Path(raw).resolve(), Path(case_dir).resolve()
    config = json.loads((case / "dem_config.json").read_text(encoding="utf-8"))
    if not config["boundary_check"]["accepted"]:
        raise ValueError("DEM delineation has not passed numerical checks")
    inputs = case / "model_inputs"
    inputs.mkdir(exist_ok=False)
    for folder in ["parameters", "forcings", "source", "results", "config", "raw_data"]:
        (case / folder).mkdir(exist_ok=False)
    units = pd.read_csv(case / "gis" / "units.csv")
    stations = pd.read_excel(raw / "ST_STNM.xlsx")
    if stations["站名"].isna().any() or stations["站名"].duplicated().any():
        raise ValueError("Rain gauge names must be unique and nonempty")
    names = stations["站名"].astype(str).tolist()
    with rasterio.open(case / "gis" / "units.tif") as src:
        labels = src.read(1)
        areas = np.bincount(labels.ravel())[1:] * abs(src.transform.determinant) / 1e6
        weights = station_weights(labels, src.transform, src.crs, stations)
    if not np.array_equal(units.unit_id, np.arange(1, len(areas)+1)) or not np.allclose(areas, units.area_km2):
        raise ValueError("Unit raster/table area or order mismatch")
    if not np.isclose(areas.sum(), config["boundary_check"]["dem_area_km2"]):
        raise ValueError("Disjoint unit areas do not cover the DEM catchment")
    daily_paths = sorted((raw / "日数据").glob("*.csv"))
    frame = pd.concat([_read_daily_csv(path) for path in daily_paths], ignore_index=True)
    frame["time"] = pd.to_datetime(frame["时间"].astype(str).str.strip().str.strip("#"))
    frame = frame.sort_values("time").reset_index(drop=True)
    observed, original_weights = prepare_daily_data(raw)
    if not frame.time.equals(observed.time):
        raise ValueError("Station and observed timestamps disagree")
    gauge_rain = frame[names].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    if not np.isfinite(gauge_rain).all() or (gauge_rain < 0).any():
        raise ValueError("Gauge rain must be finite and nonnegative; no automatic filling")
    rain = gauge_rain @ weights.T
    ep = np.repeat(observed.evaporation.to_numpy()[:, None], len(units), axis=1)
    ids = [f"unit_{uid}" for uid in units.unit_id]
    for name, array in [("precipitation_mm", rain), ("evaporation_mm", ep)]:
        table = pd.DataFrame(array, columns=ids)
        table.insert(0, "time", observed.time)
        table.to_csv(inputs / f"{name}.csv", index=False)
    observed.to_csv(inputs / "observed.csv", index=False)
    pd.DataFrame(weights, columns=names, index=pd.Index(units.unit_id, name="unit_id")).to_csv(inputs / "station_weights.csv")
    stations.to_csv(inputs / "stations.csv", index=False)
    shutil.copy2(case / "gis" / "units.csv", inputs / "units.csv")
    # Archive only explicitly scoped modelling sources, never .env or arbitrary files.
    shutil.copy2(raw / "ST_STNM.xlsx", case / "raw_data" / "ST_STNM.xlsx")
    for path in daily_paths:
        (case / "raw_data" / "日数据").mkdir(exist_ok=True)
        shutil.copy2(path, case / "raw_data" / "日数据" / path.name)
    shutil.copytree(raw / "GIS图层", case / "raw_data" / "GIS图层")
    defaults = parameter_defaults(load_yaml(ROOT / "parameter_bounds.yaml"))
    parameters = []
    for uid, area in zip(units.unit_id, areas):
        values = {key.lower(): value for key, value in defaults.items()}
        # Shared, uncalibrated academy parameters: no invented DEM->soil relation.
        values.update(rivid=int(uid), area=float(area), dp=1, ke=24., xe=.2, lag=0)
        xaj.make_parameter(values, xaj.DAY, int(uid)-1)
        parameters.append(values)
    pd.DataFrame(parameters, columns=xaj.PARAMETERS).to_csv(case / "parameters" / "parameters.csv", index=False)
    shutil.copy2(ROOT / "parameter_bounds.yaml", case / "config" / "parameter_bounds.yaml")
    start = observed.time.iloc[0]
    lines = ["&xaj_namelist", f"nzone={len(units)}, nstep={len(observed)}, dt=86400,",
        f"start_year={start.year}, start_month={start.month}, start_day={start.day}, start_hour={start.hour},",
        f"start_minute={start.minute}, start_second={start.second},",
        "fnm_parameters='parameters/parameters.csv', fnm_output='results/native_output.nc',",
        "fnm_restart_out='results/restart.nc',", "/"]
    (case / "xaj.namelist").write_text("\n".join(lines)+"\n", encoding="utf-8")
    for name, data in [("prec", rain), ("ep", ep)]:
        np.savetxt(case / "forcings" / f"{name}.txt", np.column_stack([np.arange(1, len(data)+1), data]),
                   header="step " + " ".join(ids), comments="", fmt="%.12g")
    for name in ["xaj.py", "distributed_xaj_lab.py", "manual_xaj_lab.py", "dem_xaj_lab.py"]:
        shutil.copy2(ROOT / name, case / "source" / name)
    dump(case / "config" / "model_assumptions.json", dict(agent_used=False, api_used=False,
        model_mode=config.get("model_mode", "distributed"),
        model="academy/xaj.py (native multi-unit Model, unmodified)", nzone=len(units), dt_seconds=86400,
        units_order=ids, period=[str(observed.time.iloc[0]), str(observed.time.iloc[-1])], nstep=len(observed),
        precipitation="Cell-wise nearest station / Thiessen area weights using ST_STNM.xlsx coordinates; mm/day",
        original_basin_weights=original_weights, evaporation="Same measured basin evaporation depth for all units; mm/day",
        observed_discharge="Outlet only; no invented per-unit flow observations; m3/s",
        parameters="Shared uncalibrated defaults. DEM determines partition and area, NOT WM/SM/KC etc.",
        routing="Independent unit-to-common-outlet Muskingum: DP=1 KE=24h XE=0.2 LAG=0. No network cascade or extra area weighting of outlet flows.",
        warmup_days=365, area_used_km2=float(areas.sum()), boundary_review_required=True,
        station_coordinate_warning="Some GIS geometries differ from station table coordinates; inspect boundary_check.json and units_map.png.",
        scope="Retrospective daily academy simulation, NOT calibrated operational flood forecast"))
    # Input manifest remains valid when learners replay native outputs.
    manifest = {str(p.relative_to(case)): sha256(p) for folder in ["source", "source_dem", "raw_data", "model_inputs", "parameters", "config", "forcings", "gis"]
                for p in sorted((case / folder).rglob("*")) if p.is_file()}
    manifest.update({name: sha256(case / name) for name in ["xaj.namelist", "dem_config.json"]})
    dump(case / "input_manifest.sha256.json", manifest)
    if run:
        run_case(case)
    print(f"Native XAJ case built ({len(units)} unit(s)): {case}")


def run_case(case, *, export_only=False):
    """Use exactly the exported namelist, parameters and forcing files."""
    case = Path(case).resolve()
    config = xaj.read_namelist(case / "xaj.namelist")
    params = xaj.read_parameters(case / config.fnm_parameters, config.nzone, config.dt)
    assumptions = json.loads((case / "config" / "model_assumptions.json").read_text(encoding="utf-8"))
    observed = pd.read_csv(case / "model_inputs" / "observed.csv", parse_dates=["time"])
    if len(observed) != config.nstep or config.dt != xaj.DAY:
        raise ValueError("This academy replay requires matching daily observations")
    if not export_only:
        xaj.run(case)
    from netCDF4 import Dataset, chartostring
    with Dataset(netcdf_path(case / config.fnm_output)) as dataset:
        total = np.asarray(dataset["sum_qsig"][:], dtype=float)
        times = pd.to_datetime(chartostring(dataset["time"][:]), format="%Y%m%d%H%M%S")
        if len(total) != config.nstep or not np.array_equal(times.to_numpy(), observed.time.to_numpy()):
            raise ValueError("Native output dates/length do not match the current daily inputs")
        routed = np.column_stack([
            sum(np.asarray(dataset[name][:, index, p.dp], dtype=float) for name in ("qxs", "qxi", "qxg"))
            for index, p in enumerate(params)])
    with Dataset(netcdf_path(case / "m3_riv.nc")) as dataset:
        pre_musk_volume = np.asarray(dataset["m3_riv"][:], dtype=float)
    if routed.shape != (config.nstep, config.nzone) or pre_musk_volume.shape != routed.shape:
        raise ValueError("Native output unit dimensions do not match the current configuration")
    if not np.isfinite(routed).all() or not np.isfinite(pre_musk_volume).all():
        raise ValueError("Native unit outputs contain non-finite values")
    if not np.isfinite(total).all() or (total < 0).any():
        raise ValueError("Invalid simulated outlet flow")
    # Native summation is float32 by flow component, not float64 by unit.
    np.testing.assert_allclose(routed.sum(axis=1), total, rtol=2e-6, atol=1e-5)
    results = case / "results"
    results.mkdir(exist_ok=True)
    for name, array in [("unit_outlet_m3s", routed), ("unit_before_muskingum_m3_per_step", pre_musk_volume)]:
        table = pd.DataFrame(array, columns=[f"unit_{p.rivid}" for p in params])
        table.insert(0, "time", observed.time)
        table.to_csv(results / f"{name}.csv", index=False)
    table = pd.DataFrame(dict(time=observed.time, observed_m3s=observed.discharge, simulated_m3s=total))
    table.to_csv(results / "outlet_simulation.csv", index=False)
    warmup = int(assumptions["warmup_days"])
    score = evaluation_metrics(observed.discharge.to_numpy()[warmup:], total[warmup:])
    dump(results / "metrics.json", dict(after_warmup=score, warmup_days=warmup, calibrated=False,
        unit_sum_max_abs_error_m3s=float(np.max(abs(routed.sum(axis=1)-total))),
        warning="Academy defaults only; scores are not forecast skill or independent calibration/validation."))
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(observed.time, observed.discharge, linewidth=.6, label="Observed outlet")
    mode = "lumped" if config.nzone == 1 else "multi-unit"
    ax.plot(observed.time, total, linewidth=.6, label=f"Uncalibrated {mode} XAJ")
    ax.set(xlabel="Time", ylabel="Discharge (m³/s)", title="Yaogu: daily historical academy simulation")
    ax.legend()
    fig.text(.78, .78, f"After {warmup} warmup days\nN = {score['count']} days\n\n" + metric_label(score),
             va="top", fontsize=10, bbox=dict(facecolor="white", edgecolor="gray", alpha=.9))
    fig.tight_layout(rect=(0, 0, .77, 1))
    fig.savefig(results / "outlet_hydrograph.png", dpi=140)
    plt.close(fig)
    (case / "REPORT.md").write_text(
        f"# 腰古 DEM {'集总式' if config.nzone == 1 else '多单元'} XAJ 教学算例\n\n"
        f"- 计算单元：{config.nzone}；日步长；{config.nstep} 时段。\n"
        f"- DEM 面积：{assumptions['area_used_km2']:.3f} km²。单元是不重叠的增量区域。\n"
        f"- 参数尚未率定；跳过 {warmup} 天后的评价：`{json.dumps(score, ensure_ascii=False)}`。\n"
        "- 这是历史模拟，不是业务预报；DEM 出口、边界和站点坐标仍需人工确认。\n\n"
        "## 人工检查顺序\n\n"
        "1. `gis/units_map.png`、`gis/boundary_check.json`：出口位置、DEM 与原边界差异。\n"
        "2. `gis/units.csv` 和 `units.tif`：单元面积、空间覆盖、小单元。\n"
        "3. `model_inputs/station_weights.csv`、雨量/蒸发 CSV：每行权重和为 1，列顺序一致。\n"
        "4. `parameters/parameters.csv`、`xaj.namelist`、`config/model_assumptions.json`：单位与参数假设。\n"
        "5. `results/`：单元独立汇流后相加得到总出口，不能再次乘面积权重。\n\n"
        "## 不依赖 Agent 的原生重跑\n\n"
        "在本 case 目录执行（需要 numpy、netCDF4）：\n\n"
        "```bash\npython source/xaj.py --case-dir .\n```\n\n"
        "输出 `results/native_output.nc`、`results/restart.nc`、`m3_riv.nc`；重复运行覆盖这些计算结果，不改输入。\n"
        "`m3_riv.nc` 是 Muskingum 前的单元体积（m³/时段），不是出口流量（m³/s）。\n"
        "`native_output.nc` 的 `sum_qsig` 才是汇流后的总出口流量。\n"
        "Python CSV/图片重新生成：`python source/distributed_xaj_lab.py --case-dir .`。\n"
        "修改输入后原始 `input_manifest.sha256.json` 会提示哈希变化；它只记录初次构建版本。\n",
        encoding="utf-8")
    nse_label = 'undefined (constant observations)' if score['nse'] is None else f"{score['nse']:.4f}"
    print(f"Exported {config.nstep} days, {config.nzone} units from NetCDF; uncalibrated NSE={nse_label}")
    return table


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--export-only", action="store_true", help="Read existing native NetCDF outputs without running XAJ")
    args = parser.parse_args()
    run_case(args.case_dir, export_only=args.export_only)
