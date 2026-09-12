"""Shared temporal budgets for leakage-safe model windows."""

from datetime import date, timedelta

DIAGNOSTIC_LOOKBACK_ISSUE_DAYS = 10
DIAGNOSTIC_VALIDATION_GAP_DAYS = 4

# Latest diagnostic issue is validation_start - 4 days; a ten-day lookback
# therefore reaches validation_start - 13 days.
PREVALIDATION_ISSUE_RESERVE_DAYS = (
    DIAGNOSTIC_VALIDATION_GAP_DAYS + DIAGNOSTIC_LOOKBACK_ISSUE_DAYS - 1
)


def recommended_task_window(
    data_start: date, data_end: date, history_days: int, *, span_days: int = 14
) -> tuple[date, date]:
    """Return a task window legal for history, diagnostics, and three leads."""
    first_issue = data_start + timedelta(days=history_days - 1)
    last_issue = data_end - timedelta(days=3)
    start = first_issue + timedelta(days=PREVALIDATION_ISSUE_RESERVE_DAYS)
    if start > last_issue:
        raise ValueError("资料长度不足以支撑预热、诊断窗口和三日 lead")
    return start, min(start + timedelta(days=span_days), last_issue)
