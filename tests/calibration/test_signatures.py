from datetime import datetime, timedelta, timezone

from hydro_agent.calibration.signatures import (
    build_flood_event_bank,
    compute_hydrologic_signatures,
)


def test_event_bank_extracts_multiple_floods_and_relative_magnitudes():
    obs = [1, 1, 2, 8, 20, 7, 2, 1, 1, 3, 12, 30, 9, 2, 1, 1, 5, 18, 45, 10, 2, 1]
    sim = [1, 1, 2, 7, 18, 8, 2, 1, 1, 3, 11, 27, 10, 2, 1, 1, 4, 17, 40, 11, 2, 1]
    events = build_flood_event_bank(obs, sim, quantile=0.75)
    assert len(events) >= 3
    assert {event.magnitude_class for event in events} >= {"small", "medium", "large"}
    assert all(event.peak_relative_error >= 0 for event in events)


def test_signatures_report_water_balance_recession_and_event_metrics():
    start = datetime(2018, 1, 1, tzinfo=timezone.utc)
    obs = [10.0 + ((i % 30) / 5.0) for i in range(120)]
    for peak in (20, 50, 80, 105):
        obs[peak] += 40.0
        if peak + 1 < len(obs):
            obs[peak + 1] += 20.0
    sim = [value * 0.9 for value in obs]
    times = tuple(start + timedelta(days=i) for i in range(len(obs)))
    signatures = compute_hydrologic_signatures(
        obs,
        sim,
        times=times,
        precipitation_mm=[2.0] * len(obs),
        area_km2=1000.0,
    )
    metrics = signatures.metrics
    assert 0.09 < metrics["volume_rel_error"] < 0.11
    assert metrics["annual_volume_bias_mae"] > 0
    assert metrics["seasonal_volume_bias_mae"] > 0
    assert "recession_fast_rel_error" in metrics
    assert metrics["flood_event_count"] >= 3
    assert metrics["event_peak_rel_error_median"] > 0
    assert "observed_runoff_ratio" in metrics
