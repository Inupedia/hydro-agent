from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Iterable

import numpy as np

from hydro_agent.evaluation.metrics import bias, high_flow_mae, kge, mae, nse


@dataclass(frozen=True)
class FloodEvent:
    event_id: str
    start_index: int
    peak_index: int
    end_index: int
    magnitude_class: str
    observed_peak: float
    simulated_peak: float
    peak_relative_error: float
    peak_timing_steps: float
    volume_relative_error: float
    recession_relative_error: float


@dataclass(frozen=True)
class HydrologicSignatures:
    metrics: dict[str, float]
    events: tuple[FloodEvent, ...]


def _safe_rel_error(sim: float, obs: float) -> float:
    return abs(float(sim) - float(obs)) / max(abs(float(obs)), 1e-9)


def _signed_rel_error(sim: float, obs: float) -> float:
    return (float(sim) - float(obs)) / max(abs(float(obs)), 1e-9)


def _year_groups(times: tuple[datetime, ...] | None, n: int) -> list[list[int]]:
    if times is None or len(times) != n:
        return [list(range(n))]
    groups: dict[int, list[int]] = {}
    for i, stamp in enumerate(times):
        groups.setdefault(stamp.year, []).append(i)
    return list(groups.values())


def _season_groups(times: tuple[datetime, ...] | None, n: int) -> list[list[int]]:
    if times is None or len(times) != n:
        return [list(range(n))]
    groups: dict[tuple[int, str], list[int]] = {}
    for i, stamp in enumerate(times):
        month = stamp.month
        if month in (12, 1, 2):
            season = "DJF"
            season_year = stamp.year + (1 if month == 12 else 0)
        elif month in (3, 4, 5):
            season = "MAM"
            season_year = stamp.year
        elif month in (6, 7, 8):
            season = "JJA"
            season_year = stamp.year
        else:
            season = "SON"
            season_year = stamp.year
        groups.setdefault((season_year, season), []).append(i)
    return list(groups.values())


def _group_volume_bias(obs: np.ndarray, sim: np.ndarray, groups: Iterable[list[int]]) -> float:
    values: list[float] = []
    for idx in groups:
        if not idx:
            continue
        o = float(np.sum(obs[idx]))
        s = float(np.sum(sim[idx]))
        if abs(o) <= 1e-9:
            continue
        values.append(abs(_signed_rel_error(s, o)))
    return float(np.mean(values)) if values else 0.0


def _recession_slopes(values: np.ndarray) -> tuple[float, float, float]:
    """Median ln(Q) recession slope for fast/middle/tail flow bands.

    The signature is intentionally simple and auditable. Only strictly falling,
    positive consecutive pairs are used. Flow bands are based on the observed
    series quantiles so the three slopes describe fast, intermediate and slow
    drainage behaviour without fitting a hidden black-box recession model.
    """

    positive = values[values > 0]
    if positive.size < 6:
        return 0.0, 0.0, 0.0
    q33, q66 = np.quantile(positive, [0.33, 0.66])
    buckets: dict[str, list[float]] = {"fast": [], "mid": [], "tail": []}
    for left, right in zip(values[:-1], values[1:]):
        if left <= 0 or right <= 0 or right >= left:
            continue
        slope = abs(float(np.log(right) - np.log(left)))
        if left >= q66:
            buckets["fast"].append(slope)
        elif left >= q33:
            buckets["mid"].append(slope)
        else:
            buckets["tail"].append(slope)
    return tuple(
        float(median(buckets[name])) if buckets[name] else 0.0
        for name in ("fast", "mid", "tail")
    )


def _recession_error(obs: np.ndarray, sim: np.ndarray) -> tuple[float, float, float, float]:
    obs_slopes = _recession_slopes(obs)
    sim_slopes = _recession_slopes(sim)
    errors = tuple(_safe_rel_error(s, o) if o > 0 else 0.0 for o, s in zip(obs_slopes, sim_slopes))
    nonzero = [value for value in errors if value > 0]
    aggregate = float(max(nonzero)) if nonzero else 0.0
    return aggregate, errors[0], errors[1], errors[2]


