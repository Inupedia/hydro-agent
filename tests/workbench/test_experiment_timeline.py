from datetime import date, timedelta

import pytest

from hydro_agent.api.services import build_runtime_task_config
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
    assert timeline.calibration_history_days == 4002
    calibration_issue = timeline.validation_start - timedelta(days=1)
    first_required_day = calibration_issue - timedelta(days=timeline.calibration_history_days - 1)
    assert calibration_issue == date(1990, 2, 25)
    assert first_required_day == date(1979, 3, 14)
    assert timeline.estimated_rolling_forecast_runs == 90


def test_runtime_restore_keeps_research_provenance_but_uses_holdout_window() -> None:
    timeline = build_experiment_timeline(
        start_date=date(1980, 3, 13),
        end_date=date(1990, 3, 27),
        warmup_days=365,
        validation_days=30,
    )
    persisted = {
        "start_date": "1980-03-13",
        "end_date": "1990-03-27",
        **timeline.as_dict(),
    }

    runtime = build_runtime_task_config(
        persisted,
        base={"model_id": "xaj", "forcing_mode": "R"},
        model_plan_id="plan-leaf",
    )

    assert runtime["research_start_date"] == "1980-03-13"
    assert runtime["research_end_date"] == "1990-03-27"
    assert runtime["start_date"] == "1990-02-26"
    assert runtime["end_date"] == "1990-03-27"
    assert runtime["calibration_end_date"] == "1990-02-25"
    assert runtime["calibration_history_days"] == 4002
    assert runtime["model_plan_id"] == "plan-leaf"


def test_runtime_restore_preserves_legacy_window_without_holdout_fields() -> None:
    runtime = build_runtime_task_config({"start_date": "2025-05-01", "end_date": "2025-05-10"})

    assert runtime["start_date"] == "2025-05-01"
    assert runtime["end_date"] == "2025-05-10"


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
