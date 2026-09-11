"""Observed-vs-scheme hydrograph comparison. Titles never imply calibration unless Gate ACCEPT."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from hydro_agent.evaluation.metrics import kge, mae, nse, pbias_percent, rmse

WindowName = Literal["warmup", "calibration", "validation", "test"]
ComparisonKind = Literal["calibration", "independent_test"]

CSV_FIELDS = (
    "time",
    "observed_m3s",
    "baseline_m3s",
    "candidate_m3s",
    "frozen_m3s",
    "change_m3s",
    "window",
    "is_warmup",
)


def _safe(fn, obs: list[float], sim: list[float]) -> float | None:
    try:
        return float(fn(obs, sim))
    except (TypeError, ValueError):
        return None


def score_series(
    obs: list[float], sim: list[float], *, warmup_days: int, evaluated_days: int
) -> dict[str, Any]:
    return {
        "nse": _safe(nse, obs, sim),
        "kge": _safe(kge, obs, sim),
        "pbias_percent": _safe(pbias_percent, obs, sim),
        "rmse_m3s": _safe(rmse, obs, sim),
        "mae": _safe(mae, obs, sim),
        "count": len(obs),
        "warmup_days": warmup_days,
        "evaluated_days": evaluated_days,
    }


def _delta(after: float | None, before: float | None) -> float | None:
    if after is None or before is None:
        return None
    return float(after - before)


def title_for(kind: ComparisonKind, *, calibrated: bool, gate_status: str | None) -> str:
    if kind == "calibration":
        return "观测与基线 / 候选 · 率定窗口"
    if calibrated:
        return "观测与冻结方案 · 独立检验"
    if gate_status == "KEEP":
        return "观测与冻结方案 · 独立检验（维持原方案）"
    if gate_status == "ROLLBACK":
        return "观测与冻结方案 · 独立检验（已回退）"
    return "观测与冻结方案 · 独立检验"


def calibrated_flag(*, gate_status: str | None, frozen_is_candidate: bool) -> bool:
    return gate_status == "ACCEPT" and frozen_is_candidate


def build_comparison(
    *,
    kind: ComparisonKind,
    dates: list[date],
    observed: dict[date, float],
    warmup_days: int,
    evaluated_window: WindowName,
    baseline: list[float] | None = None,
    candidate: list[float] | None = None,
    frozen: list[float] | None = None,
    gate_status: str | None = None,
    frozen_is_candidate: bool = False,
    parameter_delta: dict[str, float] | None = None,
    windows: dict[str, str] | None = None,
) -> dict[str, Any]:
    n = len(dates)
    for series in (baseline, candidate, frozen):
        if series is not None and len(series) != n:
            raise ValueError("hydrograph series length must match dates")
    calibrated = calibrated_flag(gate_status=gate_status, frozen_is_candidate=frozen_is_candidate)
    points: list[dict[str, Any]] = []
    eval_obs: list[float] = []
    eval_baseline: list[float] = []
    eval_candidate: list[float] = []
    eval_frozen: list[float] = []
    for index, day in enumerate(dates):
        is_warmup = index < warmup_days
        window: WindowName = "warmup" if is_warmup else evaluated_window
        obs = observed.get(day)
        base = None if baseline is None else float(baseline[index])
        cand = None if candidate is None else float(candidate[index])
        froze = None if frozen is None else float(frozen[index])
        change = None
        if base is not None and cand is not None:
            change = float(cand - base)
        elif base is not None and froze is not None:
            change = float(froze - base)
        point = {
            "time": day.isoformat(),
            "observed_m3s": None if obs is None else float(obs),
            "baseline_m3s": base,
            "candidate_m3s": cand,
            "frozen_m3s": froze,
            "change_m3s": change,
            "window": window,
            "is_warmup": is_warmup,
        }
        points.append(point)
        if is_warmup or obs is None:
            continue
        eval_obs.append(float(obs))
        if base is not None:
            eval_baseline.append(base)
        if cand is not None:
            eval_candidate.append(cand)
        if froze is not None:
            eval_frozen.append(froze)
    evaluated_days = len(eval_obs)
    baseline_metrics = (
        score_series(
            eval_obs, eval_baseline, warmup_days=warmup_days, evaluated_days=evaluated_days
        )
        if eval_baseline and len(eval_baseline) == len(eval_obs)
        else None
    )
    candidate_metrics = (
        score_series(
            eval_obs, eval_candidate, warmup_days=warmup_days, evaluated_days=evaluated_days
        )
        if eval_candidate and len(eval_candidate) == len(eval_obs)
        else None
    )
    frozen_metrics = (
        score_series(eval_obs, eval_frozen, warmup_days=warmup_days, evaluated_days=evaluated_days)
        if eval_frozen and len(eval_frozen) == len(eval_obs)
        else None
    )
    change = None
    if kind == "calibration" and baseline_metrics and candidate_metrics:
        change = {
            "nse": _delta(candidate_metrics["nse"], baseline_metrics["nse"]),
            "kge": _delta(candidate_metrics["kge"], baseline_metrics["kge"]),
            "pbias_percent": _delta(
                candidate_metrics["pbias_percent"], baseline_metrics["pbias_percent"]
            ),
            "rmse_m3s": _delta(candidate_metrics["rmse_m3s"], baseline_metrics["rmse_m3s"]),
        }
    return {
        "kind": kind,
        "title": title_for(kind, calibrated=calibrated, gate_status=gate_status),
        "calibrated": calibrated,
        "gate_status": gate_status,
        "warmup_days": warmup_days,
        "evaluated_days": evaluated_days,
        "series": points,
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
        "frozen_metrics": frozen_metrics,
        "change": change,
        "parameter_delta": dict(parameter_delta or {}),
        "windows": dict(windows or {}),
    }


def write_comparison_csv(path: Path, comparison: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in comparison["series"]:
            writer.writerow(
                {
                    "time": row["time"],
                    "observed_m3s": "" if row["observed_m3s"] is None else row["observed_m3s"],
                    "baseline_m3s": "" if row["baseline_m3s"] is None else row["baseline_m3s"],
                    "candidate_m3s": "" if row["candidate_m3s"] is None else row["candidate_m3s"],
                    "frozen_m3s": "" if row["frozen_m3s"] is None else row["frozen_m3s"],
                    "change_m3s": "" if row["change_m3s"] is None else row["change_m3s"],
                    "window": row["window"],
                    "is_warmup": "true" if row["is_warmup"] else "false",
                }
            )


def write_metrics_json(path: Path, comparison: dict[str, Any]) -> None:
    payload = {
        "kind": comparison["kind"],
        "title": comparison["title"],
        "calibrated": comparison["calibrated"],
        "gate_status": comparison.get("gate_status"),
        "warmup_days": comparison["warmup_days"],
        "evaluated_days": comparison["evaluated_days"],
        "baseline": comparison.get("baseline_metrics"),
        "candidate": comparison.get("candidate_metrics"),
        "frozen": comparison.get("frozen_metrics"),
        "change": comparison.get("change"),
        "parameter_delta": comparison.get("parameter_delta") or {},
        "windows": comparison.get("windows") or {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )


def write_comparison_json(path: Path, comparison: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(comparison, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )


def maybe_write_png(path: Path, comparison: dict[str, Any]) -> Path | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    series = comparison["series"]
    if not series:
        return None
    times = [row["time"] for row in series]
    observed = [row["observed_m3s"] for row in series]
    fig, axes = plt.subplots(
        2, 1, figsize=(10.5, 6.4), sharex=True, gridspec_kw={"height_ratios": (3, 1)}
    )
    axes[0].plot(times, observed, color="#111111", linewidth=1.4, label="Observed")
    if any(row["baseline_m3s"] is not None for row in series):
        axes[0].plot(
            times,
            [row["baseline_m3s"] for row in series],
            color="#6e7b85",
            linewidth=1.1,
            linestyle="--",
            label="Baseline Scheme",
        )
    if any(row["candidate_m3s"] is not None for row in series):
        axes[0].plot(
            times,
            [row["candidate_m3s"] for row in series],
            color="#1889ee",
            linewidth=1.3,
            label="Candidate Scheme",
        )
    if any(row["frozen_m3s"] is not None for row in series):
        axes[0].plot(
            times,
            [row["frozen_m3s"] for row in series],
            color="#1f6b4a",
            linewidth=1.4,
            label="Frozen Scheme",
        )
    warmup_span = [i for i, row in enumerate(series) if row["is_warmup"]]
    if warmup_span:
        axes[0].axvspan(
            times[warmup_span[0]],
            times[warmup_span[-1]],
            color="#d7dde3",
            alpha=0.35,
            label="Warm-up",
        )
    axes[0].set_ylabel("Discharge (m³/s)")
    axes[0].set_title(comparison["title"])
    axes[0].legend(loc="upper right", frameon=False)
    residual_src = "candidate_m3s" if comparison["kind"] == "calibration" else "frozen_m3s"
    residual = []
    for row in series:
        obs = row["observed_m3s"]
        sim = row[residual_src]
        residual.append(None if obs is None or sim is None else float(sim - obs))
    axes[1].plot(times, residual, color="#b42318", linewidth=1.0, label="Sim − Observed")
    axes[1].axhline(0, color="#98a2ad", linewidth=0.8)
    axes[1].set_ylabel("Δ m³/s")
    axes[1].set_xlabel("Date")
    fig.autofmt_xdate()
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def write_bundle(directory: Path, comparison: dict[str, Any], *, stem: str) -> dict[str, str]:
    csv_path = directory / f"{stem}.csv"
    json_path = directory / f"{stem}.json"
    metrics_name = (
        "calibration-metrics.json" if comparison["kind"] == "calibration" else "test-metrics.json"
    )
    metrics_path = directory / metrics_name
    write_comparison_csv(csv_path, comparison)
    write_comparison_json(json_path, comparison)
    write_metrics_json(metrics_path, comparison)
    png = maybe_write_png(directory / f"{stem}.png", comparison)
    artifacts = {
        "csv": csv_path.name,
        "json": json_path.name,
        "metrics": metrics_path.name,
    }
    if png is not None:
        artifacts["png"] = png.name
    return artifacts
