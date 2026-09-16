from hydro_agent.agent.hydrologic_evidence import HydrologicEvidence
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
