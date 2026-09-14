"""Deterministic rolling-forecast sampling for long research windows."""

from __future__ import annotations

from datetime import date, timedelta

FORECAST_LEAD_DAYS = 3
MAX_ROLLING_ISSUES = 90


def evenly_spaced_issue_days(
    start: date,
    end: date,
    limit: int,
    *,
    lead_days: int = FORECAST_LEAD_DAYS,
) -> tuple[date, ...]:
    """Return deterministic, full-lead-safe issue dates across a window.

    Every selected issue has all requested lead dates inside ``start..end``.
    This keeps development sampling from reading forcing across the final-test
    boundary and bounds rolling-evaluation cost without shrinking the continuous
    hydrologic evaluation window.
    """

    if end < start:
        raise ValueError("end before start")
    if limit < 1 or limit > MAX_ROLLING_ISSUES:
        raise ValueError(f"limit must be between 1 and {MAX_ROLLING_ISSUES}")
    if lead_days < 1:
        raise ValueError("lead_days must be positive")

    last_issue = end - timedelta(days=lead_days)
    if last_issue < start:
        return ()

    total = (last_issue - start).days + 1
    count = min(limit, total)
    if count == total:
        return tuple(start + timedelta(days=offset) for offset in range(total))
    if count == 1:
        return (start,)

    offsets = tuple((index * (total - 1)) // (count - 1) for index in range(count))
    return tuple(start + timedelta(days=offset) for offset in offsets)
