from datetime import datetime

from pydantic import Field, field_validator, model_validator

from hydro_agent.execution.contracts import FrozenModel, Identifier


class ForecastRecord(FrozenModel):
    forecast_id: Identifier
    task_id: Identifier
    action_run_id: Identifier
    scheme_id: Identifier
    data_snapshot_id: Identifier
    issue_time: datetime
    lead_values: dict[int, float]
    unit: str
    artifact_ids: tuple[str, ...]

    @field_validator("unit")
    @classmethod
    def unit_must_be_m3s(cls, value: str) -> str:
        if value != "m3/s":
            raise ValueError("unit must be m3/s")
        return value

    @model_validator(mode="after")
    def exact_leads(self):
        if set(self.lead_values) != {1, 2, 3}:
            raise ValueError("leads must be exactly 1,2,3")
        if any(
            not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf"))
            for v in self.lead_values.values()
        ):
            raise ValueError("lead values must be finite")
        return self


class ForecastCreate(FrozenModel):
    forecast_id: Identifier
    task_id: Identifier
    action_run_id: Identifier
    scheme_id: Identifier
    data_snapshot_id: Identifier
    issue_time: datetime | str
    lead_values: dict[int, float]
    unit: str = "m3/s"
    artifact_ids: tuple[str, ...] = Field(default_factory=tuple)
