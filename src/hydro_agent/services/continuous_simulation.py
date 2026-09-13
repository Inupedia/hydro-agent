from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from hydro_agent.evaluation.evidence import HydrologicEvidenceBuilder


@dataclass(frozen=True)
class ContinuousSimulationEvidence:
    """Deterministic evidence derived from one uninterrupted model trajectory."""

    window: str
    start: date
    end: date
    sample_count: int
    nse: float
    kge: float
    mae: float
    rmse: float
    pbias_percent: float
    high_flow_mae: float
    peak_ratio: float
    peak_timing_lag_steps: int
    input_count: int = 0
    dropped_count: int = 0
    coverage: float = 1.0
    dropped_by_reason: dict[str, int] = field(default_factory=dict)

    def as_metrics(self) -> dict[str, float]:
        return {
            "nse": self.nse,
            "kge": self.kge,
            "mae": self.mae,
            "rmse": self.rmse,
            "pbias_percent": self.pbias_percent,
            "high_flow_mae": self.high_flow_mae,
            "peak_ratio": self.peak_ratio,
            "peak_timing_lag_steps": float(self.peak_timing_lag_steps),
            "sample_count": float(self.sample_count),
            "input_count": float(self.input_count),
            "dropped_count": float(self.dropped_count),
            "coverage": float(self.coverage),
        }


class ContinuousSimulationEvidenceService:
    """Build comparable hydrologic evidence from a continuous simulation.

    Execution remains owned by the model/runtime layer.  This scorer shares the
    same data-quality semantics as :class:`HydrologicEvidenceBuilder`: explicit
    masks, missing/non-finite observations and negative observed discharge are
    audited and removed, while finite negative *simulated* discharge remains in
    the score as evidence of model failure.
    """

    def evaluate(
        self,
        *,
        window: str,
        dates: Sequence[date],
        observed: Sequence[float | None],
        simulated: Sequence[float | None],
        discard_prefix_days: int = 0,
        quality_mask: Sequence[bool] | None = None,
    ) -> ContinuousSimulationEvidence:
        if len(dates) != len(observed) or len(dates) != len(simulated):
            raise ValueError("dates/observed/simulated length mismatch")
        if quality_mask is not None and len(quality_mask) != len(dates):
            raise ValueError("quality_mask length mismatch")
        if discard_prefix_days < 0:
            raise ValueError("discard_prefix_days must be non-negative")
        if discard_prefix_days >= len(dates):
            raise ValueError("discard_prefix_days removes the complete series")

        kept_dates = tuple(dates[discard_prefix_days:])
        kept_observed = tuple(observed[discard_prefix_days:])
        kept_simulated = tuple(simulated[discard_prefix_days:])
        kept_mask = (
            tuple(quality_mask[discard_prefix_days:]) if quality_mask is not None else None
        )

        # Use the shared evidence builder as the single data-quality authority.
        # Low minimums are intentional here because the continuous scorer still
        # supports the 3-day smoke final_test; richer annual/FDC conclusions are
        # produced separately by the research Evidence Builder.
        bundle = HydrologicEvidenceBuilder(
            min_overall_samples=2,
            min_slice_samples=2,
            min_year_samples=2,
            min_fdc_samples=2,
            min_event_samples=1,
        ).build(
            window=window,
            dates=kept_dates,
            observed=kept_observed,
            simulated=kept_simulated,
            quality_mask=kept_mask,
        )
        overall = bundle.overall
        if overall.status != "available" or overall.start is None or overall.end is None:
            raise ValueError("continuous evidence requires at least two valid evaluated days")
        required = {
            "nse",
            "kge",
            "mae",
            "rmse",
            "pbias_percent",
            "peak_ratio",
            "peak_timing_lag_steps",
        }
        missing = sorted(required - set(overall.metrics))
        if missing:
            raise ValueError("continuous evidence metrics unavailable: " + ",".join(missing))

        # Preserve the historical high-flow MAE definition (90th observed
        # percentile) for API compatibility while using the cleaned series.
        # The overall slice does not expose raw arrays, so rebuild the valid
        # values using the same audited rules through a small high-flow slice.
        valid_rows: list[tuple[float, float]] = []
        for index, (obs_raw, sim_raw) in enumerate(zip(kept_observed, kept_simulated)):
            if kept_mask is not None and not kept_mask[index]:
                continue
            try:
                obs = float(obs_raw)  # type: ignore[arg-type]
                sim = float(sim_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if not __import__("math").isfinite(obs) or obs < 0 or not __import__("math").isfinite(sim):
                continue
            valid_rows.append((obs, sim))
        obs_values = [row[0] for row in valid_rows]
        sim_values = [row[1] for row in valid_rows]
        import numpy as np

        threshold = float(np.quantile(np.asarray(obs_values, dtype=float), 0.9))
        high_errors = [
            abs(obs - sim) for obs, sim in zip(obs_values, sim_values) if obs >= threshold
        ]
        high_flow_mae = float(sum(high_errors) / len(high_errors))

        quality = bundle.quality
        return ContinuousSimulationEvidence(
            window=window,
            start=overall.start,
            end=overall.end,
            sample_count=overall.sample_count,
            nse=float(overall.metrics["nse"]),
            kge=float(overall.metrics["kge"]),
            mae=float(overall.metrics["mae"]),
            rmse=float(overall.metrics["rmse"]),
            pbias_percent=float(overall.metrics["pbias_percent"]),
            high_flow_mae=high_flow_mae,
            peak_ratio=float(overall.metrics["peak_ratio"]),
            peak_timing_lag_steps=int(overall.metrics["peak_timing_lag_steps"]),
            input_count=quality.total_count,
            dropped_count=quality.dropped_count,
            coverage=quality.coverage,
            dropped_by_reason=dict(quality.dropped_by_reason),
        )
