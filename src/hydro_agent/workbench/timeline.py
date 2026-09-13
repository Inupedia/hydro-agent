from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

DEFAULT_DEVELOPMENT_DAYS = 30
DEFAULT_FINAL_TEST_DAYS = 30
MAX_HOLDOUT_DAYS = 3650
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
    """Preregistered calibration → development → final-test protocol."""

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
    def evaluation_history_days(self) -> int:
        """Warmup plus the complete independently held-out final-test period."""

        return self.warmup_days + self.final_test_days

    @property
    def estimated_rolling_forecast_runs(self) -> int:
        return self.development_days * 2 + self.final_test_days

    def as_dict(self) -> dict[str, object]:
        return {
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
            "evaluation_history_days": self.evaluation_history_days,
            "warmup_days": self.warmup_days,
            "research_days": self.research_days,
            "protocol_mode": self.protocol_mode,
            "estimated_rolling_forecast_runs": self.estimated_rolling_forecast_runs,
            # Legacy alias: validation always means mutable development, never final_test.
            "validation_start_date": self.development_start.isoformat(),
            "validation_end_date": self.development_end.isoformat(),
            "validation_days": self.development_days,
        }


def _compressed_smoke_windows(
    *, start_date: date, end_date: date
) -> tuple[date | None, date | None, DateWindow, DateWindow]:
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


def _explicit_windows(
    *,
    research_start: date,
    research_end: date,
    development_start: date,
    development_end: date,
    final_test_start: date,
    final_test_end: date,
) -> tuple[date, date, DateWindow, DateWindow]:
    for name, day in (
        ("development_start", development_start),
        ("development_end", development_end),
        ("final_test_start", final_test_start),
        ("final_test_end", final_test_end),
    ):
        if day < research_start or day > research_end:
            raise ValueError(f"{name} lies outside research period")
    if development_end < development_start:
        raise ValueError("development_end before development_start")
    if final_test_end < final_test_start:
        raise ValueError("final_test_end before final_test_start")
    if development_end >= final_test_start:
        raise ValueError("development and final_test must not overlap")
    calibration_start = research_start
    calibration_end = development_start - timedelta(days=1)
    if (calibration_end - calibration_start).days + 1 < MIN_WINDOW_DAYS:
        raise ValueError("explicit research protocol requires at least three calibration days")
    if (development_end - development_start).days + 1 < MIN_WINDOW_DAYS:
        raise ValueError("explicit development window requires at least three days")
    if (final_test_end - final_test_start).days + 1 < MIN_WINDOW_DAYS:
        raise ValueError("explicit final_test window requires at least three days")
    return (
        calibration_start,
        calibration_end,
        DateWindow(development_start, development_end),
        DateWindow(final_test_start, final_test_end),
    )


def build_experiment_timeline(
    *,
    start_date: date,
    end_date: date,
    warmup_days: int,
    validation_days: int = DEFAULT_DEVELOPMENT_DAYS,
    final_test_days: int = DEFAULT_FINAL_TEST_DAYS,
    development_start_date: date | None = None,
    development_end_date: date | None = None,
    final_test_start_date: date | None = None,
    final_test_end_date: date | None = None,
) -> ExperimentTimeline:
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

    explicit = (
        development_start_date,
        development_end_date,
        final_test_start_date,
        final_test_end_date,
    )
    explicit_count = sum(value is not None for value in explicit)
    if explicit_count not in {0, 4}:
        raise ValueError("explicit research protocol requires all four holdout dates")

    warmup_start = start_date - timedelta(days=warmup_days)
    warmup_end = start_date - timedelta(days=1)

    if explicit_count == 4:
        calibration_start, calibration_end, development, final_test = _explicit_windows(
            research_start=start_date,
            research_end=end_date,
            development_start=development_start_date,  # type: ignore[arg-type]
            development_end=development_end_date,  # type: ignore[arg-type]
            final_test_start=final_test_start_date,  # type: ignore[arg-type]
            final_test_end=final_test_end_date,  # type: ignore[arg-type]
        )
        protocol_mode: Literal["research", "smoke"] = "research"
    else:
        requested_holdout = validation_days + final_test_days
        if research_days >= requested_holdout + MIN_WINDOW_DAYS:
            final_test_end = end_date
            final_test_start = end_date - timedelta(days=final_test_days - 1)
            development_end = final_test_start - timedelta(days=1)
            development_start = development_end - timedelta(days=validation_days - 1)
            calibration_start = start_date
            calibration_end = development_start - timedelta(days=1)
            development = DateWindow(development_start, development_end)
            final_test = DateWindow(final_test_start, final_test_end)
            protocol_mode = "research"
        else:
            calibration_start, calibration_end, development, final_test = _compressed_smoke_windows(
                start_date=start_date,
                end_date=end_date,
            )
            protocol_mode = "smoke"

    calibration_history_days = (
        (calibration_end - warmup_start).days + 1 if calibration_end is not None else None
    )

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
