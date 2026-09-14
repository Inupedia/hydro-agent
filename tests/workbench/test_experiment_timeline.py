from datetime import date, timedelta

import pytest

from hydro_agent.api.services import build_runtime_task_config
from hydro_agent.workbench.timeline import build_experiment_timeline


def test_decade_research_period_separates_development_and_final_test() -> None:
    timeline = build_experiment_timeline(
        start_date=date(1980, 3, 13),
        end_date=date(1990, 3, 27),
        warmup_days=365,
        validation_days=30,
        final_test_days=30,
    )

    assert timeline.research_days == 3667
    assert timeline.protocol_mode == "research"
    assert timeline.warmup_start == date(1979, 3, 14)
    assert timeline.warmup_end == date(1980, 3, 12)
    assert timeline.calibration_start == date(1980, 3, 13)
    assert timeline.calibration_end == date(1990, 1, 26)
    assert timeline.development_start == date(1990, 1, 27)
    assert timeline.development_end == date(1990, 2, 25)
    assert timeline.final_test_start == date(1990, 2, 26)
    assert timeline.final_test_end == date(1990, 3, 27)
    assert timeline.validation_start == timeline.development_start
    assert timeline.validation_end == timeline.development_end
    assert timeline.calibration_history_days == 3972
    assert timeline.estimated_rolling_forecast_runs == 90

    calibration_issue = timeline.development_start - timedelta(days=1)
    assert calibration_issue == timeline.calibration_end
    assert timeline.development_end < timeline.final_test_start


def test_runtime_restore_points_legacy_window_to_development_not_final_test() -> None:
    timeline = build_experiment_timeline(
        start_date=date(1980, 3, 13),
        end_date=date(1990, 3, 27),
        warmup_days=365,
        validation_days=30,
        final_test_days=30,
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
    assert runtime["start_date"] == "1990-01-27"
    assert runtime["end_date"] == "1990-02-25"
    assert runtime["development_start_date"] == "1990-01-27"
    assert runtime["development_end_date"] == "1990-02-25"
    assert runtime["final_test_start_date"] == "1990-02-26"
    assert runtime["final_test_end_date"] == "1990-03-27"
    assert runtime["calibration_end_date"] == "1990-01-26"
    assert runtime["calibration_history_days"] == 3972
    assert runtime["model_plan_id"] == "plan-leaf"


def test_runtime_restore_preserves_legacy_window_without_protocol_fields() -> None:
    runtime = build_runtime_task_config({"start_date": "2025-05-01", "end_date": "2025-05-10"})

    assert runtime["start_date"] == "2025-05-01"
    assert runtime["end_date"] == "2025-05-10"


def test_short_event_uses_explicit_smoke_protocol_without_window_reuse() -> None:
    timeline = build_experiment_timeline(
        start_date=date(2000, 5, 1),
        end_date=date(2000, 5, 10),
        warmup_days=365,
        validation_days=30,
        final_test_days=30,
    )

    assert timeline.protocol_mode == "smoke"
    assert timeline.calibration_start == date(2000, 5, 1)
    assert timeline.calibration_end == date(2000, 5, 4)
    assert timeline.development_start == date(2000, 5, 5)
    assert timeline.development_end == date(2000, 5, 7)
    assert timeline.final_test_start == date(2000, 5, 8)
    assert timeline.final_test_end == date(2000, 5, 10)
    assert timeline.estimated_rolling_forecast_runs == 9


def test_one_day_research_period_is_not_splittable() -> None:
    with pytest.raises(ValueError, match="at least two days"):
        build_experiment_timeline(
            start_date=date(2000, 5, 1),
            end_date=date(2000, 5, 1),
            warmup_days=365,
            validation_days=30,
            final_test_days=30,
        )


def test_formal_holdout_windows_are_not_capped_at_legacy_90_days() -> None:
    long_development = build_experiment_timeline(
        start_date=date(1980, 1, 1),
        end_date=date(1990, 1, 1),
        warmup_days=365,
        validation_days=365,
        final_test_days=30,
    )
    assert long_development.protocol_mode == "research"
    assert long_development.development_start == date(1988, 12, 3)
    assert long_development.development_end == date(1989, 12, 2)
    assert long_development.final_test_start == date(1989, 12, 3)
    assert long_development.final_test_end == date(1990, 1, 1)

    long_final_test = build_experiment_timeline(
        start_date=date(1980, 1, 1),
        end_date=date(1990, 1, 1),
        warmup_days=365,
        validation_days=30,
        final_test_days=365,
    )
    assert long_final_test.protocol_mode == "research"
    assert long_final_test.development_start == date(1988, 12, 3)
    assert long_final_test.development_end == date(1989, 1, 1)
    assert long_final_test.final_test_start == date(1989, 1, 2)
    assert long_final_test.final_test_end == date(1990, 1, 1)
