from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, field_validator, model_validator

from hydro_agent.execution.contracts import ExecutionCapability, FrozenModel, Identifier


class ForcingRow(FrozenModel):
    valid_date: date
    precipitation_mm_day: float = Field(ge=0, allow_inf_nan=False)
    pet_mm_day: float = Field(ge=0, allow_inf_nan=False)
    # Optional air temperature for snow-aware models (e.g. HBV). Absent for P+PET models.
    temperature_c: float | None = Field(default=None, allow_inf_nan=False)
    source_kind: Literal["observation", "reanalysis", "forecast"]
    source: str = Field(min_length=1)
    available_at: AwareDatetime


class FlowObservation(FrozenModel):
    valid_date: date
    discharge_m3s: float = Field(ge=0, allow_inf_nan=False)
    source: str = Field(min_length=1)
    available_at: AwareDatetime
    # Keep questionable/imputed rows available for chronology and inspection,
    # while making scoring eligibility explicit all the way to model evaluation.
    eligible_for_scoring: bool = True
    quality_code: str = "approved"
    quality_note: str | None = None


class SnapshotContext(FrozenModel):
    task_id: Identifier
    snapshot_id: Identifier
    basin_id: Identifier
    phase: Literal["B", "F", "E"]
    forcing_mode: Literal["R", "F"]
    capability: ExecutionCapability
    issue_time: AwareDatetime
    history_days: int = Field(default=365, ge=1, le=36500)
    day_timezone: str = "UTC"
    history_end_date: date | None = None

    @model_validator(mode="after")
    def validate_history_end(self):
        if self.history_end_date is not None:
            if self.capability != "calibrate" or self.history_end_date > self.issue_date:
                raise ValueError(
                    "history_end_date requires calibration and cannot exceed issue date"
                )
        return self

    @field_validator("day_timezone")
    @classmethod
    def timezone_exists(cls, value):
        ZoneInfo(value)
        return value

    @property
    def issue_date(self):
        return self.issue_time.astimezone(ZoneInfo(self.day_timezone)).date()

    def end_of_day(self, valid_date):
        return datetime.combine(
            valid_date + timedelta(days=1), time.min, ZoneInfo(self.day_timezone)
        )

    @property
    def dates(self):
        first = (self.history_end_date or self.issue_date) - timedelta(days=self.history_days - 1)
        forecast_horizon_days = 3 if self.capability == "forecast" else 0
        return tuple(
            first + timedelta(days=i) for i in range(self.history_days + forecast_horizon_days)
        )

    @property
    def flow_dates(self):
        first = (self.history_end_date or self.issue_date) - timedelta(days=self.history_days - 1)
        truth_horizon_days = 3 if self.capability in {"forecast", "evaluate"} else 0
        return tuple(
            first + timedelta(days=i) for i in range(self.history_days + truth_horizon_days)
        )


class SnapshotFile(FrozenModel):
    role: str
    relative_path: Literal["forcing.csv", "streamflow.csv", "basin.json"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(ge=0)
    row_count: int = Field(ge=0)
    min_valid_date: date | None
    max_valid_date: date | None
    sources: tuple[str, ...]


class SnapshotManifest(FrozenModel):
    snapshot_id: Identifier
    context: SnapshotContext
    files: tuple[SnapshotFile, ...]
    created_at: AwareDatetime
    forcing_rows: tuple[ForcingRow, ...]
    flow_rows: tuple[FlowObservation, ...]
    source_metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent(self):
        if self.snapshot_id != self.context.snapshot_id:
            raise ValueError("snapshot id mismatch")
        if {f.relative_path for f in self.files} != {
            "forcing.csv",
            "streamflow.csv",
            "basin.json",
        } or len(self.files) != 3:
            raise ValueError("snapshot requires exactly three declared files")
        return self
