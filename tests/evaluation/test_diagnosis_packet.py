from datetime import date, timedelta

from hydro_agent.evaluation.diagnosis_packet import build_diagnosis_packet
from hydro_agent.evaluation.evidence import HydrologicEvidenceBuilder


def test_packet_preserves_multiple_events_flow_regimes_and_fdc():
    dates = [date(2020, 7, 1) + timedelta(days=i) for i in range(42)]
    observed = [10, 11, 12, 18, 40, 90, 55, 25, 14, 11, 10, 10, 10, 10] * 3
    simulated = [value * 0.92 for value in observed]
    precipitation = [0, 0, 4, 20, 12, 0, 0, 0, 0, 0, 0, 0, 0, 0] * 3
    bundle = HydrologicEvidenceBuilder(
        min_slice_samples=3,
        min_fdc_samples=10,
        min_event_samples=3,
        flood_threshold_quantile=0.85,
    ).build(
        window="calibration",
        dates=dates,
        observed=observed,
        simulated=simulated,
        precipitation=precipitation,
    )

    packet = build_diagnosis_packet(bundle)
    assert len(packet.flood_events) >= 2
    assert packet.flow_regimes["high"].metrics
    assert packet.fdc.metrics
    assert packet.overall.metrics["nse"] == bundle.overall.metrics["nse"]
