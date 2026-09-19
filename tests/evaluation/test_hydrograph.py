from datetime import date

import pytest

from hydro_agent.api.schemas import HydrographComparisonResult
from hydro_agent.evaluation.hydrograph import build_comparison, write_bundle
from hydro_agent.evaluation.metrics import pbias_percent, rmse


def test_calibration_comparison_is_not_labelled_calibrated_until_gate_accept():
    dates = [date(2020, 5, 1), date(2020, 5, 2), date(2020, 5, 3), date(2020, 5, 4)]
    observed = {day: 10.0 + i for i, day in enumerate(dates)}
    baseline = [8.0, 9.0, 10.0, 11.0]
    candidate = [8.5, 9.5, 10.5, 11.5]
    comparison = build_comparison(
        kind="calibration",
        dates=dates,
        observed=observed,
        warmup_days=1,
        evaluated_window="calibration",
        baseline=baseline,
        candidate=candidate,
        gate_status="KEEP",
        frozen_is_candidate=False,
    )
    assert comparison["calibrated"] is False
    assert comparison["series"][0]["is_warmup"] is True
    assert comparison["series"][1]["window"] == "calibration"
    assert comparison["series"][1]["change_m3s"] == 0.5
    assert comparison["title"].startswith("观测与基线")


def test_independent_test_title_does_not_say_calibrated_on_keep(tmp_path):
    dates = [date(2020, 6, 1), date(2020, 6, 2), date(2020, 6, 3)]
    observed = {dates[0]: 1.0, dates[1]: 2.0, dates[2]: 3.0}
    comparison = build_comparison(
        kind="independent_test",
        dates=dates,
        observed=observed,
        warmup_days=1,
        evaluated_window="test",
        frozen=[1.1, 2.1, 2.8],
        gate_status="KEEP",
        frozen_is_candidate=False,
    )
    assert comparison["calibrated"] is False
    assert "独立检验" in comparison["title"]
    assert "calibrated" not in comparison["title"].lower()
    artifacts = write_bundle(tmp_path, comparison, stem="test-hydrograph")
    csv_text = (tmp_path / artifacts["csv"]).read_text(encoding="utf-8")
    assert csv_text.splitlines()[0].startswith("time,observed_m3s")
    assert "frozen_m3s" in csv_text
    validated = HydrographComparisonResult.model_validate(comparison)
    assert validated.frozen_metrics is not None
    assert validated.frozen_metrics["window"] == "test"
    assert validated.frozen_metrics["start_date"] == "2020-06-02"


def test_rmse_and_pbias_match_hand_calculation():
    obs = [1.0, 2.0, 3.0]
    sim = [1.0, 2.0, 2.0]
    assert rmse(obs, sim) == pytest.approx((1.0 / 3.0) ** 0.5)
    assert pbias_percent(obs, sim) == pytest.approx(100.0 * ((1 + 2 + 2) - (1 + 2 + 3)) / 6.0)



def test_calibration_comparison_exposes_baseline_and_candidate_diagnosis_packets():
    from datetime import timedelta

    dates = [date(2020, 7, 1) + timedelta(days=i) for i in range(42)]
    pattern = [10, 11, 12, 18, 40, 90, 55, 25, 14, 11, 10, 10, 10, 10]
    observed_values = [float(value) for value in pattern * 3]
    observed = {day: value for day, value in zip(dates, observed_values)}
    baseline = [value * 0.85 for value in observed_values]
    candidate = [value * 0.95 for value in observed_values]
    rain_values = [0, 0, 4, 20, 12, 0, 0, 0, 0, 0, 0, 0, 0, 0] * 3
    precipitation = {day: float(value) for day, value in zip(dates, rain_values)}

    comparison = build_comparison(
        kind="calibration",
        dates=dates,
        observed=observed,
        warmup_days=0,
        evaluated_window="calibration",
        baseline=baseline,
        candidate=candidate,
        precipitation=precipitation,
    )

    assert comparison["baseline_diagnosis"]["window"] == "calibration"
    assert comparison["candidate_diagnosis"]["window"] == "calibration"
    assert len(comparison["candidate_diagnosis"]["flood_events"]) >= 2
    validated = HydrographComparisonResult.model_validate(comparison)
    assert validated.candidate_diagnosis is not None
    assert validated.candidate_diagnosis["window"] == "calibration"


def test_independent_test_does_not_expose_diagnosis_feedback_packet():
    dates = [date(2020, 8, 1), date(2020, 8, 2), date(2020, 8, 3)]
    observed = {dates[0]: 10.0, dates[1]: 20.0, dates[2]: 15.0}
    comparison = build_comparison(
        kind="independent_test",
        dates=dates,
        observed=observed,
        warmup_days=0,
        evaluated_window="final_test",
        frozen=[9.0, 19.0, 16.0],
    )

    assert "baseline_diagnosis" not in comparison
    assert "candidate_diagnosis" not in comparison



def test_short_calibration_window_keeps_precipitation_event_basis():
    dates = [date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4)]
    observed = {dates[0]: 1.6, dates[1]: 1.5, dates[2]: 1.7}
    precipitation = {dates[0]: 4.0, dates[1]: 0.5, dates[2]: 2.5}

    comparison = build_comparison(
        kind="calibration",
        dates=dates,
        observed=observed,
        warmup_days=0,
        evaluated_window="calibration",
        baseline=[1.5, 1.4, 1.6],
        candidate=[1.55, 1.45, 1.65],
        precipitation=precipitation,
    )

    assert comparison["candidate_diagnosis"]["flood_events"]
    assert comparison["candidate_diagnosis"]["flood_events"][0]["basis"] == "rainfall_runoff"
