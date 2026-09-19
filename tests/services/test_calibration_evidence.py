from hydro_agent.services.calibration_evidence import apply_calibration_evidence_to_diagnosis


def test_calibration_evidence_promotes_diagnosis_packet_for_agent_context():
    packet = {
        "window": "calibration",
        "overall": {"status": "available", "sample_count": 20, "metrics": {"nse": 0.4}, "notes": []},
        "water_balance": {"status": "available", "sample_count": 20, "metrics": {"pbias_percent": 2.0}, "notes": []},
        "flow_regimes": {},
        "fdc": {"status": "available", "sample_count": 20, "metrics": {}, "notes": []},
        "seasons": {},
        "years": {},
        "flood_events": [],
        "data_quality": {
            "total_count": 20,
            "valid_count": 20,
            "dropped_count": 0,
            "coverage": 1.0,
            "dropped_by_reason": {},
        },
        "basin_attributes": {},
    }
    result = apply_calibration_evidence_to_diagnosis(
        {"metrics": {}, "notes": []},
        {
            "provenance": {"model_id": "xaj"},
            "overall": {
                "status": "available",
                "metrics": {
                    "nse": 0.4,
                    "kge": 0.3,
                    "pbias_percent": 2.0,
                    "mae": 1.0,
                    "rmse": 1.2,
                    "peak_ratio": 0.9,
                    "peak_timing_lag_steps": 0.0,
                },
            },
            "quality": {"valid_count": 20},
            "diagnosis_packet": packet,
        },
        dc_bing_floor=0.5,
    )

    assert result["diagnosis_packet"] == packet
    assert result["calibration_evidence"]["diagnosis_packet"] == packet
