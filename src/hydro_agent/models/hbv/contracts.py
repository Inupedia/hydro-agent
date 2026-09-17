"""HBV-light scheme and basin contracts."""

from __future__ import annotations

import math
from datetime import date
from typing import ClassVar, Literal

from pydantic import Field, model_validator

from hydro_agent.execution.contracts import FrozenModel


class HbvScheme(FrozenModel):
    """HBV-light daily snow + soil + groundwater scheme."""

    PARAMETER_ORDER: ClassVar[tuple[str, ...]] = (
        "TT",
        "CFMAX",
        "CFR",
        "CWH",
        "FC",
        "BETA",
        "LP",
        "K0",
        "K1",
        "K2",
        "PERC",
        "MAXBAS",
    )
    model_id: Literal["hbv"] = "hbv"
    warmup_days: int = Field(ge=1)
    parameters: dict[str, float]

    @model_validator(mode="after")
    def validate_parameters(self):
        p = self.parameters
        if set(p) != set(self.PARAMETER_ORDER) or not all(math.isfinite(v) for v in p.values()):
            raise ValueError("exact finite HBV parameter set required")
        if p["CFMAX"] <= 0 or p["FC"] <= 0 or p["BETA"] <= 0 or p["PERC"] < 0:
            raise ValueError("invalid HBV capacity or melt factor")
        if not 0 <= p["CFR"] < 1 or not 0 <= p["CWH"] < 1 or not 0 < p["LP"] <= 1:
            raise ValueError("invalid HBV snow-hold or ET threshold")
        if any(not 0 < p[k] < 1 for k in ("K0", "K1", "K2")):
            raise ValueError("invalid HBV recession coefficients")
        if p["MAXBAS"] < 1:
            raise ValueError("MAXBAS must be at least 1 day")
        return self

    def parameter_vector(self) -> tuple[float, ...]:
        return tuple(self.parameters[k] for k in self.PARAMETER_ORDER)


class HbvBasin(FrozenModel):
    basin_id: str
    area_km2: float = Field(gt=0, allow_inf_nan=False)
    station_id: str | None = None
    day_timezone: str = "UTC"


class HbvForecastRow(FrozenModel):
    lead: Literal[1, 2, 3]
    target_date: date
    value: float = Field(ge=0, allow_inf_nan=False)
