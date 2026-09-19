from datetime import date, timedelta

from hydro_agent.agent.hydrologic_evidence import HydrologicEvidence
from hydro_agent.evaluation.diagnosis_packet import build_diagnosis_packet
from hydro_agent.evaluation.evidence import HydrologicEvidenceBuilder
from hydro_agent.optimization.calibration_scientist import interpret_evidence


def test_hydrologic_evidence_round_trips_diagnosis_metrics():
    evidence = HydrologicEvidence.from_diagnosis(
        {
            "hypothesis": "TIMING",
            "phenomenon": "洪峰偏晚",
            "recommended_param_groups": ["routing"],
            "recommended_strategy_id": "xaj-local-refine-v1",
            "metrics": {
                "nse": 0.35,
                "pbias_percent": 4.2,
                "peak_ratio": 1.12,
                "peak_timing_lag_days": 1.0,
            },
            "notes": ["held-out diagnosis"],
            "local_boundary_hits": ["CS"],
        }
    )
    assert evidence.overall.nse == 0.35
    assert evidence.water_balance.pbias_percent == 4.2
    assert evidence.flood_events[0].timing_lag_days == 1.0
    assert evidence.recommended_param_groups == ("routing",)

    projected = evidence.as_diagnosis_dict()
    assert projected["metrics"]["nse"] == 0.35
    assert projected["metrics"]["peak_timing_lag_days"] == 1.0
    assert projected["local_boundary_hits"] == ["CS"]

    reading = interpret_evidence(evidence)
    assert any(item.startswith("nse=") for item in reading.metrics_summary)
    assert "flood_peak_and_timing" in reading.required_evidence
    assert "water_balance" in reading.required_evidence



def test_hydrologic_evidence_preserves_full_diagnosis_packet_and_legacy_views():
    dates = [date(2020, 7, 1) + timedelta(days=i) for i in range(42)]
    observed = [10, 11, 12, 18, 40, 90, 55, 25, 14, 11, 10, 10, 10, 10] * 3
    simulated = [value * 0.9 for value in observed]
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
    packet = build_diagnosis_packet(bundle, basin_attributes={"area_km2": 100.0})

    evidence = HydrologicEvidence.from_diagnosis(
        {"hypothesis": "UNKNOWN"},
        diagnosis_packet=packet,
    )

    assert evidence.diagnosis_packet == packet
    assert len(evidence.flood_events) == len(packet.flood_events)
    assert evidence.flood_events[0].event_id == packet.flood_events[0].event_id
    assert evidence.flood_events[0].peak_relative_error is not None
    assert evidence.high_flow.extras
    assert evidence.low_flow.extras
    assert evidence.basin_attributes["area_km2"] == 100.0
    assert evidence.as_diagnosis_dict()["diagnosis_packet"]["window"] == "calibration"



def test_hydrologic_evidence_hydrates_packet_from_raw_diagnosis_dict():
    dates = [date(2020, 7, 1) + timedelta(days=i) for i in range(42)]
    observed = [10, 11, 12, 18, 40, 90, 55, 25, 14, 11, 10, 10, 10, 10] * 3
    simulated = [value * 0.9 for value in observed]
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

    evidence = HydrologicEvidence.from_diagnosis(
        {
            "hypothesis": "MODEL",
            "diagnosis_packet": packet.model_dump(mode="json"),
        }
    )

    assert evidence.diagnosis_packet == packet
    assert len(evidence.flood_events) == len(packet.flood_events)
