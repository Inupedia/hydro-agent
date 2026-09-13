from datetime import date

from hydro_agent.api.schemas import TaskCreateRequest
from hydro_agent.workbench.timeline import build_experiment_timeline


def test_explicit_multiyear_protocol_is_not_capped_at_ninety_days():
    timeline = build_experiment_timeline(
        start_date=date(1990, 1, 1),
        end_date=date(2003, 12, 31),
        warmup_days=365,
        development_start_date=date(1998, 1, 1),
        development_end_date=date(2000, 12, 31),
        final_test_start_date=date(2001, 1, 1),
        final_test_end_date=date(2003, 12, 31),
    )
    assert timeline.protocol_mode == "research"
    assert timeline.calibration_start == date(1990, 1, 1)
    assert timeline.calibration_end == date(1997, 12, 31)
    assert timeline.development_days > 1000
    assert timeline.final_test_days > 1000
    assert timeline.evaluation_history_days == 365 + timeline.final_test_days


def test_task_request_accepts_preregistered_year_windows():
    request = TaskCreateRequest(
        basin_id="yaogu",
        model_id="xaj",
        start_date=date(1990, 1, 1),
        end_date=date(2003, 12, 31),
        forcing_mode="R",
        base_scheme_id="base",
        allow_optimization=True,
        development_start_date=date(1998, 1, 1),
        development_end_date=date(2000, 12, 31),
        final_test_start_date=date(2001, 1, 1),
        final_test_end_date=date(2003, 12, 31),
    )
    assert request.development_start_date == date(1998, 1, 1)
    assert request.final_test_end_date == date(2003, 12, 31)
