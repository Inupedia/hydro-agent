from datetime import date

import pytest

from hydro_agent.workbench.timeline import build_experiment_timeline


def test_decade_research_period_uses_bounded_holdout() -> None:
    timeline = build_experiment_timeline(
        start_date=date(1980, 3, 13),
        end_date=date(1990, 3, 27),
        warmup_days=365,
        validation_days=30,
    )

    assert timeline.research_days == 3667
    assert timeline.validation_start == date(1990, 2, 26)
    assert timeline.validation_end == date(1990, 3, 27)
    assert timeline.validation_days == 30
    assert timeline.calibration_start == date(1980, 3, 13)
    assert timeline.calibration_end == date(1990, 2, 25)
    assert timeline.calibration_history_days is not None
    assert timeline.calibration_history_days > 3650
    assert timeline.estimated_rolling_forecast_runs == 90


def test_short_event_keeps_complete_window_for_validation() -> None:
    timeline = build_experiment_timeline(
        start_date=date(2000, 5, 1),
        end_date=date(2000, 5, 10),
        warmup_days=365,
        validation_days=30,
    )

    assert timeline.validation_start == date(2000, 5, 1)
    assert timeline.validation_end == date(2000, 5, 10)
    assert timeline.calibration_start is None
    assert timeline.calibration_history_days is None
    assert timeline.estimated_rolling_forecast_runs == 30


def test_validation_window_has_hard_api_bound() -> None:
    with pytest.raises(ValueError, match="validation_days"):
        build_experiment_timeline(
            start_date=date(1980, 1, 1),
            end_date=date(1990, 1, 1),
            warmup_days=365,
            validation_days=365,
        )
