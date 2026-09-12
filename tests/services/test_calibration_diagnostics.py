from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from hydro_agent.services.calibration_diagnostics import diagnose_prevalidation_window


class _Repo:
    def __init__(self, forecasts):
        self._forecasts = forecasts

    def list_forecasts(self, _task_id):
        return list(self._forecasts)


class _ForecastService:
    def forecast(self, **_kwargs):
        raise AssertionError("pre-populated diagnostic forecasts should be reused")


def test_diagnosis_uses_only_truth_before_validation_and_prioritizes_water_balance():
    validation_start = date(2000, 5, 1)
    latest_issue = validation_start - timedelta(days=4)
    first_issue = latest_issue - timedelta(days=9)

    flow_rows = []
    truth = {}
    for offset in range(30):
        day = first_issue + timedelta(days=offset)
        value = 10.0 + offset
        truth[day] = value
        flow_rows.append(SimpleNamespace(valid_date=day, discharge_m3s=value))

    forecasts = []
    for i in range(10):
        issue_day = first_issue + timedelta(days=i)
        leads = {}
        for lead in (1, 2, 3):
            target = issue_day + timedelta(days=lead)
            leads[str(lead)] = truth[target] * 1.2
        forecasts.append(
            SimpleNamespace(
                scheme_id="scheme-base",
                issue_time=datetime(
                    issue_day.year, issue_day.month, issue_day.day, tzinfo=timezone.utc
                ),
                lead_values_json=leads,
                forecast_id=f"f-{i:02d}",
            )
        )

    result = diagnose_prevalidation_window(
        repository=_Repo(forecasts),
        forecast_service=_ForecastService(),
        source=SimpleNamespace(flow_rows=flow_rows),
        policy=SimpleNamespace(),
        task_id="task-1",
        scheme_id="scheme-base",
        validation_start=validation_start,
        nse_good_enough=0.5,
    )

    assert result["recommended_strategy_id"] == "xaj-water-balance-v1"
    assert result["recommended_param_groups"] == ["evap", "runoff"]
    assert result["recommended_objective"] == "composite"
    assert result["metrics"]["pbias_percent"] > 10.0
    assert "diagnostic_truth_strictly_precedes_validation=true" in result["notes"]
    assert f"diagnostic_target_end={(validation_start - timedelta(days=1)).isoformat()}" in result["notes"]
