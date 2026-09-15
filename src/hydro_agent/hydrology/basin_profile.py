"""Deterministic, leakage-safe basin profile derived from observed data."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from hydro_agent.execution.contracts import FrozenModel


class BasinHydroProfile(FrozenModel):
    aridity: float | None = None
    runoff_ratio: float | None = None
    baseflow_index: float | None = None
    frac_snow: float | None = None
    climate_zone: str | None = None

    @property
    def available(self) -> bool:
        return any(value is not None for value in self.model_dump().values())


def derive_basin_hydro_profile(
    *,
    forcing_rows: Iterable[object],
    flow_rows: Iterable[object],
    area_km2: float,
    before_date: date | None = None,
    evaporation_is_potential: bool = True,
) -> BasinHydroProfile:
    if area_km2 <= 0:
        raise ValueError("area_km2 must be positive")

    forcing: dict[date, tuple[float, float]] = {}
    for row in forcing_rows:
        day = getattr(row, "valid_date")
        if before_date is not None and day >= before_date:
            continue
        p = float(getattr(row, "precipitation_mm_day"))
        evap = float(getattr(row, "pet_mm_day"))
        if p >= 0 and evap >= 0:
            forcing[day] = (p, evap)

    flow: dict[date, float] = {}
    for row in flow_rows:
        day = getattr(row, "valid_date")
        if before_date is not None and day >= before_date:
            continue
        q = float(getattr(row, "discharge_m3s"))
        if q >= 0:
            flow[day] = q

    total_p = sum(p for p, _ in forcing.values())
    total_evap = sum(evap for _, evap in forcing.values())
    aridity = total_evap / total_p if evaporation_is_potential and total_p > 0 else None

    overlap = sorted(set(forcing).intersection(flow))
    overlap_p = sum(forcing[day][0] for day in overlap)
    runoff_mm = sum(flow[day] * 86400.0 / (area_km2 * 1000.0) for day in overlap)
    runoff_ratio = runoff_mm / overlap_p if overlap_p > 0 else None
    return BasinHydroProfile(aridity=aridity, runoff_ratio=runoff_ratio)
