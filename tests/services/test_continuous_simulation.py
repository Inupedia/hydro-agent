from datetime import date, timedelta

import pytest

from hydro_agent.services.continuous_simulation import ContinuousSimulationEvidenceService


def _dates(count: int) -> list[date]:
    start = date(2020, 1, 1)
    return [start + timedelta(days=index) for index in range(count)]


def test_continuous_evidence_scores_one_uninterrupted_series() -> None:
    service = ContinuousSimulationEvidenceService()
    observed = [10.0, 20.0, 15.0, 30.0, 25.0]

    evidence = service.evaluate(
        window="development",
        dates=_dates(5),
        observed=observed,
        simulated=observed,
    )

    assert evidence.window == "development"
    assert evidence.sample_count == 5
    assert evidence.input_count == 5
    assert evidence.dropped_count == 0
    assert evidence.coverage == pytest.approx(1.0)
    assert evidence.nse == pytest.approx(1.0)
    assert evidence.kge == pytest.approx(1.0)
    assert evidence.pbias_percent == pytest.approx(0.0)
    assert evidence.peak_ratio == pytest.approx(1.0)
    assert evidence.peak_timing_lag_steps == 0


def test_continuous_evidence_discards_warmup_prefix_before_scoring() -> None:
    service = ContinuousSimulationEvidenceService()
    dates = _dates(6)
    observed = [100.0, 100.0, 10.0, 20.0, 30.0, 40.0]
    simulated = [0.0, 0.0, 10.0, 20.0, 30.0, 40.0]

    evidence = service.evaluate(
        window="calibration",
        dates=dates,
        observed=observed,
        simulated=simulated,
        discard_prefix_days=2,
    )

    assert evidence.start == dates[2]
    assert evidence.end == dates[-1]
    assert evidence.sample_count == 4
    assert evidence.input_count == 4
    assert evidence.nse == pytest.approx(1.0)
    assert evidence.kge == pytest.approx(1.0)


def test_continuous_evidence_uses_shared_quality_semantics() -> None:
    service = ContinuousSimulationEvidenceService()
    evidence = service.evaluate(
        window="development",
        dates=_dates(6),
        observed=[10.0, None, -1.0, 20.0, 30.0, 40.0],
        simulated=[10.0, 12.0, 13.0, -5.0, float("nan"), 40.0],
        quality_mask=[True, True, True, True, True, True],
    )

    # None observation, negative observation and non-finite simulation are dropped.
    # The finite negative simulation at observed=20 is retained and penalizes skill.
    assert evidence.input_count == 6
    assert evidence.sample_count == 3
    assert evidence.dropped_count == 3
    assert evidence.coverage == pytest.approx(0.5)
    assert evidence.dropped_by_reason == {
        "invalid_observation": 1,
        "negative_observation": 1,
        "nonfinite_simulation": 1,
    }
    assert evidence.nse < 1.0


def test_continuous_evidence_quality_mask_is_audited() -> None:
    evidence = ContinuousSimulationEvidenceService().evaluate(
        window="final_test",
        dates=_dates(4),
        observed=[10.0, 20.0, 30.0, 40.0],
        simulated=[10.0, 20.0, 30.0, 40.0],
        quality_mask=[True, False, True, True],
    )

    assert evidence.sample_count == 3
    assert evidence.dropped_by_reason == {"quality_mask": 1}
    assert evidence.as_metrics()["coverage"] == pytest.approx(0.75)


def test_continuous_evidence_rejects_misaligned_or_non_monotonic_series() -> None:
    service = ContinuousSimulationEvidenceService()

    with pytest.raises(ValueError, match="length mismatch"):
        service.evaluate(
            window="final_test",
            dates=_dates(3),
            observed=[1.0, 2.0],
            simulated=[1.0, 2.0],
        )

    with pytest.raises(ValueError, match="strictly increasing"):
        service.evaluate(
            window="final_test",
            dates=[date(2020, 1, 1), date(2020, 1, 1), date(2020, 1, 2)],
            observed=[1.0, 2.0, 3.0],
            simulated=[1.0, 2.0, 3.0],
        )

    with pytest.raises(ValueError, match="quality_mask length mismatch"):
        service.evaluate(
            window="final_test",
            dates=_dates(3),
            observed=[1.0, 2.0, 3.0],
            simulated=[1.0, 2.0, 3.0],
            quality_mask=[True, False],
        )
