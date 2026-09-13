from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from hydro_agent.evaluation.metrics import high_flow_mae, kge, mae, nse, pbias_percent, rmse


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
        }


class ContinuousSimulationEvidenceService:
    """Build comparable hydrologic evidence from a continuous simulation.

    The service intentionally does not launch XAJ. Execution remains owned by the
    model/runtime layer; this layer makes sure calibration, development and final
    test score an uninterrupted trajectory with the same deterministic metric
    semantics. Later evidence builders (annual/seasonal/event/FDC) should extend
    this service rather than inventing separate scoring paths.
    """

    def evaluate(
        self,
        *,
        window: str,
        dates: Sequence[date],
        observed: Sequence[float],
        simulated: Sequence[float],
        discard_prefix_days: int = 0,
    ) -> ContinuousSimulationEvidence:
        if len(dates) != len(observed) or len(dates) != len(simulated):
            raise ValueError("dates/observed/simulated length mismatch")
        if discard_prefix_days < 0:
            raise ValueError("discard_prefix_days must be non-negative")
        if discard_prefix_days >= len(dates):
            raise ValueError("discard_prefix_days removes the complete series")

        kept_dates = tuple(dates[discard_prefix_days:])
        obs = tuple(float(value) for value in observed[discard_prefix_days:])
        sim = tuple(float(value) for value in simulated[discard_prefix_days:])
        if len(obs) < 2:
            raise ValueError("continuous evidence requires at least two evaluated days")
        if any(later <= earlier for earlier, later in zip(kept_dates, kept_dates[1:])):
            raise ValueError("dates must be strictly increasing")

        obs_peak_i = max(range(len(obs)), key=lambda index: obs[index])
        sim_peak_i = max(range(len(sim)), key=lambda index: sim[index])
        obs_peak = obs[obs_peak_i]
        sim_peak = sim[sim_peak_i]
        peak_ratio = float(sim_peak / obs_peak) if obs_peak else 0.0

        return ContinuousSimulationEvidence(
            window=window,
            start=kept_dates[0],
            end=kept_dates[-1],
            sample_count=len(obs),
            nse=float(nse(obs, sim)),
            kge=float(kge(obs, sim)),
            mae=float(mae(obs, sim)),
            rmse=float(rmse(obs, sim)),
            pbias_percent=float(pbias_percent(obs, sim)),
            high_flow_mae=float(high_flow_mae(obs, sim)),
            peak_ratio=peak_ratio,
            peak_timing_lag_steps=int(sim_peak_i - obs_peak_i),
        )
