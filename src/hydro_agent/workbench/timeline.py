from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

DEFAULT_DEVELOPMENT_DAYS = 30
DEFAULT_FINAL_TEST_DAYS = 30
MAX_HOLDOUT_DAYS = 90
MIN_WINDOW_DAYS = 3


@dataclass(frozen=True)
class DateWindow:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def as_dict(self, prefix: str) -> dict[str, str | int]:
        return {
            f"{prefix}_start_date": self.start.isoformat(),
            f"{prefix}_end_date": self.end.isoformat(),
            f"{prefix}_days": self.days,
        }


@dataclass(frozen=True)
class ExperimentTimeline:
    """Preregistered four-part calibration protocol.

    ``research_start`` / ``research_end`` are the complete user-selected study
    period. The model may use warmup forcing before ``research_start``. Model
    parameters are searched only on ``calibration``. Candidate selection/Gate may
    repeatedly inspect ``development``. ``final_test`` is reserved for the frozen
    scheme and must not participate in calibration or candidate selection.

    ``validation_*`` remains a compatibility alias for the development window so
    older workbench code keeps functioning while the final-test path is migrated.
    """

    research_start: date
    research_end: date
    warmup_start: date
    warmup_end: date
    calibration_start: date | None
    calibration_end: date | None
    development_start: date
    development_end: date
    final_test_start: date
    final_test_end: date
    calibration_history_days: int | None
    warmup_days: int
    protocol_mode: Literal["research", "smoke"] = "research"

    @property
    def research_days(self) -> int:
        return (self.research_end - self.research_start).days + 1

    @property
    def development_days(self) -> int:
        return (self.development_end - self.development_start).days + 1

    @property
    def final_test_days(self) -> int:
        return (self.final_test_end - self.final_test_start).days + 1

    @property
    def validation_start(self) -> date:
        return self.development_start

    @property
    def validation_end(self) -> date:
        return self.development_end

    @property
    def validation_days(self) -> int:
        return self.development_days

    @property
    def estimated_rolling_forecast_runs(self) -> int:
        # Development Gate runs base + candidate. Final test replays only the
        # frozen scheme, so the cost is 2*development + final_test rather than
        # three executions across one reused holdout.
        return self.development_days * 2 + self.final_test_days

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "research_start_date": self.research_start.isoformat(),
            "research_end_date": self.research_end.isoformat(),
            "warmup_start_date": self.warmup_start.isoformat(),
            "warmup_end_date": self.warmup_end.isoformat(),
            "calibration_start_date": (
                self.calibration_start.isoformat() if self.calibration_start is not None else None
            ),
            "calibration_end_date": (
                self.calibration_end.isoformat() if self.calibration_end is not None else None
            ),
            "calibration_history_days": self.calibration_history_days,
            "development_start_date": self.development_start.isoformat(),
            "development_end_date": self.development_end.isoformat(),
            "development_days": self.development_days,
            "final_test_start_date": self.final_test_start.isoformat(),
            "final_test_end_date": self.final_test_end.isoformat(),
            "final_test_days": self.final_test_days,
            "warmup_days": self.warmup_days,
            "research_days": self.research_days,
            "protocol_mode": self.protocol_mode,
            "estimated_rolling_forecast_runs": self.estimated_rolling_forecast_runs,
            # Compatibility: old runtime code treats validation as the mutable
            # candidate-selection window. It must never point at final_test.
            "validation_start_date": self.development_start.isoformat(),
            "validation_end_date": self.development_end.isoformat(),
            "validation_days": self.development_days,
        }
        return payload