def _event_ranges(obs: np.ndarray, *, quantile: float = 0.90, max_gap: int = 1) -> list[tuple[int, int]]:
    if obs.size < 10:
        return []
    threshold = float(np.quantile(obs, quantile))
    high = [i for i, value in enumerate(obs) if value >= threshold]
    if not high:
        return []
    ranges: list[tuple[int, int]] = []
    start = previous = high[0]
    for i in high[1:]:
        if i - previous <= max_gap + 1:
            previous = i
            continue
        ranges.append((max(0, start - 1), min(len(obs) - 1, previous + 2)))
        start = previous = i
    ranges.append((max(0, start - 1), min(len(obs) - 1, previous + 2)))

    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def build_flood_event_bank(
    obs_values: Iterable[float],
    sim_values: Iterable[float],
    *,
    times: tuple[datetime, ...] | None = None,
    quantile: float = 0.90,
) -> tuple[FloodEvent, ...]:
    obs = np.asarray(tuple(obs_values), dtype=float)
    sim = np.asarray(tuple(sim_values), dtype=float)
    if obs.size != sim.size:
        raise ValueError("obs/sim length mismatch")
    ranges = _event_ranges(obs, quantile=quantile)
    if not ranges:
        return ()

    peaks = [float(np.max(obs[start : end + 1])) for start, end in ranges]
    p33, p67 = np.quantile(np.asarray(peaks, dtype=float), [0.33, 0.67])
    events: list[FloodEvent] = []
    for ordinal, (start, end) in enumerate(ranges, start=1):
        obs_segment = obs[start : end + 1]
        sim_segment = sim[start : end + 1]
        obs_local_peak = int(np.argmax(obs_segment))
        sim_local_peak = int(np.argmax(sim_segment))
        obs_peak = float(obs_segment[obs_local_peak])
        sim_peak = float(sim_segment[sim_local_peak])
        obs_volume = float(np.sum(obs_segment))
        sim_volume = float(np.sum(sim_segment))
        recession_start = obs_local_peak
        obs_recession = obs_segment[recession_start:]
        sim_recession = sim_segment[recession_start:]
        recession_error, _, _, _ = _recession_error(obs_recession, sim_recession)
        if obs_peak >= p67:
            magnitude = "large"
        elif obs_peak >= p33:
            magnitude = "medium"
        else:
            magnitude = "small"
        if times is not None and len(times) == len(obs):
            event_id = f"{times[start].date().isoformat()}_{times[end].date().isoformat()}"
        else:
            event_id = f"event-{ordinal:03d}"
        events.append(
            FloodEvent(
                event_id=event_id,
                start_index=start,
                peak_index=start + obs_local_peak,
                end_index=end,
                magnitude_class=magnitude,
                observed_peak=obs_peak,
                simulated_peak=sim_peak,
                peak_relative_error=_safe_rel_error(sim_peak, obs_peak),
                peak_timing_steps=float(abs(sim_local_peak - obs_local_peak)),
                volume_relative_error=_safe_rel_error(sim_volume, obs_volume),
                recession_relative_error=recession_error,
            )
        )
    return tuple(events)


def _event_metric(events: tuple[FloodEvent, ...], attr: str, *, magnitude: str | None = None) -> float:
    values = [
        float(getattr(event, attr))
        for event in events
        if magnitude is None or event.magnitude_class == magnitude
    ]
    return float(median(values)) if values else 0.0


