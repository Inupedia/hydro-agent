"""Shared forcing column helpers driven by plugin ``required_forcings``."""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping, Sequence

FORCING_FIELD_BY_NAME: dict[str, str] = {
    "precipitation": "precipitation_mm_day",
    "pet": "pet_mm_day",
    "temperature": "temperature_c",
}
# Bundled basins that ship P+PET only. Used solely when the model requires T.
_BASIN_LATITUDE_FALLBACK: dict[str, float] = {
    "yaogu": 22.9,
}


def basin_latitude_deg(basin: Mapping[str, Any] | None) -> float:
    payload = dict(basin or {})
    for key in ("latitude", "lat", "outlet_lat"):
        raw = payload.get(key)
        if raw not in (None, ""):
            return float(raw)
    basin_id = str(payload.get("basin_id") or "")
    if basin_id in _BASIN_LATITUDE_FALLBACK:
        return _BASIN_LATITUDE_FALLBACK[basin_id]
    return 40.0


def seasonal_temperature_c(day: date, *, latitude: float = 23.0) -> float:
    """Climatological daily mean T when the source has no air temperature.

    Northern-hemisphere sine wave. Guangdong (~23°N) stays above 0 °C so HBV
    snow stays inactive; higher latitudes get a colder mean and larger amplitude.
    """

    mean = 30.0 - 0.35 * abs(float(latitude))
    amplitude = 5.0 + 0.15 * abs(float(latitude))
    doy = int(day.timetuple().tm_yday)
    return mean + amplitude * math.sin(2.0 * math.pi * (doy - 80) / 365.25)


def forcing_csv_columns(required_forcings: Sequence[str] | None = None) -> list[str]:
    names = tuple(required_forcings) if required_forcings else ("precipitation", "pet")
    columns = ["date"]
    for name in names:
        key = FORCING_FIELD_BY_NAME.get(name)
        if key is None:
            raise KeyError(f"unsupported forcing name: {name}")
        columns.append(key)
    return columns


def row_forcing_values(row: Any, required_forcings: Sequence[str]) -> list[float]:
    values: list[float] = []
    for name in required_forcings:
        field = FORCING_FIELD_BY_NAME[name]
        raw = getattr(row, field, None)
        if raw is None and isinstance(row, dict):
            raw = row.get(field)
        if raw is None:
            raise ValueError(f"forcing missing required field: {field}")
        values.append(float(raw))
    return values


def load_forcing_matrix(
    rows: Sequence[dict[str, str]],
    *,
    required_forcings: Sequence[str],
):
    """Return ``(n_days, 1, n_forcings)`` array ordered by ``required_forcings``."""

    import numpy as np

    matrix = []
    for row in rows:
        values = []
        for name in required_forcings:
            field = FORCING_FIELD_BY_NAME[name]
            if field not in row or row[field] in ("", None):
                raise ValueError(f"forcing csv missing required column: {field}")
            values.append(float(row[field]))
        matrix.append(values)
    array = np.asarray(matrix, dtype=float)
    if array.ndim != 2:
        raise ValueError("forcing matrix must be 2-d")
    if not np.isfinite(array).all():
        raise ValueError("forcing must be finite")
    # Precipitation and PET must be nonnegative; temperature may be negative.
    for index, name in enumerate(required_forcings):
        if name != "temperature" and (array[:, index] < 0).any():
            raise ValueError(f"forcing {name} must be nonnegative")
    return array[:, None, :]
