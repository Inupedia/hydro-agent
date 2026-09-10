from hydro_agent.calibration.contracts import CalibrationPhase
from hydro_agent.calibration.development import infer_rework_phase


def base_metrics():
    return {
        "volume_rel_error": 0.05,
        "annual_volume_bias_mae": 0.08,
        "seasonal_volume_bias_mae": 0.10,
        "recession_relative_error": 0.12,
        "event_recession_rel_error_median": 0.15,
        "event_peak_rel_error_median": 0.12,
        "event_peak_timing_steps_median": 0.5,
        "event_volume_rel_error_median": 0.10,
        "nse": 0.40,
        "kge": 0.20,
    }


def test_development_failure_routes_to_water_balance_first():
    metrics = base_metrics()
    metrics["annual_volume_bias_mae"] = 0.25
    metrics["event_peak_rel_error_median"] = 0.80
    assert infer_rework_phase(metrics) == CalibrationPhase.WATER_BALANCE


def test_development_failure_routes_to_recession_after_water_balance_passes():
    metrics = base_metrics()
    metrics["recession_relative_error"] = 0.45
    metrics["event_peak_rel_error_median"] = 0.80
    assert infer_rework_phase(metrics) == CalibrationPhase.SOURCE_RECESSION


def test_development_failure_routes_to_routing_after_upstream_processes_pass():
    metrics = base_metrics()
    metrics["event_peak_timing_steps_median"] = 3.0
    assert infer_rework_phase(metrics) == CalibrationPhase.ROUTING_EVENT


def test_development_failure_routes_to_joint_when_physics_pass_but_skill_does_not():
    metrics = base_metrics()
    assert infer_rework_phase(metrics) == CalibrationPhase.JOINT_REFINE
