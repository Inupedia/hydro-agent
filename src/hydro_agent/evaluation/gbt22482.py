"""GB/T 22482—2026 §6.5 flood-forecast accuracy helpers (Q / discharge focus)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import numpy as np

from hydro_agent.evaluation.metrics import nse as nse_metric

BasinClass = Literal["gt3000", "mid", "plain"]
SchemeGrade = Literal["甲", "乙", "丙", "不合格"]
GrdGrade = Literal["优秀", "良好", "合格", "不合格"]
TimelinessGrade = Literal["甲", "乙", "丙", "不合格", "pending"]
MetricStatus = Literal["pass", "fail", "not_applicable", "pending"]

GRADE_RANK = {"不合格": 0, "丙": 1, "乙": 2, "甲": 3}


@dataclass(frozen=True)
class GbtAccuracyConfig:
    min_scheme_grade: SchemeGrade = "丙"
    basin_class: Literal["auto", "gt3000", "mid", "plain"] = "auto"
    peak_rel_error_large: float = 0.20
    peak_rel_error_mid: float = 0.30
    peak_timing_frac: float = 0.30
    peak_timing_min_hours: float = 3.0
    runoff_rel_error: float = 0.20
    runoff_max_mm: float = 20.0
    runoff_min_mm: float = 3.0
    process_amp_frac: float = 0.20
    process_min_rel: float = 0.05
    grade_dc_jia: float = 0.90
    grade_dc_yi: float = 0.70
    grade_dc_bing: float = 0.50
    grade_qr_jia: float = 85.0
    grade_qr_yi: float = 70.0
    grade_qr_bing: float = 60.0
    area_km2: float | None = None

    @classmethod
    def from_metadata(
        cls, meta: dict[str, str], *, area_km2: float | None = None
    ) -> GbtAccuracyConfig:
        def f(key: str, default: float) -> float:
            raw = meta.get(key)
            if raw is None or raw == "":
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        grade = str(meta.get("min_scheme_grade") or "丙").strip()
        if grade not in GRADE_RANK:
            grade = "丙"
        basin = str(meta.get("basin_class") or "auto").strip()
        if basin not in {"auto", "gt3000", "mid", "plain"}:
            basin = "auto"
        return cls(
            min_scheme_grade=grade,  # type: ignore[arg-type]
            basin_class=basin,  # type: ignore[arg-type]
            peak_rel_error_large=f("peak_rel_error_large", 0.20),
            peak_rel_error_mid=f("peak_rel_error_mid", 0.30),
            peak_timing_frac=f("peak_timing_frac", 0.30),
            peak_timing_min_hours=f("peak_timing_min_hours", 3.0),
            runoff_rel_error=f("runoff_rel_error", 0.20),
            runoff_max_mm=f("runoff_max_mm", 20.0),
            runoff_min_mm=f("runoff_min_mm", 3.0),
            process_amp_frac=f("process_amp_frac", 0.20),
            process_min_rel=f("process_min_rel", 0.05),
            grade_dc_jia=f("grade_dc_jia", 0.90),
            grade_dc_yi=f("grade_dc_yi", 0.70),
            grade_dc_bing=f("grade_dc_bing", 0.50),
            grade_qr_jia=f("grade_qr_jia", 85.0),
            grade_qr_yi=f("grade_qr_yi", 70.0),
            grade_qr_bing=f("grade_qr_bing", 60.0),
            area_km2=area_km2 if area_km2 is not None else _optional_float(meta.get("area_km2")),
        )


@dataclass(frozen=True)
class HydroSeries:
    """Observed vs simulated discharge series for one evaluation window."""

    obs: tuple[float, ...]
    sim: tuple[float, ...]
    times: tuple[datetime, ...] | None = None
    dt_hours: float = 24.0
    publish_time: datetime | None = None
    area_km2: float | None = None
    has_stage: bool = False

    def __post_init__(self) -> None:
        if len(self.obs) != len(self.sim):
            raise ValueError("obs/sim length mismatch")
        if self.times is not None and len(self.times) != len(self.obs):
            raise ValueError("times length mismatch")


@dataclass(frozen=True)
class GbtMetricResult:
    metric_id: str
    status: MetricStatus
    value: float | None = None
    permitted: float | None = None
    grade: str | None = None
    detail: str = ""
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class GbtAccuracyReport:
    metrics: tuple[GbtMetricResult, ...]
    scheme_grade: SchemeGrade
    accuracy_rate: float | None
    dc: float | None
    meets_min_grade: bool
    min_scheme_grade: SchemeGrade
    basin_class: BasinClass
    summary: str = ""

    def as_metrics_dict(self) -> dict[str, float]:
        out: dict[str, float] = {}
        if self.dc is not None:
            out["DC"] = float(self.dc)
            out["NSE"] = float(self.dc)
        if self.accuracy_rate is not None:
            out["QR"] = float(self.accuracy_rate)
        out["scheme_grade_rank"] = float(GRADE_RANK.get(self.scheme_grade, 0))
        for item in self.metrics:
            if item.value is not None and np.isfinite(item.value):
                out[f"gbt_{item.metric_id}"] = float(item.value)
        return out

    def model_dump(self) -> dict:
        return {
            "scheme_grade": self.scheme_grade,
            "accuracy_rate": self.accuracy_rate,
            "dc": self.dc,
            "meets_min_grade": self.meets_min_grade,
            "min_scheme_grade": self.min_scheme_grade,
            "basin_class": self.basin_class,
            "summary": self.summary,
            "metrics": [
                {
                    "metric_id": m.metric_id,
                    "status": m.status,
                    "value": m.value,
                    "permitted": m.permitted,
                    "grade": m.grade,
                    "detail": m.detail,
                    "reasons": list(m.reasons),
                }
                for m in self.metrics
            ],
        }


def resolve_basin_class(area_km2: float | None, configured: str) -> BasinClass:
    if configured in {"gt3000", "mid", "plain"}:
        return configured  # type: ignore[return-value]
    if area_km2 is None:
        return "mid"
    if area_km2 > 3000:
        return "gt3000"
    if area_km2 >= 200:
        return "mid"
    return "mid"


def peak_flow_permitted(obs_peak: float, basin: BasinClass, cfg: GbtAccuracyConfig) -> float:
    frac = cfg.peak_rel_error_large if basin == "gt3000" else cfg.peak_rel_error_mid
    permitted = abs(obs_peak) * frac
    floor = abs(obs_peak) * 0.05
    return max(permitted, floor)


def peak_timing_permitted_hours(basis_to_peak_hours: float, cfg: GbtAccuracyConfig) -> float:
    return max(cfg.peak_timing_min_hours, abs(basis_to_peak_hours) * cfg.peak_timing_frac)


def runoff_permitted(obs_volume: float, cfg: GbtAccuracyConfig) -> float:
    permitted = abs(obs_volume) * cfg.runoff_rel_error
    return float(np.clip(permitted, cfg.runoff_min_mm, max(cfg.runoff_max_mm, permitted)))


def process_point_permitted(obs: float, amplitude: float, cfg: GbtAccuracyConfig) -> float:
    amp_err = abs(amplitude) * cfg.process_amp_frac
    floor = abs(obs) * cfg.process_min_rel
    return max(amp_err, floor)


def grade_from_dc(dc: float, cfg: GbtAccuracyConfig) -> SchemeGrade:
    if dc >= cfg.grade_dc_jia:
        return "甲"
    if dc >= cfg.grade_dc_yi:
        return "乙"
    if dc >= cfg.grade_dc_bing:
        return "丙"
    return "不合格"


def grade_from_qr(qr: float, cfg: GbtAccuracyConfig) -> SchemeGrade:
    if qr >= cfg.grade_qr_jia:
        return "甲"
    if qr >= cfg.grade_qr_yi:
        return "乙"
    if qr >= cfg.grade_qr_bing:
        return "丙"
    return "不合格"


def combine_scheme_grade(dc_grade: SchemeGrade, qr_grade: SchemeGrade) -> SchemeGrade:
    """§6.5.6: use the stricter (lower) of DC and QR grades for the scheme."""
    return min(dc_grade, qr_grade, key=lambda g: GRADE_RANK[g])


def grade_meets_min(actual: SchemeGrade, minimum: SchemeGrade) -> bool:
    return GRADE_RANK.get(actual, 0) >= GRADE_RANK.get(minimum, 0)


def grd_grade(error: float, permitted: float) -> GrdGrade:
    if permitted <= 0:
        return "不合格"
    grd = abs(error) / permitted * 100.0
    if grd <= 25.0:
        return "优秀"
    if grd <= 50.0:
        return "良好"
    if grd <= 100.0:
        return "合格"
    return "不合格"


def timeliness_grade(cet: float, dh_hours: float) -> TimelinessGrade:
    if cet >= 0.95 and dh_hours <= 0.6:
        return "甲"
    if cet >= 0.85 and dh_hours <= 0.8:
        return "乙"
    if cet >= 0.70 and dh_hours <= 1.0:
        return "丙"
    return "不合格"


def evaluate_peak_flow(
    series: HydroSeries, cfg: GbtAccuracyConfig, basin: BasinClass
) -> GbtMetricResult:
    obs = np.asarray(series.obs, dtype=float)
    sim = np.asarray(series.sim, dtype=float)
    if obs.size == 0:
        return GbtMetricResult("peak_flow", "not_applicable", detail="empty series")
    obs_peak = float(np.max(obs))
    sim_peak = float(np.max(sim))
    err = abs(sim_peak - obs_peak)
    permitted = peak_flow_permitted(obs_peak, basin, cfg)
    ok = err <= permitted
    return GbtMetricResult(
        metric_id="peak_flow",
        status="pass" if ok else "fail",
        value=err,
        permitted=permitted,
        detail=f"obs_peak={obs_peak:.4f} sim_peak={sim_peak:.4f}",
        reasons=() if ok else ("peak_flow_exceeds_permitted",),
    )


def evaluate_peak_timing(series: HydroSeries, cfg: GbtAccuracyConfig) -> GbtMetricResult:
    obs = np.asarray(series.obs, dtype=float)
    sim = np.asarray(series.sim, dtype=float)
    if obs.size < 2:
        return GbtMetricResult("peak_timing", "not_applicable", detail="need >=2 points")
    i_obs = int(np.argmax(obs))
    i_sim = int(np.argmax(sim))
    dt = float(series.dt_hours)
    err_h = abs(i_sim - i_obs) * dt
    # Basis → observed peak: use start of series as forecast basis when publish_time absent.
    basis_to_peak = max(dt, i_obs * dt)
    if series.times is not None and series.publish_time is not None:
        basis_to_peak = max(
            dt,
            (series.times[i_obs] - series.publish_time).total_seconds() / 3600.0,
        )
    permitted = peak_timing_permitted_hours(basis_to_peak, cfg)
    ok = err_h <= permitted
    return GbtMetricResult(
        metric_id="peak_timing",
        status="pass" if ok else "fail",
        value=err_h,
        permitted=permitted,
        detail=f"obs_idx={i_obs} sim_idx={i_sim} basis_to_peak_h={basis_to_peak:.2f}",
        reasons=() if ok else ("peak_timing_exceeds_permitted",),
    )


def evaluate_runoff_volume(series: HydroSeries, cfg: GbtAccuracyConfig) -> GbtMetricResult:
    obs = np.asarray(series.obs, dtype=float)
    sim = np.asarray(series.sim, dtype=float)
    if obs.size == 0:
        return GbtMetricResult("runoff_volume", "not_applicable", detail="empty series")
    # Convert mean discharge * duration to volume proxy; relative error is scale-free.
    obs_vol = float(np.sum(obs) * series.dt_hours)
    sim_vol = float(np.sum(sim) * series.dt_hours)
    err = abs(sim_vol - obs_vol)
    permitted = abs(obs_vol) * cfg.runoff_rel_error
    ok = err <= permitted + 1e-12
    return GbtMetricResult(
        metric_id="runoff_volume",
        status="pass" if ok else "fail",
        value=err / max(abs(obs_vol), 1e-9),
        permitted=cfg.runoff_rel_error,
        detail=f"obs_vol={obs_vol:.4f} sim_vol={sim_vol:.4f}",
        reasons=() if ok else ("runoff_volume_exceeds_permitted",),
    )


def evaluate_process(series: HydroSeries, cfg: GbtAccuracyConfig) -> GbtMetricResult:
    obs = np.asarray(series.obs, dtype=float)
    sim = np.asarray(series.sim, dtype=float)
    if obs.size == 0:
        return GbtMetricResult("process", "not_applicable", detail="empty series")
    amplitude = float(np.max(obs) - np.min(obs)) if obs.size else 0.0
    accurate = 0
    for o, s in zip(obs, sim):
        permitted = process_point_permitted(float(o), amplitude, cfg)
        if abs(float(s) - float(o)) <= permitted:
            accurate += 1
    qr = 100.0 * accurate / len(obs)
    ok = accurate == len(obs)  # process node itself: all points within? Use QR later.
    # Status = pass if point-wise QR >= bing threshold portion of points.
    ok = qr >= cfg.grade_qr_bing
    return GbtMetricResult(
        metric_id="process",
        status="pass" if ok else "fail",
        value=qr,
        permitted=cfg.grade_qr_bing,
        detail=f"accurate_points={accurate}/{len(obs)}",
        reasons=() if ok else ("process_accuracy_below_bing",),
    )


def evaluate_dc_nse(series: HydroSeries, cfg: GbtAccuracyConfig) -> GbtMetricResult:
    try:
        dc = nse_metric(series.obs, series.sim)
    except ValueError as exc:
        return GbtMetricResult("dc_nse", "not_applicable", detail=str(exc))
    grade = grade_from_dc(dc, cfg)
    ok = grade_meets_min(grade, cfg.min_scheme_grade)
    return GbtMetricResult(
        metric_id="dc_nse",
        status="pass" if ok else "fail",
        value=dc,
        permitted=cfg.grade_dc_bing,
        grade=grade,
        detail=f"DC={dc:.4f} grade={grade}",
        reasons=() if ok else ("dc_below_min_scheme_grade",),
    )


def evaluate_accuracy_rate(
    series: HydroSeries, cfg: GbtAccuracyConfig, basin: BasinClass
) -> GbtMetricResult:
    """QR over forecast events: each local peak window counts as one forecast (V1)."""
    events = _extract_peak_events(series)
    if not events:
        # Fall back to whole-series peak + process composite as one event.
        peak = evaluate_peak_flow(series, cfg, basin)
        timing = evaluate_peak_timing(series, cfg)
        volume = evaluate_runoff_volume(series, cfg)
        accurate = int(
            peak.status == "pass" and timing.status == "pass" and volume.status == "pass"
        )
        total = 1
    else:
        accurate = 0
        total = 0
        for event in events:
            total += 1
            peak = evaluate_peak_flow(event, cfg, basin)
            timing = evaluate_peak_timing(event, cfg)
            volume = evaluate_runoff_volume(event, cfg)
            if peak.status == "pass" and timing.status == "pass" and volume.status == "pass":
                accurate += 1
    qr = 100.0 * accurate / max(total, 1)
    grade = grade_from_qr(qr, cfg)
    ok = grade_meets_min(grade, cfg.min_scheme_grade)
    return GbtMetricResult(
        metric_id="accuracy_rate",
        status="pass" if ok else "fail",
        value=qr,
        permitted=cfg.grade_qr_bing,
        grade=grade,
        detail=f"QR={qr:.1f}% accurate={accurate}/{total} grade={grade}",
        reasons=() if ok else ("qr_below_min_scheme_grade",),
    )


def evaluate_grd(series: HydroSeries, cfg: GbtAccuracyConfig, basin: BasinClass) -> GbtMetricResult:
    peak = evaluate_peak_flow(series, cfg, basin)
    if peak.permitted is None or peak.value is None:
        return GbtMetricResult("grd", "not_applicable", detail="no peak")
    grade = grd_grade(peak.value, peak.permitted)
    ok = grade != "不合格"
    return GbtMetricResult(
        metric_id="grd",
        status="pass" if ok else "fail",
        value=(peak.value / peak.permitted * 100.0) if peak.permitted else None,
        permitted=100.0,
        grade=grade,
        detail=f"GRD_peak grade={grade}",
        reasons=() if ok else ("grd_unqualified",),
    )


def evaluate_timeliness(series: HydroSeries, cfg: GbtAccuracyConfig) -> GbtMetricResult:
    if series.publish_time is None or series.times is None or not series.times:
        return GbtMetricResult(
            "timeliness",
            "pending",
            detail="missing publish_time or times",
            grade="pending",
        )
    obs = np.asarray(series.obs, dtype=float)
    i_obs = int(np.argmax(obs))
    peak_time = series.times[i_obs]
    # Theoretical foresee period: from series start (basis) to observed peak.
    tpf = max(0.1, (peak_time - series.times[0]).total_seconds() / 3600.0)
    epf = max(0.0, (peak_time - series.publish_time).total_seconds() / 3600.0)
    cet = epf / tpf if tpf > 0 else 0.0
    dh = tpf - epf
    grade = timeliness_grade(cet, dh)
    ok = grade in {"甲", "乙", "丙"}
    return GbtMetricResult(
        metric_id="timeliness",
        status="pass" if ok else "fail",
        value=cet,
        permitted=0.70,
        grade=grade,
        detail=f"CET={cet:.2f} dh={dh:.2f}h grade={grade}",
        reasons=() if ok else ("timeliness_unqualified",),
    )


def evaluate_scheme_grade(
    dc_result: GbtMetricResult,
    qr_result: GbtMetricResult,
    cfg: GbtAccuracyConfig,
) -> GbtMetricResult:
    dc_grade = (dc_result.grade or "不合格") if dc_result.grade in GRADE_RANK else "不合格"
    qr_grade = (qr_result.grade or "不合格") if qr_result.grade in GRADE_RANK else "不合格"
    scheme = combine_scheme_grade(dc_grade, qr_grade)  # type: ignore[arg-type]
    ok = grade_meets_min(scheme, cfg.min_scheme_grade)
    return GbtMetricResult(
        metric_id="scheme_grade",
        status="pass" if ok else "fail",
        value=float(GRADE_RANK[scheme]),
        permitted=float(GRADE_RANK[cfg.min_scheme_grade]),
        grade=scheme,
        detail=f"scheme={scheme} dc={dc_grade} qr={qr_grade} min={cfg.min_scheme_grade}",
        reasons=() if ok else ("scheme_grade_below_min",),
    )


def build_gbt_accuracy_report(series: HydroSeries, cfg: GbtAccuracyConfig) -> GbtAccuracyReport:
    area = series.area_km2 if series.area_km2 is not None else cfg.area_km2
    basin = resolve_basin_class(area, cfg.basin_class)
    peak = evaluate_peak_flow(series, cfg, basin)
    timing = evaluate_peak_timing(series, cfg)
    volume = evaluate_runoff_volume(series, cfg)
    process = evaluate_process(series, cfg)
    dc = evaluate_dc_nse(series, cfg)
    qr = evaluate_accuracy_rate(series, cfg, basin)
    grd = evaluate_grd(series, cfg, basin)
    time_m = evaluate_timeliness(series, cfg)
    grade = evaluate_scheme_grade(dc, qr, cfg)
    metrics = (peak, timing, volume, process, dc, qr, grd, time_m, grade)
    scheme_grade = grade.grade if grade.grade in GRADE_RANK else "不合格"
    meets = grade_meets_min(scheme_grade, cfg.min_scheme_grade)  # type: ignore[arg-type]
    # Hard fails (excluding pending/N/A) also block "meets".
    hard_fail = any(
        m.status == "fail" and m.metric_id in {"peak_flow", "peak_timing", "runoff_volume"}
        for m in metrics
    )
    if hard_fail and scheme_grade != "不合格":
        # Keep scheme grade from table1 but mark meets only if grade ok AND no hard fails
        # for accept path — plan: ACCEPT only when scheme_grade >= min.
        # Hard peak failures typically pull QR down; still require grade.
        pass
    summary = (
        f"GB/T22482 scheme_grade={scheme_grade} DC={dc.value} QR={qr.value} "
        f"basin={basin} meets_min={meets}"
    )
    return GbtAccuracyReport(
        metrics=metrics,
        scheme_grade=scheme_grade,  # type: ignore[arg-type]
        accuracy_rate=qr.value,
        dc=dc.value,
        meets_min_grade=meets,
        min_scheme_grade=cfg.min_scheme_grade,
        basin_class=basin,
        summary=summary,
    )


def series_from_lead_lists(
    lead_series: dict[int, tuple[list[float], list[float]]],
    *,
    start: datetime | None = None,
    dt_hours: float = 24.0,
    area_km2: float | None = None,
    publish_time: datetime | None = None,
) -> HydroSeries:
    """Flatten lead-1/2/3 obs/sim lists into one evaluation series (prefer lead-1 then others)."""
    obs: list[float] = []
    sim: list[float] = []
    times: list[datetime] = []
    origin = start or datetime(2000, 1, 1)
    idx = 0
    for lead in (1, 2, 3):
        if lead not in lead_series:
            continue
        o, s = lead_series[lead]
        for ov, sv in zip(o, s):
            obs.append(float(ov))
            sim.append(float(sv))
            times.append(origin + timedelta(hours=dt_hours * idx))
            idx += 1
    if not obs:
        raise ValueError("empty lead series")
    return HydroSeries(
        obs=tuple(obs),
        sim=tuple(sim),
        times=tuple(times),
        dt_hours=dt_hours,
        publish_time=publish_time or origin,
        area_km2=area_km2,
    )


def _extract_peak_events(series: HydroSeries, *, min_points: int = 3) -> list[HydroSeries]:
    """Simple event split: contiguous windows around local maxima above median."""
    obs = np.asarray(series.obs, dtype=float)
    if obs.size < min_points * 2:
        return []
    median = float(np.median(obs))
    peaks = []
    for i in range(1, obs.size - 1):
        if obs[i] >= obs[i - 1] and obs[i] >= obs[i + 1] and obs[i] > median:
            peaks.append(i)
    if not peaks:
        return []
    events: list[HydroSeries] = []
    for i in peaks:
        left = max(0, i - 2)
        right = min(obs.size, i + 3)
        if right - left < min_points:
            continue
        times = series.times[left:right] if series.times is not None else None
        events.append(
            HydroSeries(
                obs=tuple(series.obs[left:right]),
                sim=tuple(series.sim[left:right]),
                times=times,
                dt_hours=series.dt_hours,
                publish_time=series.publish_time,
                area_km2=series.area_km2,
            )
        )
    return events


def _optional_float(raw: str | None) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None