def _compressed_smoke_windows(
    *, start_date: date, end_date: date
) -> tuple[date | None, date | None, DateWindow, DateWindow]:
    """Build deterministic non-overlapping windows for short CI/event tasks.

    Formal research should use the requested holdout lengths. For short smoke
    tasks we preserve independent development/final-test semantics with the
    smallest useful three-day windows. If fewer than six research days are
    supplied, calibration falls back to historical context and the research span
    is split as evenly as possible between development and final test.
    """

    total = (end_date - start_date).days + 1
    if total >= 9:
        final_days = MIN_WINDOW_DAYS
        development_days = MIN_WINDOW_DAYS
        calibration_days = total - final_days - development_days
        calibration_start = start_date
        calibration_end = start_date + timedelta(days=calibration_days - 1)
        development_start = calibration_end + timedelta(days=1)
    else:
        final_days = max(1, total // 2)
        development_days = total - final_days
        calibration_start = None
        calibration_end = None
        development_start = start_date

    development_end = development_start + timedelta(days=development_days - 1)
    final_start = development_end + timedelta(days=1)
    return (
        calibration_start,
        calibration_end,
        DateWindow(development_start, development_end),
        DateWindow(final_start, end_date),
    )


def build_experiment_timeline(
    *,
    start_date: date,
    end_date: date,
    warmup_days: int,
    validation_days: int = DEFAULT_DEVELOPMENT_DAYS,
    final_test_days: int = DEFAULT_FINAL_TEST_DAYS,
) -> ExperimentTimeline:
    """Create a leakage-safe calibration/development/final-test protocol.

    ``validation_days`` is kept as the public compatibility name for the
    development window. New callers should think of it as development_days.
    """

    if end_date < start_date:
        raise ValueError("end_date before start_date")
    research_days = (end_date - start_date).days + 1
    if research_days < 2:
        raise ValueError("research period must contain at least two days")
    if warmup_days < 1:
        raise ValueError("warmup_days must be positive")
    if validation_days < MIN_WINDOW_DAYS or validation_days > MAX_HOLDOUT_DAYS:
        raise ValueError(
            f"validation_days must be between {MIN_WINDOW_DAYS} and {MAX_HOLDOUT_DAYS}"
        )
    if final_test_days < MIN_WINDOW_DAYS or final_test_days > MAX_HOLDOUT_DAYS:
        raise ValueError(
            f"final_test_days must be between {MIN_WINDOW_DAYS} and {MAX_HOLDOUT_DAYS}"
        )

    requested_holdout = validation_days + final_test_days
    warmup_start = start_date - timedelta(days=warmup_days)
    warmup_end = start_date - timedelta(days=1)

    # Formal research requires at least three calibration days before the two
    # independently held-out windows. Otherwise use the explicit smoke protocol.
    if research_days >= requested_holdout + MIN_WINDOW_DAYS:
        final_test_end = end_date
        final_test_start = end_date - timedelta(days=final_test_days - 1)
        development_end = final_test_start - timedelta(days=1)
        development_start = development_end - timedelta(days=validation_days - 1)
        calibration_start: date | None = start_date
        calibration_end: date | None = development_start - timedelta(days=1)
        development = DateWindow(development_start, development_end)
        final_test = DateWindow(final_test_start, final_test_end)
        protocol_mode: Literal["research", "smoke"] = "research"
    else:
        calibration_start, calibration_end, development, final_test = _compressed_smoke_windows(
            start_date=start_date,
            end_date=end_date,
        )
        protocol_mode = "smoke"

    if calibration_end is not None:
        # Calibration snapshot starts at warmup_start and ends on the final
        # calibration day. Objective scoring can discard the first warmup_days.
        calibration_history_days = (calibration_end - warmup_start).days + 1
    else:
        calibration_history_days = None

    return ExperimentTimeline(
        research_start=start_date,
        research_end=end_date,
        warmup_start=warmup_start,
        warmup_end=warmup_end,
        calibration_start=calibration_start,
        calibration_end=calibration_end,
        development_start=development.start,
        development_end=development.end,
        final_test_start=final_test.start,
        final_test_end=final_test.end,
        calibration_history_days=calibration_history_days,
        warmup_days=warmup_days,
        protocol_mode=protocol_mode,
    )
