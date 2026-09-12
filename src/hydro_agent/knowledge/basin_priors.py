"""Derive simple basin priors from data already present in the data bottom board.

Only pre-cutoff observations are used so the profile cannot leak held-out
validation information into calibration planning. V1 intentionally derives
only quantities with direct unit-safe definitions; BFI/snow/climate classes are
left unset until a reviewed method/data source exists.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from hydro_agent.knowledge.expert import BasinHydroProfile


def derive_basin_hydro_profile(
    *,
    forcing_rows: Iterable[object],
    flow_rows: Iterable[object],
    area_km2: float,
    before_date: date | None = None,
) -> BasinHydroProfile:
    if area_km2 <= 0:
        raise ValueError("area_km2 must be positive")

    forcing: dict[date, tuple[float, float]] = {}
    for row in forcing_rows:
        day = getattr(row, "valid_date")
        if before_date is not None and day >= before_date:
            continue
        p = float(getattr(row, "precipitation_mm_day"))
        pet = float(getattr(row, "pet_mm_day"))
        if p >= 0 and pet >= 0:
            forcing[day] = (p, pet)

    flow: dict[date, float] = {}
    for row in flow_rows:
        day = getattr(row, "valid_date")
        if before_date is not None and day >= before_date:
            continue
        q = float(getattr(row, "discharge_m3s"))
        if q >= 0:
            flow[day] = q

    total_p = sum(p for p, _ in forcing.values())
    total_pet = sum(pet for _, pet in forcing.values())
    aridity = total_pet / total_p if total_p > 0 else None

    overlap = sorted(set(forcing).intersection(flow))
    overlap_p = sum(forcing[day][0] for day in overlap)
    # m3/s -> mm/day: Q * 86400 / (area_km2 * 1e6) * 1000
    runoff_mm = sum(flow[day] * 86400.0 / (area_km2 * 1000.0) for day in overlap)
    runoff_ratio = runoff_mm / overlap_p if overlap_p > 0 else None

    return BasinHydroProfile(aridity=aridity, runoff_ratio=runoff_ratio)
