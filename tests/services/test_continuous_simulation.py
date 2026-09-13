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
    assert evidence.nse == pytest.approx(1.0)
    assert evidence.kge == pytest.approx(1.0)


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
