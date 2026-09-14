from datetime import date

from hydro_agent.api.schemas import TaskCreateRequest
from hydro_agent.api.services import build_runtime_task_config
from hydro_agent.workbench.timeline import build_experiment_timeline


def test_explicit_multiyear_protocol_is_not_capped_at_ninety_days():
    timeline = build_experiment_timeline(
        start_date=date(1990, 1, 1),
        end_date=date(2003, 12, 31),
        warmup_days=365,
        development_start_date=date(1999, 1, 1),
        development_end_date=date(2001, 12, 31),
        final_test_start_date=date(2002, 1, 1),
        final_test_end_date=date(2003, 12, 31),
    )
    assert timeline.protocol_mode == "research"
    assert timeline.calibration_start == date(1990, 1, 1)
    assert timeline.calibration_end == date(1998, 12, 31)
    assert timeline.development_days > 1000
    assert timeline.final_test_days > 700
    assert timeline.evaluation_history_days == 365 + timeline.final_test_days


def test_task_request_accepts_preregistered_year_windows_and_sampling_limits():
    request = TaskCreateRequest(
        basin_id="yaogu",
        model_id="xaj",
        start_date=date(1990, 1, 1),
        end_date=date(2003, 12, 31),
        forcing_mode="R",
        base_scheme_id="base",
        allow_optimization=True,
        development_start_date=date(1999, 1, 1),
        development_end_date=date(2001, 12, 31),
        final_test_start_date=date(2002, 1, 1),
        final_test_end_date=date(2003, 12, 31),
        development_rolling_issue_limit=24,
        final_test_rolling_issue_limit=24,
    )
    assert request.development_start_date == date(1999, 1, 1)
    assert request.final_test_end_date == date(2003, 12, 31)
    assert request.development_rolling_issue_limit == 24
    assert request.final_test_rolling_issue_limit == 24


def test_runtime_alias_uses_latest_full_lead_safe_development_issue():
    timeline = build_experiment_timeline(
        start_date=date(1990, 1, 1),
        end_date=date(2003, 12, 31),
        warmup_days=365,
        development_start_date=date(1999, 1, 1),
        development_end_date=date(2001, 12, 31),
        final_test_start_date=date(2002, 1, 1),
        final_test_end_date=date(2003, 12, 31),
    )
    workbench = {
        **timeline.as_dict(),
        "development_rolling_issue_limit": 24,
        "final_test_rolling_issue_limit": 24,
    }
    runtime = build_runtime_task_config(workbench)
    assert runtime["development_end_date"] == "2001-12-31"
    assert runtime["end_date"] == "2001-12-28"
    assert len(runtime["development_rolling_issue_dates"]) == 24
    assert runtime["development_rolling_issue_dates"][0] == "1999-01-01"
    assert runtime["development_rolling_issue_dates"][-1] == "2001-12-28"
