"""Hydrologic evidence builder for auditable calibration experiments.

This module turns one uninterrupted observed/simulated trajectory into structured
hydrologic evidence.  It is deliberately conservative: sections that do not have
enough valid samples are marked ``insufficient_data`` instead of emitting unstable
statistics.  The builder never chooses parameters and never reads final-test data
implicitly; callers own experiment-window isolation.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Mapping, Sequence

import numpy as np

from hydro_agent.evaluation.metrics import kge, mae, nse, pbias_percent, rmse


@dataclass(frozen=True)
class QualityReport:
    total_count: int
    valid_count: int
    dropped_count: int
    coverage: float
    dropped_by_reason: dict[str, int]


@dataclass(frozen=True)
class EvidenceSlice:
    name: str
    status: str
    sample_count: int
    start: date | None = None
    end: date | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class FloodEventEvidence:
    event_id: str
    status: str
    start: date
    end: date
    sample_count: int
    metrics: dict[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class HydrologicEvidenceBundle:
    window: str
    quality: QualityReport
    overall: EvidenceSlice
    flow_regimes: dict[str, EvidenceSlice]
    seasons: dict[str, EvidenceSlice]
    years: dict[str, EvidenceSlice]
    fdc: EvidenceSlice
    flood_events: tuple[FloodEventEvidence, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceDelta:
    section: str
    metric: str
    baseline: float
    candidate: float
    delta: float


@dataclass(frozen=True)
class HydrologicEvidenceComparison:
    deltas: tuple[EvidenceDelta, ...]
    improved: tuple[str, ...]
    worsened: tuple[str, ...]
    unchanged: tuple[str, ...]


@dataclass(frozen=True)
class _CleanSeries:
    dates: tuple[date, ...]
    obs: tuple[float, ...]
    sim: tuple[float, ...]
    quality: QualityReport


_DEFAULT_SEASONS: dict[str, tuple[int, ...]] = {
    "DJF": (12, 1, 2),
    "MAM": (3, 4, 5),
    "JJA": (6, 7, 8),
    "SON": (9, 10, 11),
}


class HydrologicEvidenceBuilder:
    """Build multi-scale hydrologic evidence from an already isolated window.

    ``season_definitions`` is explicit because wet/dry seasons are basin-specific.
    Callers may pass e.g. ``{"wet": (5, 6, 7, 8, 9), "dry": (...)}``; when omitted,
    neutral meteorological seasons are used rather than guessing a basin's wet
    season.
    """

    def __init__(
        self,
        *,
        min_overall_samples: int = 2,
        min_slice_samples: int = 5,
        min_year_samples: int = 30,
        min_fdc_samples: int = 20,
        min_event_samples: int = 2,
        low_flow_quantile: float = 0.2,
        high_flow_quantile: float = 0.8,
        flood_threshold_quantile: float = 0.9,
        season_definitions: Mapping[str, Sequence[int]] | None = None,
    ):
        if min_overall_samples < 2 or min_slice_samples < 2 or min_event_samples < 1:
            raise ValueError("minimum sample counts are invalid")
        if min_year_samples < 2 or min_fdc_samples < 2:
            raise ValueError("year/FDC minimum sample counts are invalid")
        if not 0 < low_flow_quantile < high_flow_quantile < 1:
            raise ValueError("flow quantiles must satisfy 0 < low < high < 1")
        if not high_flow_quantile <= flood_threshold_quantile < 1:
            raise ValueError("flood threshold must be >= high-flow quantile and < 1")
        seasons = season_definitions or _DEFAULT_SEASONS
        normalized: dict[str, tuple[int, ...]] = {}
        for name, months in seasons.items():
            values = tuple(int(month) for month in months)
            if not values or any(month < 1 or month > 12 for month in values):
                raise ValueError(f"invalid season definition: {name}")
            normalized[str(name)] = values
        self.min_overall_samples = min_overall_samples
        self.min_slice_samples = min_slice_samples
        self.min_year_samples = min_year_samples
        self.min_fdc_samples = min_fdc_samples
        self.min_event_samples = min_event_samples
        self.low_flow_quantile = low_flow_quantile
        self.high_flow_quantile = high_flow_quantile
        self.flood_threshold_quantile = flood_threshold_quantile
        self.season_definitions = normalized

    def build(
        self,
        *,
        window: str,
        dates: Sequence[date],
        observed: Sequence[float | None],
        simulated: Sequence[float | None],
        quality_mask: Sequence[bool] | None = None,
    ) -> HydrologicEvidenceBundle:
        clean = self._clean(dates, observed, simulated, quality_mask)
        overall = self._slice(
            "overall", clean.dates, clean.obs, clean.sim, self.min_overall_samples
        )
        flow_regimes = self._flow_regimes(clean)
        seasons = self._seasons(clean)
        years = self._years(clean)
        fdc = self._fdc(clean)
        events = self._events(clean)
        return HydrologicEvidenceBundle(
            window=str(window),
            quality=clean.quality,
            overall=overall,
            flow_regimes=flow_regimes,
            seasons=seasons,
            years=years,
            fdc=fdc,
            flood_events=events,
        )

    def _clean(
        self,
        dates: Sequence[date],
        observed: Sequence[float | None],
        simulated: Sequence[float | None],
        quality_mask: Sequence[bool] | None,
    ) -> _CleanSeries:
        if len(dates) != len(observed) or len(dates) != len(simulated):
            raise ValueError("dates/observed/simulated length mismatch")
        if quality_mask is not None and len(quality_mask) != len(dates):
            raise ValueError("quality_mask length mismatch")
        if not dates:
            raise ValueError("hydrologic evidence requires at least one input row")
        if any(later <= earlier for earlier, later in zip(dates, dates[1:])):
            raise ValueError("dates must be strictly increasing")

        reasons: Counter[str] = Counter()
        kept_dates: list[date] = []
        obs_values: list[float] = []
        sim_values: list[float] = []
        for index, day in enumerate(dates):
            if quality_mask is not None and not bool(quality_mask[index]):
                reasons["quality_mask"] += 1
                continue
            try:
                obs = float(observed[index])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                reasons["invalid_observation"] += 1
                continue
            try:
                sim = float(simulated[index])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                reasons["invalid_simulation"] += 1
                continue
            if not math.isfinite(obs):
                reasons["nonfinite_observation"] += 1
                continue
            if obs < 0:
                reasons["negative_observation"] += 1
                continue
            if not math.isfinite(sim):
                reasons["nonfinite_simulation"] += 1
                continue
            # Negative simulations are retained: they are model failures worth
            # scoring, not missing observations that should disappear silently.
            kept_dates.append(day)
            obs_values.append(obs)
            sim_values.append(sim)

        total = len(dates)
        valid = len(kept_dates)
        quality = QualityReport(
            total_count=total,
            valid_count=valid,
            dropped_count=total - valid,
            coverage=float(valid / total),
            dropped_by_reason=dict(sorted(reasons.items())),
        )
        return _CleanSeries(tuple(kept_dates), tuple(obs_values), tuple(sim_values), quality)

    @staticmethod
    def _metric_set(
        obs: Sequence[float], sim: Sequence[float]
    ) -> tuple[dict[str, float], list[str]]:
        metrics: dict[str, float] = {
            "mae": float(mae(obs, sim)),
            "rmse": float(rmse(obs, sim)),
        }
        unavailable: list[str] = []
        for name, func in (("pbias_percent", pbias_percent), ("nse", nse), ("kge", kge)):
            try:
                metrics[name] = float(func(obs, sim))
            except (ValueError, FloatingPointError):
                unavailable.append(name)

        obs_peak_i = max(range(len(obs)), key=lambda index: obs[index])
        sim_peak_i = max(range(len(sim)), key=lambda index: sim[index])
        obs_peak = float(obs[obs_peak_i])
        sim_peak = float(sim[sim_peak_i])
        metrics["peak_observed"] = obs_peak
        metrics["peak_simulated"] = sim_peak
        if obs_peak > 0:
            metrics["peak_ratio"] = float(sim_peak / obs_peak)
            metrics["peak_relative_error"] = float((sim_peak - obs_peak) / obs_peak)
        else:
            unavailable.extend(("peak_ratio", "peak_relative_error"))
        metrics["peak_timing_lag_steps"] = float(sim_peak_i - obs_peak_i)
        obs_volume = float(sum(obs))
        sim_volume = float(sum(sim))
        metrics["volume_observed"] = obs_volume
        metrics["volume_simulated"] = sim_volume
        if obs_volume > 0:
            metrics["volume_ratio"] = float(sim_volume / obs_volume)
        else:
            unavailable.append("volume_ratio")
        return metrics, unavailable

    def _slice(
        self,
        name: str,
        dates: Sequence[date],
        obs: Sequence[float],
        sim: Sequence[float],
        minimum: int,
    ) -> EvidenceSlice:
        count = len(obs)
        if count < minimum:
            return EvidenceSlice(
                name=name,
                status="insufficient_data",
                sample_count=count,
                start=dates[0] if dates else None,
                end=dates[-1] if dates else None,
                notes=(f"requires_at_least={minimum}",),
            )
        metrics, unavailable = self._metric_set(obs, sim)
        notes = tuple(f"metric_unavailable={item}" for item in sorted(set(unavailable)))
        return EvidenceSlice(
            name=name,
            status="available",
            sample_count=count,
            start=dates[0],
            end=dates[-1],
            metrics=metrics,
            notes=notes,
        )

    def _flow_regimes(self, clean: _CleanSeries) -> dict[str, EvidenceSlice]:
        if len(clean.obs) < self.min_slice_samples:
            return {
                name: self._slice(name, (), (), (), self.min_slice_samples)
                for name in ("low", "mid", "high")
            }
        obs_a = np.asarray(clean.obs, dtype=float)
        low_cut = float(np.quantile(obs_a, self.low_flow_quantile))
        high_cut = float(np.quantile(obs_a, self.high_flow_quantile))
        groups: dict[str, list[int]] = {"low": [], "mid": [], "high": []}
        for index, value in enumerate(clean.obs):
            if value <= low_cut:
                groups["low"].append(index)
            elif value >= high_cut:
                groups["high"].append(index)
            else:
                groups["mid"].append(index)
        out: dict[str, EvidenceSlice] = {}
        for name, indexes in groups.items():
            evidence = self._slice(
                name,
                tuple(clean.dates[i] for i in indexes),
                tuple(clean.obs[i] for i in indexes),
                tuple(clean.sim[i] for i in indexes),
                self.min_slice_samples,
            )
            notes = evidence.notes + (
                f"low_quantile={self.low_flow_quantile}",
                f"high_quantile={self.high_flow_quantile}",
            )
            out[name] = EvidenceSlice(
                name=evidence.name,
                status=evidence.status,
                sample_count=evidence.sample_count,
                start=evidence.start,
                end=evidence.end,
                metrics=evidence.metrics,
                notes=notes,
            )
        return out

    def _seasons(self, clean: _CleanSeries) -> dict[str, EvidenceSlice]:
        out: dict[str, EvidenceSlice] = {}
        for name, months in self.season_definitions.items():
            indexes = [i for i, day in enumerate(clean.dates) if day.month in months]
            evidence = self._slice(
                name,
                tuple(clean.dates[i] for i in indexes),
                tuple(clean.obs[i] for i in indexes),
                tuple(clean.sim[i] for i in indexes),
                self.min_slice_samples,
            )
            out[name] = EvidenceSlice(
                name=evidence.name,
                status=evidence.status,
                sample_count=evidence.sample_count,
                start=evidence.start,
                end=evidence.end,
                metrics=evidence.metrics,
                notes=evidence.notes + ("months=" + ",".join(str(month) for month in months),),
            )
        return out

    def _years(self, clean: _CleanSeries) -> dict[str, EvidenceSlice]:
        indexes_by_year: dict[int, list[int]] = defaultdict(list)
        for index, day in enumerate(clean.dates):
            indexes_by_year[day.year].append(index)
        return {
            str(year): self._slice(
                str(year),
                tuple(clean.dates[i] for i in indexes),
                tuple(clean.obs[i] for i in indexes),
                tuple(clean.sim[i] for i in indexes),
                self.min_year_samples,
            )
            for year, indexes in sorted(indexes_by_year.items())
        }

    def _fdc(self, clean: _CleanSeries) -> EvidenceSlice:
        count = len(clean.obs)
        if count < self.min_fdc_samples:
            return EvidenceSlice(
                name="fdc",
                status="insufficient_data",
                sample_count=count,
                start=clean.dates[0] if clean.dates else None,
                end=clean.dates[-1] if clean.dates else None,
                notes=(f"requires_at_least={self.min_fdc_samples}",),
            )
        obs = np.asarray(clean.obs, dtype=float)
        sim = np.asarray(clean.sim, dtype=float)
        metrics: dict[str, float] = {}
        squared_errors: list[float] = []
        for exceedance in (0.05, 0.10, 0.50, 0.90, 0.95):
            quantile = 1.0 - exceedance
            obs_q = float(np.quantile(obs, quantile))
            sim_q = float(np.quantile(sim, quantile))
            key = f"exceed_{int(exceedance * 100):02d}"
            metrics[f"{key}_observed"] = obs_q
            metrics[f"{key}_simulated"] = sim_q
            if obs_q != 0:
                metrics[f"{key}_relative_error"] = float((sim_q - obs_q) / obs_q)
            squared_errors.append((sim_q - obs_q) ** 2)
        metrics["fdc_rmse"] = float(math.sqrt(sum(squared_errors) / len(squared_errors)))
        return EvidenceSlice(
            name="fdc",
            status="available",
            sample_count=count,
            start=clean.dates[0],
            end=clean.dates[-1],
            metrics=metrics,
            notes=("exceedance_probabilities=0.05,0.10,0.50,0.90,0.95",),
        )

    def _events(self, clean: _CleanSeries) -> tuple[FloodEventEvidence, ...]:
        if len(clean.obs) < self.min_fdc_samples:
            return ()
        threshold = float(
            np.quantile(np.asarray(clean.obs, dtype=float), self.flood_threshold_quantile)
        )
        groups: list[list[int]] = []
        current: list[int] = []
        for index, (day, value) in enumerate(zip(clean.dates, clean.obs)):
            if value < threshold:
                if current:
                    groups.append(current)
                    current = []
                continue
            if current and (day - clean.dates[current[-1]]).days != 1:
                groups.append(current)
                current = []
            current.append(index)
        if current:
            groups.append(current)

        events: list[FloodEventEvidence] = []
        for number, indexes in enumerate(groups, start=1):
            dates = tuple(clean.dates[i] for i in indexes)
            obs = tuple(clean.obs[i] for i in indexes)
            sim = tuple(clean.sim[i] for i in indexes)
            event_id = f"event-{number:03d}"
            if len(indexes) < self.min_event_samples:
                events.append(
                    FloodEventEvidence(
                        event_id=event_id,
                        status="insufficient_data",
                        start=dates[0],
                        end=dates[-1],
                        sample_count=len(indexes),
                        notes=(
                            f"requires_at_least={self.min_event_samples}",
                            f"threshold={threshold}",
                        ),
                    )
                )
                continue
            metrics, unavailable = self._metric_set(obs, sim)
            events.append(
                FloodEventEvidence(
                    event_id=event_id,
                    status="available",
                    start=dates[0],
                    end=dates[-1],
                    sample_count=len(indexes),
                    metrics=metrics,
                    notes=(
                        f"threshold={threshold}",
                        f"threshold_quantile={self.flood_threshold_quantile}",
                        *(f"metric_unavailable={item}" for item in sorted(set(unavailable))),
                    ),
                )
            )
        return tuple(events)


def compare_evidence(
    baseline: HydrologicEvidenceBundle,
    candidate: HydrologicEvidenceBundle,
    *,
    tolerance: float = 1e-12,
) -> HydrologicEvidenceComparison:
    """Compare common evidence metrics without assuming every metric is higher-is-better.

    The returned ``delta`` is always candidate minus baseline.  ``improved`` and
    ``worsened`` are only assigned for metrics with an unambiguous optimization
    direction; volume/peak ratios and timing lags are intentionally left
    ``unchanged`` here because closeness-to-target, not raw magnitude, determines
    improvement.
    """

    if baseline.window != candidate.window:
        raise ValueError("cannot compare evidence from different windows")
    deltas: list[EvidenceDelta] = []
    improved: list[str] = []
    worsened: list[str] = []
    neutral: list[str] = []
    higher_is_better = {"nse", "kge"}
    lower_is_better = {"mae", "rmse", "fdc_rmse"}

    section_pairs: list[tuple[str, EvidenceSlice, EvidenceSlice]] = [
        ("overall", baseline.overall, candidate.overall),
        ("fdc", baseline.fdc, candidate.fdc),
    ]
    for key in sorted(set(baseline.flow_regimes) & set(candidate.flow_regimes)):
        section_pairs.append(
            (f"flow_regime:{key}", baseline.flow_regimes[key], candidate.flow_regimes[key])
        )
    for key in sorted(set(baseline.seasons) & set(candidate.seasons)):
        section_pairs.append((f"season:{key}", baseline.seasons[key], candidate.seasons[key]))
    for key in sorted(set(baseline.years) & set(candidate.years)):
        section_pairs.append((f"year:{key}", baseline.years[key], candidate.years[key]))

    for section, base_slice, cand_slice in section_pairs:
        if base_slice.status != "available" or cand_slice.status != "available":
            continue
        for metric in sorted(set(base_slice.metrics) & set(cand_slice.metrics)):
            base_value = float(base_slice.metrics[metric])
            candidate_value = float(cand_slice.metrics[metric])
            delta = candidate_value - base_value
            deltas.append(EvidenceDelta(section, metric, base_value, candidate_value, delta))
            label = f"{section}.{metric}"
            if abs(delta) <= tolerance:
                neutral.append(label)
            elif metric in higher_is_better:
                (improved if delta > 0 else worsened).append(label)
            elif metric in lower_is_better:
                (improved if delta < 0 else worsened).append(label)
            else:
                neutral.append(label)
    return HydrologicEvidenceComparison(
        deltas=tuple(deltas),
        improved=tuple(improved),
        worsened=tuple(worsened),
        unchanged=tuple(neutral),
    )
