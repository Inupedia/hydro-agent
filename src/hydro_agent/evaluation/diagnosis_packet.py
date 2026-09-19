from __future__ import annotations

from typing import Any

from pydantic import Field

from hydro_agent.evaluation.evidence import (
    EvidenceSlice,
    FloodEventEvidence,
    HydrologicEvidenceBundle,
)
from hydro_agent.execution.contracts import FrozenModel


class EvidenceSliceView(FrozenModel):
    status: str
    sample_count: int
    metrics: dict[str, float] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()


class FloodEventDiagnosticView(EvidenceSliceView):
    event_id: str
    start: str
    end: str
    basis: str
    rain_start: str | None = None
    rain_end: str | None = None


class DataQualityView(FrozenModel):
    total_count: int
    valid_count: int
    dropped_count: int
    coverage: float
    dropped_by_reason: dict[str, int] = Field(default_factory=dict)


class HydrographDiagnosisPacket(FrozenModel):
    window: str
    overall: EvidenceSliceView
    water_balance: EvidenceSliceView
    flow_regimes: dict[str, EvidenceSliceView]
    fdc: EvidenceSliceView
    seasons: dict[str, EvidenceSliceView]
    years: dict[str, EvidenceSliceView]
    flood_events: tuple[FloodEventDiagnosticView, ...]
    data_quality: DataQualityView
    basin_attributes: dict[str, Any] = Field(default_factory=dict)


def _slice_view(item: EvidenceSlice) -> EvidenceSliceView:
    return EvidenceSliceView(
        status=item.status,
        sample_count=item.sample_count,
        metrics=dict(item.metrics),
        notes=tuple(item.notes),
    )


def _event_view(item: FloodEventEvidence) -> FloodEventDiagnosticView:
    return FloodEventDiagnosticView(
        event_id=item.event_id,
        start=item.start.isoformat(),
        end=item.end.isoformat(),
        basis=item.basis,
        rain_start=item.rain_start.isoformat() if item.rain_start else None,
        rain_end=item.rain_end.isoformat() if item.rain_end else None,
        status=item.status,
        sample_count=item.sample_count,
        metrics=dict(item.metrics),
        notes=tuple(item.notes),
    )


def _water_balance_view(overall: EvidenceSlice) -> EvidenceSliceView:
    water_keys = {
        "pbias_percent",
        "volume_observed",
        "volume_simulated",
        "volume_ratio",
        "volume_relative_error",
    }
    metrics = {
        key: float(value)
        for key, value in overall.metrics.items()
        if key in water_keys
    }
    return EvidenceSliceView(
        status=overall.status,
        sample_count=overall.sample_count,
        metrics=metrics,
        notes=tuple(overall.notes),
    )


def build_diagnosis_packet(
    bundle: HydrologicEvidenceBundle,
    *,
    basin_attributes: dict[str, Any] | None = None,
) -> HydrographDiagnosisPacket:
    return HydrographDiagnosisPacket(
        window=bundle.window,
        overall=_slice_view(bundle.overall),
        water_balance=_water_balance_view(bundle.overall),
        flow_regimes={key: _slice_view(value) for key, value in bundle.flow_regimes.items()},
        fdc=_slice_view(bundle.fdc),
        seasons={key: _slice_view(value) for key, value in bundle.seasons.items()},
        years={key: _slice_view(value) for key, value in bundle.years.items()},
        flood_events=tuple(_event_view(item) for item in bundle.flood_events),
        data_quality=DataQualityView(
            total_count=bundle.quality.total_count,
            valid_count=bundle.quality.valid_count,
            dropped_count=bundle.quality.dropped_count,
            coverage=bundle.quality.coverage,
            dropped_by_reason=dict(bundle.quality.dropped_by_reason),
        ),
        basin_attributes=dict(basin_attributes or {}),
    )
