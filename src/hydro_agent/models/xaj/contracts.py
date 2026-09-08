import math
from datetime import date
from typing import ClassVar, Literal

from pydantic import Field, model_validator

from hydro_agent.execution.contracts import FrozenModel

UPSTREAM_COMMIT = "89d7a8ed1d72ce4fffbbd9897490b089382ecbac"


class XajScheme(FrozenModel):
    PARAMETER_ORDER: ClassVar[tuple[str, ...]] = (
        "K",
        "B",
        "IM",
        "UM",
        "LM",
        "DM",
        "C",
        "SM",
        "EX",
        "KI",
        "KG",
        "CS",
        "L",
        "CI",
        "CG",
    )
    model_id: Literal["xaj"] = "xaj"
    warmup_days: int = Field(ge=1)
    parameters: dict[str, float]

    @model_validator(mode="after")
    def validate_parameters(self):
        p = self.parameters
        if set(p) != set(self.PARAMETER_ORDER) or not all(math.isfinite(v) for v in p.values()):
            raise ValueError("exact finite XAJ parameter set required")
        if any(p[k] <= 0 for k in ("K", "B", "UM", "LM", "DM", "SM", "EX")):
            raise ValueError("capacities and exponents must be positive")
        if (
            any(not 0 <= p[k] < 1 for k in ("IM", "C", "KI", "KG", "CS", "CI", "CG"))
            or not 0 < p["KI"] + p["KG"] < 1
        ):
            raise ValueError("invalid XAJ partition or recession coefficients")
        if p["L"] < 0 or not p["L"].is_integer():
            raise ValueError("daily routing lag must be a nonnegative integer")
        return self

    def parameter_vector(self):
        return tuple(self.parameters[k] for k in self.PARAMETER_ORDER)


class XajBasin(FrozenModel):
    basin_id: str
    area_km2: float = Field(gt=0, allow_inf_nan=False)
    station_id: str | None = None
    day_timezone: str = "UTC"


class XajForecastRow(FrozenModel):
    lead: Literal[1, 2, 3]
    target_date: date
    value: float = Field(ge=0, allow_inf_nan=False)
