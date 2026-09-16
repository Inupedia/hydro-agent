"""GR4J scheme and basin contracts (Perrin et al., 2003)."""

from __future__ import annotations

import math
from datetime import date
from typing import ClassVar, Literal

from pydantic import Field, model_validator

from hydro_agent.execution.contracts import FrozenModel


class Gr4jScheme(FrozenModel):
    """Four-parameter GR4J daily rainfall-runoff scheme."""

    PARAMETER_ORDER: ClassVar[tuple[str, ...]] = ("X1", "X2", "X3", "X4")
    model_id: Literal["gr4j"] = "gr4j"
    warmup_days: int = Field(ge=1)
    parameters: dict[str, float]

    @model_validator(mode="after")
    def validate_parameters(self):
        p = self.parameters
        if set(p) != set(self.PARAMETER_ORDER) or not all(math.isfinite(v) for v in p.values()):
            raise ValueError("exact finite GR4J parameter set required")
        if p["X1"] <= 0 or p["X3"] <= 0 or p["X4"] < 0.5:
            raise ValueError("invalid GR4J capacity or UH time base")
        return self

    def parameter_vector(self) -> tuple[float, ...]:
        return tuple(self.parameters[k] for k in self.PARAMETER_ORDER)


class Gr4jBasin(FrozenModel):
    basin_id: str
    area_km2: float = Field(gt=0, allow_inf_nan=False)
    station_id: str | None = None
    day_timezone: str = "UTC"


class Gr4jForecastRow(FrozenModel):
    lead: Literal[1, 2, 3]
    target_date: date
    value: float = Field(ge=0, allow_inf_nan=False)
