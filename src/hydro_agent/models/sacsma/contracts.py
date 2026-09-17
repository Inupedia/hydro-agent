"""NOAA-OWP SAC-SMA scheme and basin contracts (16 parameters + 6 states)."""

from __future__ import annotations

import math
from datetime import date
from typing import ClassVar, Literal

from pydantic import Field, model_validator

from hydro_agent.execution.contracts import FrozenModel


class SacSmaScheme(FrozenModel):
    """NOAA-OWP SAC-SMA scheme: the official 16-parameter soil-moisture core.

    The 16 parameters mirror the NOAA-OWP ``sac-sma`` public interface
    (PCTIM, ADIMP, RIVA, ZPERC, REXP, PFREE, SIDE, RSERV included).  ``HOURS``
    is a separate routing-only parameter (triangular unit-hydrograph base); it
    is not part of the official SAC-SMA parameter set.
    """

    PARAMETER_ORDER: ClassVar[tuple[str, ...]] = (
        "UZTWM",
        "UZFWM",
        "UZK",
        "PCTIM",
        "ADIMP",
        "RIVA",
        "ZPERC",
        "REXP",
        "LZTWM",
        "LZFSM",
        "LZFPM",
        "LZSK",
        "LZPK",
        "PFREE",
        "SIDE",
        "RSERV",
    )
    STATE_ORDER: ClassVar[tuple[str, ...]] = (
        "UZTWC",
        "UZFWC",
        "LZTWC",
        "LZFSC",
        "LZFPC",
        "ADIMC",
    )
    model_id: Literal["sac-sma"] = "sac-sma"
    warmup_days: int = Field(ge=1)
    routing: dict[str, float] = Field(default_factory=lambda: {"HOURS": 4.0})
    parameters: dict[str, float]

    @model_validator(mode="after")
    def validate_parameters(self):
        p = self.parameters
        if set(p) != set(self.PARAMETER_ORDER) or not all(math.isfinite(v) for v in p.values()):
            raise ValueError("exact finite SAC-SMA parameter set required (16 params)")
        if any(p[k] <= 0 for k in ("UZTWM", "UZFWM", "LZTWM", "LZFSM", "LZFPM", "ZPERC")):
            raise ValueError("SAC-SMA capacities and percolation coefficient must be positive")
        if p["REXP"] < 0:
            raise ValueError("SAC-SMA percolation exponent must be non-negative")
        if any(
            not 0.0 <= p[k] <= 1.0
            for k in ("UZK", "LZSK", "LZPK", "PCTIM", "ADIMP", "RIVA", "PFREE", "SIDE", "RSERV")
        ):
            raise ValueError("SAC-SMA fractions and recession coefficients must lie in [0, 1]")
        if p["PCTIM"] + p["ADIMP"] >= 1.0:
            raise ValueError("PCTIM + ADIMP must be strictly less than 1")
        routing = self.routing
        if set(routing) != {"HOURS"} or not math.isfinite(float(routing["HOURS"])):
            raise ValueError("exact finite SAC-SMA routing parameter required (HOURS)")
        if float(routing["HOURS"]) < 0:
            raise ValueError("routing HOURS must be non-negative")
        return self

    def parameter_vector(self) -> tuple[float, ...]:
        return tuple(self.parameters[k] for k in self.PARAMETER_ORDER)

    def all_parameter_vector(self) -> tuple[float, ...]:
        return self.parameter_vector() + (float(self.routing["HOURS"]),)

    def state_vector(self, values: dict[str, float] | None = None) -> tuple[float, ...]:
        if values is None:
            values = initial_state_from_parameters(self.parameters)
        return tuple(float(values[k]) for k in self.STATE_ORDER)


class SacSmaBasin(FrozenModel):
    basin_id: str
    area_km2: float = Field(gt=0, allow_inf_nan=False)
    station_id: str | None = None
    day_timezone: str = "UTC"


class SacSmaForecastRow(FrozenModel):
    lead: Literal[1, 2, 3]
    target_date: date
    value: float = Field(ge=0, allow_inf_nan=False)


def initial_state_from_parameters(p: dict[str, float]) -> dict[str, float]:
    """NOAA-OWP cold-start initial state: all six storage contents zero."""
    return {
        "UZTWC": 0.0,
        "UZFWC": 0.0,
        "LZTWC": 0.0,
        "LZFSC": 0.0,
        "LZFPC": 0.0,
        "ADIMC": 0.0,
    }
