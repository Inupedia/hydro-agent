from datetime import date, timedelta

import pytest

from hydro_agent.evaluation.evidence import HydrologicEvidenceBuilder
from hydro_agent.evaluation.evidence_summary import (
    annual_stability_evidence,
    compare_flood_events,
)


def dates(count: int, start: date) -> list[date]:
    return [start + timedelta(days=index) for index in range(count)]


def test_annual_stability_requires_multiple_supported_years():
    one_year_dates = dates(100, date(2020, 1, 1))
    one = HydrologicEvidenceBuilder(min_year_samples=30).build(
        window="calibration",
        dates=one_year_dates,
        observed=[float(index + 1) for index in range(100)],
        simulated=[float(index + 1) for index in range(100)],
    )
    assert annual_stability_evidence(one).status == "insufficient_data"

    two_year_dates = dates(730, date(2020, 1, 1))
    observed = [10.0 + (index % 50) for index in range(730)]
    simulated = [value * (1.05 if index < 366 else 0.95) for index, value in enumerate(observed)]
    two = HydrologicEvidenceBuilder(min_year_samples=30).build(
        window="calibration",
        dates=two_year_dates,
        observed=observed,
        simulated=simulated,
    )
    stability = annual_stability_evidence(two)

    assert stability.status == "available"
    assert stability.sample_count == 2
    assert "kge_stdev" in stability.metrics
    assert "pbias_percent_min" in stability.metrics


def test_event_comparison_uses_same_observed_event_boundaries():
    event_dates = dates(40, date(2020, 1, 1))
    observed = [1.0] * 30 + [10.0, 12.0, 15.0, 12.0, 10.0] + [1.0] * 5
    baseline = HydrologicEvidenceBuilder(
        min_fdc_samples=20,
        min_event_samples=2,
    ).build(
        window="development",
        dates=event_dates,
        observed=observed,
        simulated=[value * 1.4 for value in observed],
    )
    candidate = HydrologicEvidenceBuilder(
        min_fdc_samples=20,
        min_event_samples=2,
    ).build(
        window="development",
        dates=event_dates,
        observed=observed,
        simulated=[value * 1.1 for value in observed],
    )

    comparison = compare_flood_events(baseline, candidate)

    assert baseline.flood_events
    assert candidate.flood_events
    assert comparison.deltas
    assert any(label.endswith(".mae") for label in comparison.improved)


def test_event_comparison_rejects_different_windows():
    builder = HydrologicEvidenceBuilder(min_fdc_samples=2, min_event_samples=1)
    series_dates = dates(4, date(2020, 1, 1))
    kwargs = dict(dates=series_dates, observed=[1.0, 2.0, 3.0, 4.0], simulated=[1.0] * 4)
    left = builder.build(window="calibration", **kwargs)
    right = builder.build(window="development", **kwargs)
    with pytest.raises(ValueError, match="different windows"):
        compare_flood_events(left, right)
