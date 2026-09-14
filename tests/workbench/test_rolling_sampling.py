from datetime import date, timedelta

import pytest

from hydro_agent.workbench.rolling_sampling import evenly_spaced_issue_days


def test_evenly_spaced_sampling_preserves_endpoints_and_full_three_day_leads():
    start = date(1999, 1, 1)
    end = date(2001, 12, 31)
    days = evenly_spaced_issue_days(start, end, 24)

    assert len(days) == 24
    assert days[0] == start
    assert days[-1] == end - timedelta(days=3)
    assert tuple(sorted(days)) == days
    assert len(set(days)) == len(days)
    assert all(day + timedelta(days=3) <= end for day in days)


def test_sampling_returns_every_safe_issue_when_limit_exceeds_available_days():
    days = evenly_spaced_issue_days(date(2000, 5, 1), date(2000, 5, 7), 90)
    assert days == (
        date(2000, 5, 1),
        date(2000, 5, 2),
        date(2000, 5, 3),
        date(2000, 5, 4),
    )


def test_sampling_returns_empty_when_window_cannot_contain_all_leads():
    assert evenly_spaced_issue_days(date(2000, 5, 1), date(2000, 5, 3), 2) == ()


def test_sampling_rejects_invalid_limits():
    with pytest.raises(ValueError, match="limit"):
        evenly_spaced_issue_days(date(2000, 5, 1), date(2000, 5, 10), 0)
    with pytest.raises(ValueError, match="limit"):
        evenly_spaced_issue_days(date(2000, 5, 1), date(2000, 5, 10), 91)
