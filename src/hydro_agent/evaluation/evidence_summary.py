"""Cross-slice summaries for hydrologic research evidence."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from hydro_agent.evaluation.evidence import (
    EvidenceDelta,
    EvidenceSlice,
    HydrologicEvidenceBundle,
)


@dataclass(frozen=True)
class EventEvidenceComparison:
    deltas: tuple[EvidenceDelta, ...]
    improved: tuple[str, ...]
    worsened: tuple[str, ...]
    unchanged: tuple[str, ...]


def annual_stability_evidence(
    bundle: HydrologicEvidenceBundle,
    *,
    minimum_years: int = 2,
) -> EvidenceSlice:
    """Summarize interannual skill only when multiple supported years exist."""

    available = [item for _, item in sorted(bundle.years.items()) if item.status == "available"]
    if len(available) < minimum_years:
        return EvidenceSlice(
            name="annual_stability",
            status="insufficient_data",
            sample_count=len(available),
            notes=(f"requires_at_least_years={minimum_years}",),
        )

    metrics: dict[str, float] = {}
    for metric in ("nse", "kge", "pbias_percent", "mae", "rmse"):
        values = [float(item.metrics[metric]) for item in available if metric in item.metrics]
        if len(values) < minimum_years:
            continue
        metrics[f"{metric}_mean"] = float(statistics.fmean(values))
        metrics[f"{metric}_median"] = float(statistics.median(values))
        metrics[f"{metric}_stdev"] = float(statistics.stdev(values))
        metrics[f"{metric}_min"] = float(min(values))
        metrics[f"{metric}_max"] = float(max(values))
    if not metrics:
        return EvidenceSlice(
            name="annual_stability",
            status="insufficient_data",
            sample_count=len(available),
            notes=("no_common_annual_metrics",),
        )
    starts = [item.start for item in available if item.start is not None]
    ends = [item.end for item in available if item.end is not None]
    return EvidenceSlice(
        name="annual_stability",
        status="available",
        sample_count=len(available),
        start=min(starts) if starts else None,
        end=max(ends) if ends else None,
        metrics=metrics,
        notes=("sample_count_is_year_count",),
    )


def compare_flood_events(
    baseline: HydrologicEvidenceBundle,
    candidate: HydrologicEvidenceBundle,
    *,
    tolerance: float = 1e-12,
) -> EventEvidenceComparison:
    """Compare like-for-like observed-threshold events between two simulations."""

    if baseline.window != candidate.window:
        raise ValueError("cannot compare event evidence from different windows")
    base = {item.event_id: item for item in baseline.flood_events}
    cand = {item.event_id: item for item in candidate.flood_events}
    deltas: list[EvidenceDelta] = []
    improved: list[str] = []
    worsened: list[str] = []
    unchanged: list[str] = []
    higher_is_better = {"nse", "kge"}
    lower_is_better = {"mae", "rmse"}

    for event_id in sorted(set(base) & set(cand)):
        left = base[event_id]
        right = cand[event_id]
        if left.status != "available" or right.status != "available":
            continue
        if left.start != right.start or left.end != right.end:
            raise ValueError(f"event boundaries differ for {event_id}")
        for metric in sorted(set(left.metrics) & set(right.metrics)):
            before = float(left.metrics[metric])
            after = float(right.metrics[metric])
            delta = after - before
            section = f"flood_event:{event_id}"
            deltas.append(EvidenceDelta(section, metric, before, after, delta))
            label = f"{section}.{metric}"
            if abs(delta) <= tolerance:
                unchanged.append(label)
            elif metric in higher_is_better:
                (improved if delta > 0 else worsened).append(label)
            elif metric in lower_is_better:
                (improved if delta < 0 else worsened).append(label)
            else:
                # Ratios, volume and timing require target-distance semantics.
                unchanged.append(label)
    return EventEvidenceComparison(
        deltas=tuple(deltas),
        improved=tuple(improved),
        worsened=tuple(worsened),
        unchanged=tuple(unchanged),
    )
