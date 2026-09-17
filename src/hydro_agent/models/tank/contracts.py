"""Classic multi-tank scheme and basin contracts."""

from __future__ import annotations

import math
from datetime import date
from typing import ClassVar, Literal

from pydantic import Field, model_validator

from hydro_agent.execution.contracts import FrozenModel


class TankScheme(FrozenModel):
    """Sugawara-style daily multi-tank rainfall-runoff scheme."""

    PARAMETER_ORDER: ClassVar[tuple[str, ...]] = (
        "H1",
        "A11",
        "A12",
        "B1",
        "H2",
        "A2",
        "B2",
        "A3",
        "K",
        "N",
    )
    model_id: Literal["tank"] = "tank"
    warmup_days: int = Field(ge=1)
    parameters: dict[str, float]

    @model_validator(mode="after")
    def validate_parameters(self):
        p = self.parameters
        if set(p) != set(self.PARAMETER_ORDER) or not all(math.isfinite(v) for v in p.values()):
            raise ValueError("exact finite tank parameter set required")
        if p["H1"] < 0 or p["H2"] < 0:
            raise ValueError("tank outlet heights must be nonnegative")
        if any(p[k] <= 0 or p[k] >= 1 for k in ("A11", "A12", "B1", "A2", "B2", "A3", "K")):
            raise ValueError("tank coefficients must lie in (0, 1)")
        if p["N"] < 1:
            raise ValueError("Nash cascade length must be at least 1")
        return self

    def parameter_vector(self) -> tuple[float, ...]:
        return tuple(self.parameters[k] for k in self.PARAMETER_ORDER)


class TankBasin(FrozenModel):
    basin_id: str
    area_km2: float = Field(gt=0, allow_inf_nan=False)
    station_id: str | None = None
    day_timezone: str = "UTC"


class TankForecastRow(FrozenModel):
    lead: Literal[1, 2, 3]
    target_date: date
    value: float = Field(ge=0, allow_inf_nan=False)