def compute_hydrologic_signatures(
    obs_values: Iterable[float],
    sim_values: Iterable[float],
    *,
    times: tuple[datetime, ...] | None = None,
    precipitation_mm: Iterable[float] | None = None,
    area_km2: float | None = None,
    dt_hours: float = 24.0,
) -> HydrologicSignatures:
    obs = np.asarray(tuple(obs_values), dtype=float)
    sim = np.asarray(tuple(sim_values), dtype=float)
    if obs.size != sim.size:
        raise ValueError("obs/sim length mismatch")
    if obs.size < 2:
        raise ValueError("hydrologic signatures require at least 2 pairs")

    obs_volume = float(np.sum(obs))
    sim_volume = float(np.sum(sim))
    volume_bias = _signed_rel_error(sim_volume, obs_volume)
    recession_error, recession_fast, recession_mid, recession_tail = _recession_error(obs, sim)
    events = build_flood_event_bank(obs, sim, times=times)

    try:
        kge_value = float(kge(obs.tolist(), sim.tolist()))
    except ValueError:
        kge_value = 0.0
    try:
        nse_value = float(nse(obs.tolist(), sim.tolist()))
    except ValueError:
        nse_value = float("-inf")

    peak_obs_i = int(np.argmax(obs))
    peak_sim_i = int(np.argmax(sim))
    peak_obs = float(obs[peak_obs_i])
    peak_sim = float(sim[peak_sim_i])
    q90 = float(np.quantile(obs, 0.90))
    q90_idx = np.flatnonzero(obs >= q90)
    q90_obs = float(np.sum(obs[q90_idx])) if q90_idx.size else 0.0
    q90_sim = float(np.sum(sim[q90_idx])) if q90_idx.size else 0.0

    metrics = {
        "sample_count": float(obs.size),
        "nse": nse_value,
        "kge": kge_value,
        "bias": float(bias(obs.tolist(), sim.tolist())),
        "mae": float(mae(obs.tolist(), sim.tolist())),
        "high_flow_mae_q90": float(high_flow_mae(obs.tolist(), sim.tolist(), quantile=0.90)),
        "volume_bias": float(volume_bias),
        "volume_rel_error": float(abs(volume_bias)),
        "annual_volume_bias_mae": _group_volume_bias(obs, sim, _year_groups(times, len(obs))),
        "seasonal_volume_bias_mae": _group_volume_bias(obs, sim, _season_groups(times, len(obs))),
        "peak_ratio": float(peak_sim / max(peak_obs, 1e-9)),
        "peak_rel_error": _safe_rel_error(peak_sim, peak_obs),
        "peak_timing_steps": float(abs(peak_sim_i - peak_obs_i)),
        "flood_volume_bias_q90": _signed_rel_error(q90_sim, q90_obs) if q90_obs > 0 else 0.0,
        "flood_volume_rel_error_q90": _safe_rel_error(q90_sim, q90_obs) if q90_obs > 0 else 0.0,
        "recession_relative_error": recession_error,
        "recession_fast_rel_error": recession_fast,
        "recession_mid_rel_error": recession_mid,
        "recession_tail_rel_error": recession_tail,
        "flood_event_count": float(len(events)),
        "event_peak_rel_error_median": _event_metric(events, "peak_relative_error"),
        "event_peak_timing_steps_median": _event_metric(events, "peak_timing_steps"),
        "event_volume_rel_error_median": _event_metric(events, "volume_relative_error"),
        "event_recession_rel_error_median": _event_metric(events, "recession_relative_error"),
        "large_event_peak_rel_error_median": _event_metric(events, "peak_relative_error", magnitude="large"),
        "large_event_peak_timing_steps_median": _event_metric(events, "peak_timing_steps", magnitude="large"),
        "large_event_volume_rel_error_median": _event_metric(events, "volume_relative_error", magnitude="large"),
    }

    if area_km2 and area_km2 > 0:
        seconds = float(dt_hours) * 3600.0
        divisor = float(area_km2) * 1_000_000.0
        metrics["observed_runoff_depth_mm"] = float(np.sum(obs) * seconds / divisor * 1000.0)
        metrics["simulated_runoff_depth_mm"] = float(np.sum(sim) * seconds / divisor * 1000.0)
    if precipitation_mm is not None:
        precipitation = np.asarray(tuple(precipitation_mm), dtype=float)
        if precipitation.size == obs.size:
            precip_total = float(np.sum(precipitation))
            metrics["precipitation_total_mm"] = precip_total
            if precip_total > 0 and "observed_runoff_depth_mm" in metrics:
                metrics["observed_runoff_ratio"] = metrics["observed_runoff_depth_mm"] / precip_total
                metrics["simulated_runoff_ratio"] = metrics["simulated_runoff_depth_mm"] / precip_total

    return HydrologicSignatures(metrics=metrics, events=events)
