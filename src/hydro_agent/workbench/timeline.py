from dataclasses import dataclass
from datetime import date, timedelta

DEFAULT_VALIDATION_DAYS = 30
MAX_VALIDATION_DAYS = 90


@dataclass(frozen=True)
class ExperimentTimeline:
    """Explicitly separates the long research period from the operational holdout.

    ``research_start`` / ``research_end`` describe the user-selected study period.
    For long studies the final ``validation_days`` are held out for Gate/replay,
    while calibration uses all earlier research days in one continuous XAJ run.
    Short smoke/event tasks keep their complete interval as the validation window
    and fall back to the normal historical calibration snapshot.
    """

    research_start: date
    research_end: date
    validation_start: date
    validation_end: date
    calibration_start: date | None
    calibration_end: date
    calibration_history_days: int | None
    warmup_days: int

    @property
    def research_days(self) -> int:
        return (self.research_end - self.research_start).days + 1

    @property
    def validation_days(self) -> int:
        return (self.validation_end - self.validation_start).days + 1

    @property
    def estimated_rolling_forecast_runs(self) -> int:
        # Gate runs base + candidate. Replay runs the frozen scheme once per issue.
        return self.validation_days * 3

    def as_dict(self) -> dict[str, object]:
        return {
            "research_start_date": self.research_start.isoformat(),
            "research_end_date": self.research_end.isoformat(),
            "validation_start_date": self.validation_start.isoformat(),
            "validation_end_date": self.validation_end.isoformat(),
            "calibration_start_date": (
                self.calibration_start.isoformat() if self.calibration_start is not None else None
            ),
            "calibration_end_date": self.calibration_end.isoformat(),
            "calibration_history_days": self.calibration_history_days,
            "warmup_days": self.warmup_days,
            "research_days": self.research_days,
            "validation_days": self.validation_days,
            "estimated_rolling_forecast_runs": self.estimated_rolling_forecast_runs,
        }


def build_experiment_timeline(
    *,
    start_date: date,
    end_date: date,
    warmup_days: int,
    validation_days: int = DEFAULT_VALIDATION_DAYS,
) -> ExperimentTimeline:
    if end_date < start_date:
        raise ValueError("end_date before start_date")
    if warmup_days < 1:
        raise ValueError("warmup_days must be positive")
    if validation_days < 3 or validation_days > MAX_VALIDATION_DAYS:
        raise ValueError(f"validation_days must be between 3 and {MAX_VALIDATION_DAYS}")

    research_days = (end_date - start_date).days + 1
    effective_validation_days = min(validation_days, research_days)
    validation_start = end_date - timedelta(days=effective_validation_days - 1)

    # A long study period is split into calibration + independent holdout.
    # Keep at least three research days before the holdout; otherwise preserve
    # the legacy short-event behaviour and calibrate from historical context.
    if validation_start - start_date >= timedelta(days=3):
        calibration_start: date | None = start_date
        calibration_end = validation_start - timedelta(days=1)
        # SnapshotContext for calibrate no longer appends a forecast horizon.
        # Start the snapshot warmup_days before the research period so the
        # post-warmup objective begins exactly at research_start.
        first_snapshot_day = start_date - timedelta(days=warmup_days)
        calibration_history_days = (calibration_end - first_snapshot_day).days + 1
    else:
        calibration_start = None
        calibration_end = validation_start - timedelta(days=1)
        calibration_history_days = None

    return ExperimentTimeline(
        research_start=start_date,
        research_end=end_date,
        validation_start=validation_start,
        validation_end=end_date,
        calibration_start=calibration_start,
        calibration_end=calibration_end,
        calibration_history_days=calibration_history_days,
        warmup_days=warmup_days,
    )
