"""Deterministic basin spatial evidence summaries.

This module consumes already prepared arrays/tables from trusted adapters. It does
not download, geocode, delineate, or infer missing spatial data.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Literal

import numpy as np
from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel


class NumericSpatialSummary(FrozenModel):
    status: Literal["available", "unknown"]
    count: int = 0
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    std: float | None = None
    cv: float | None = None
    q25: float | None = None
    q50: float | None = None
    q75: float | None = None

    @property
    def mean_m(self) -> float | None:
        """Compatibility/readability alias for elevation-focused callers."""
        return self.mean


class CategoricalSpatialSummary(FrozenModel):
    status: Literal["available", "unknown"]
    fractions: dict[str, float] = Field(default_factory=dict)
    dominant_class: str | None = None


class DrainageSpatialSummary(FrozenModel):
    status: Literal["available", "unknown"]
    area_km2: float | None = None
    stream_density_km_per_km2: float | None = None
    main_channel_length_km: float | None = None


class BasinSpatialProfile(FrozenModel):
    elevation: NumericSpatialSummary
    slope: NumericSpatialSummary
    precipitation: NumericSpatialSummary
    land_cover: CategoricalSpatialSummary
    soil: CategoricalSpatialSummary
    drainage: DrainageSpatialSummary
    evidence_quality: tuple[str, ...] = ()


def _numeric_summary(
    values: Iterable[float | int | None] | None,
    *,
    field_name: str,
    reject_negative: bool = False,
) -> tuple[NumericSpatialSummary, tuple[str, ...]]:
    if values is None:
        return NumericSpatialSummary(status="unknown"), ()

    finite: list[float] = []
    dropped = 0
    for raw in values:
        if raw is None:
            dropped += 1
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            dropped += 1
            continue
        if not math.isfinite(value):
            dropped += 1
            continue
        if reject_negative and value < 0:
            raise ValueError(f"{field_name} cannot contain negative values")
        finite.append(value)

    notes: list[str] = []
    if dropped:
        notes.append(f"{field_name}:dropped_missing_or_nonfinite={dropped}")
    if not finite:
        return NumericSpatialSummary(status="unknown"), tuple(notes)

    array = np.asarray(sorted(finite), dtype=float)
    mean = float(np.mean(array))
    std = float(np.std(array, ddof=0))
    quantiles = np.quantile(array, [0.25, 0.50, 0.75], method="linear")
    return (
        NumericSpatialSummary(
            status="available",
            count=int(array.size),
            minimum=float(array[0]),
            maximum=float(array[-1]),
            mean=mean,
            std=std,
            cv=(std / mean if mean > 0 else None),
            q25=float(quantiles[0]),
            q50=float(quantiles[1]),
            q75=float(quantiles[2]),
        ),
        tuple(notes),
    )


def _categorical_summary(
    values: Mapping[str, float | int] | None,
    *,
    field_name: str,
) -> tuple[CategoricalSpatialSummary, tuple[str, ...]]:
    if not values:
        return CategoricalSpatialSummary(status="unknown"), ()

    cleaned: dict[str, float] = {}
    for raw_name, raw_fraction in values.items():
        name = str(raw_name).strip()
        if not name:
            raise ValueError(f"{field_name} contains an empty category")
        value = float(raw_fraction)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{field_name} fractions must be finite and non-negative")
        if value > 0:
            cleaned[name] = cleaned.get(name, 0.0) + value

    if not cleaned:
        return CategoricalSpatialSummary(status="unknown"), ()

    total = float(sum(cleaned.values()))
    if total <= 0:
        return CategoricalSpatialSummary(status="unknown"), ()

    notes: list[str] = []
    if not math.isclose(total, 1.0, rel_tol=1e-6, abs_tol=1e-6):
        cleaned = {name: value / total for name, value in cleaned.items()}
        notes.append(f"{field_name}:fractions_normalized")

    fractions = {name: float(cleaned[name]) for name in sorted(cleaned)}
    dominant = min(fractions, key=lambda name: (-fractions[name], name))
    return (
        CategoricalSpatialSummary(
            status="available",
            fractions=fractions,
            dominant_class=dominant,
        ),
        tuple(notes),
    )


def _optional_nonnegative(payload: Mapping[str, object], key: str) -> float | None:
    raw = payload.get(key)
    if raw is None:
        return None
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"drainage.{key} must be finite and non-negative")
    return value


def _drainage_summary(
    drainage: Mapping[str, object] | None,
) -> tuple[DrainageSpatialSummary, tuple[str, ...]]:
    if not drainage:
        return DrainageSpatialSummary(status="unknown"), ()

    area = _optional_nonnegative(drainage, "area_km2")
    stream_length = _optional_nonnegative(drainage, "stream_length_km")
    main_channel = _optional_nonnegative(drainage, "main_channel_length_km")
    if area is not None and area <= 0:
        raise ValueError("drainage.area_km2 must be positive")

    density = None
    if area is not None and stream_length is not None:
        density = stream_length / area

    if area is None and stream_length is None and main_channel is None:
        return DrainageSpatialSummary(status="unknown"), ()

    notes: list[str] = []
    if stream_length is not None and area is None:
        notes.append("drainage:stream_density_unknown_without_area")
    return (
        DrainageSpatialSummary(
            status="available",
            area_km2=area,
            stream_density_km_per_km2=density,
            main_channel_length_km=main_channel,
        ),
        tuple(notes),
    )


def derive_basin_spatial_profile(
    *,
    elevation_m: Iterable[float | int | None] | None = None,
    slope_deg: Iterable[float | int | None] | None = None,
    precipitation_mm: Iterable[float | int | None] | None = None,
    land_cover: Mapping[str, float | int] | None = None,
    soil: Mapping[str, float | int] | None = None,
    drainage: Mapping[str, object] | None = None,
) -> BasinSpatialProfile:
    """Derive source-aware deterministic spatial evidence.

    Missing dimensions stay unknown. No overall heterogeneity score or unit
    recommendation is produced here.
    """
    elevation, elevation_notes = _numeric_summary(elevation_m, field_name="elevation")
    slope, slope_notes = _numeric_summary(slope_deg, field_name="slope")
    precipitation, precipitation_notes = _numeric_summary(
        precipitation_mm,
        field_name="precipitation",
        reject_negative=True,
    )
    land_cover_summary, land_cover_notes = _categorical_summary(
        land_cover,
        field_name="land_cover",
    )
    soil_summary, soil_notes = _categorical_summary(soil, field_name="soil")
    drainage_summary, drainage_notes = _drainage_summary(drainage)

    quality = tuple(
        dict.fromkeys(
            (
                *elevation_notes,
                *slope_notes,
                *precipitation_notes,
                *land_cover_notes,
                *soil_notes,
                *drainage_notes,
            )
        )
    )
    return BasinSpatialProfile(
        elevation=elevation,
        slope=slope,
        precipitation=precipitation,
        land_cover=land_cover_summary,
        soil=soil_summary,
        drainage=drainage_summary,
        evidence_quality=quality,
    )
