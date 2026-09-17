"""Simplified SAC-SMA scheme and basin contracts."""

from __future__ import annotations

import math
from datetime import date
from typing import ClassVar, Literal

from pydantic import Field, model_validator

from hydro_agent.execution.contracts import FrozenModel


class SacSmaScheme(FrozenModel):
    """Simplified Sacramento Soil Moisture Accounting daily scheme."""

    PARAMETER_ORDER: ClassVar[tuple[str, ...]] = (
        "UZTWM",
        "UZFWM",
        "UZK",
        "PCTIM",
        "LZTWM",
        "LZFSM",
        "LZFPM",
        "LZSK",
        "LZPK",
        "ZPERC",
        "REXP",
        "UHK",
    )
    model_id: Literal["sac-sma"] = "sac-sma"
    warmup_days: int = Field(ge=1)
    parameters: dict[str, float]

    @model_validator(mode="after")
    def validate_parameters(self):
        p = self.parameters
        if set(p) != set(self.PARAMETER_ORDER) or not all(math.isfinite(v) for v in p.values()):
            raise ValueError("exact finite SAC-SMA parameter set required")
        if any(p[k] <= 0 for k in ("UZTWM", "UZFWM", "LZTWM", "LZFSM", "LZFPM", "ZPERC", "REXP")):
            raise ValueError("SAC-SMA capacities and percolation terms must be positive")
        if any(not 0 < p[k] < 1 for k in ("UZK", "LZSK", "LZPK")):
            raise ValueError("invalid SAC-SMA recession coefficients")
        if not 0 <= p["PCTIM"] < 1:
            raise ValueError("impervious fraction must lie in [0, 1)")
        if p["UHK"] < 1:
            raise ValueError("unit-hydrograph base must be at least 1 day")
        return self

    def parameter_vector(self) -> tuple[float, ...]:
        return tuple(self.parameters[k] for k in self.PARAMETER_ORDER)


class SacSmaBasin(FrozenModel):
    basin_id: str
    area_km2: float = Field(gt=0, allow_inf_nan=False)
    station_id: str | None = None
    day_timezone: str = "UTC"


class SacSmaForecastRow(FrozenModel):
    lead: Literal[1, 2, 3]
    target_date: date
    value: float = Field(ge=0, allow_inf_nan=False)
