from __future__ import annotations

from datetime import date, timedelta

import pytest

from hydro_agent.evaluation.evidence import HydrologicEvidenceBuilder, compare_evidence


def _dates(count: int, start: date = date(2020, 1, 1)) -> list[date]:
    return [start + timedelta(days=index) for index in range(count)]


def test_short_window_marks_unsupported_sections_insufficient():
    bundle = HydrologicEvidenceBuilder().build(
        window="final_test",
        dates=_dates(3),
        observed=[1.0, 2.0, 3.0],
        simulated=[1.1, 1.9, 3.1],
    )

    assert bundle.overall.status == "available"
    assert bundle.overall.sample_count == 3
    assert bundle.fdc.status == "insufficient_data"
    assert all(item.status == "insufficient_data" for item in bundle.flow_regimes.values())
    assert all(item.status == "insufficient_data" for item in bundle.years.values())
    assert bundle.flood_events == ()


def test_quality_mask_and_invalid_observations_are_audited():
    dates = _dates(7)
    bundle = HydrologicEvidenceBuilder(min_slice_samples=2).build(
        window="development",
        dates=dates,
        observed=[1.0, None, float("nan"), -1.0, 5.0, 6.0, 7.0],
        simulated=[1.0, 2.0, 3.0, 4.0, float("nan"), -2.0, 7.0],
        quality_mask=[True, True, True, True, True, True, False],
    )

    assert bundle.quality.total_count == 7
    assert bundle.quality.valid_count == 2
    assert bundle.quality.dropped_count == 5
    assert bundle.quality.dropped_by_reason == {
        "invalid_observation": 1,
        "negative_observation": 1,
        "nonfinite_observation": 1,
        "nonfinite_simulation": 1,
        "quality_mask": 1,
    }
    # Negative model output is deliberately retained as evidence of bad behaviour.
    assert bundle.overall.sample_count == 2


def test_explicit_wet_dry_seasons_are_basin_config_not_guessed():
    dates = _dates(365, date(2021, 1, 1))
    observed = [10.0 + index / 100.0 for index in range(365)]
    simulated = [value * 1.02 for value in observed]
    builder = HydrologicEvidenceBuilder(
        min_slice_samples=10,
        min_year_samples=30,
        season_definitions={"wet": (5, 6, 7, 8, 9), "dry": (10, 11, 12, 1, 2, 3, 4)},
    )

    bundle = builder.build(
        window="calibration",
        dates=dates,
        observed=observed,
        simulated=simulated,
    )

    assert set(bundle.seasons) == {"wet", "dry"}
    assert bundle.seasons["wet"].status == "available"
    assert bundle.seasons["dry"].status == "available"
    assert bundle.years["2021"].status == "available"
    assert bundle.fdc.status == "available"


def test_flow_regimes_and_fdc_are_built_from_observed_distribution():
    dates = _dates(100)
    observed = [float(index + 1) for index in range(100)]
    simulated = [value * 1.1 for value in observed]
    bundle = HydrologicEvidenceBuilder(min_slice_samples=5, min_fdc_samples=20).build(
        window="calibration",
        dates=dates,
        observed=observed,
        simulated=simulated,
    )

    assert bundle.flow_regimes["low"].status == "available"
    assert bundle.flow_regimes["mid"].status == "available"
    assert bundle.flow_regimes["high"].status == "available"
    assert bundle.fdc.metrics["exceed_50_simulated"] == pytest.approx(
        bundle.fdc.metrics["exceed_50_observed"] * 1.1
    )


def test_compare_evidence_only_assigns_direction_when_semantics_are_clear():
    dates = _dates(40)
    observed = [float(index + 1) for index in range(40)]
    builder = HydrologicEvidenceBuilder(min_slice_samples=5, min_fdc_samples=20)
    baseline = builder.build(
        window="development",
        dates=dates,
        observed=observed,
        simulated=[value * 1.2 for value in observed],
    )
    candidate = builder.build(
        window="development",
        dates=dates,
        observed=observed,
        simulated=[value * 1.05 for value in observed],
    )

    comparison = compare_evidence(baseline, candidate)

    assert "overall.mae" in comparison.improved
    assert "overall.rmse" in comparison.improved
    # Ratios need closeness-to-target semantics, so raw increase/decrease is neutral.
    assert "overall.peak_ratio" in comparison.unchanged
    assert comparison.deltas


def test_builder_rejects_non_monotonic_dates_and_mask_mismatch():
    builder = HydrologicEvidenceBuilder()
    with pytest.raises(ValueError, match="strictly increasing"):
        builder.build(
            window="calibration",
            dates=[date(2020, 1, 2), date(2020, 1, 1)],
            observed=[1.0, 2.0],
            simulated=[1.0, 2.0],
        )
    with pytest.raises(ValueError, match="quality_mask length mismatch"):
        builder.build(
            window="calibration",
            dates=_dates(2),
            observed=[1.0, 2.0],
            simulated=[1.0, 2.0],
            quality_mask=[True],
        )
