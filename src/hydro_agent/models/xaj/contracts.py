import math
from datetime import date
from typing import ClassVar, Literal

from pydantic import Field, model_validator

from hydro_agent.execution.contracts import FrozenModel


class XajRouting(FrozenModel):
    # Per-unit native hillslope routing. Reach-network routing is a future layer.
    dp: int = Field(default=0, ge=0, lt=50)
    ke: float = Field(default=24.0, gt=0, allow_inf_nan=False)
    xe: float = Field(default=0.2, ge=0, le=0.5)

    @model_validator(mode="after")
    def stable_daily_routing(self):
        if self.dp and not 2 * self.ke * self.xe <= 24 <= 2 * self.ke * (1 - self.xe):
            raise ValueError("unstable daily Muskingum coefficients")
        return self


class XajUnit(FrozenModel):
    """One spatial rainfall-runoff unit in a distributed XAJ scheme."""

    unit_id: int = Field(ge=1)
    area_km2: float = Field(gt=0, allow_inf_nan=False)
    centroid_lon: float | None = Field(default=None, ge=-180, le=180)
    centroid_lat: float | None = Field(default=None, ge=-90, le=90)


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
    routing: XajRouting = Field(default_factory=XajRouting)
    parameters: dict[str, float]
    units: tuple[XajUnit, ...] = ()

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
        if self.units:
            ids = [unit.unit_id for unit in self.units]
            if len(ids) != len(set(ids)):
                raise ValueError("distributed XAJ unit_id values must be unique")
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
