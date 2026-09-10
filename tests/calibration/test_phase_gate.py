from hydro_agent.calibration.contracts import CalibrationPhase, PhaseGateStatus
from hydro_agent.calibration.phase_gate import HydrologicPhaseGate


def base_metrics(**overrides):
    metrics = {
        "nse": 0.40,
        "kge": 0.35,
        "volume_rel_error": 0.20,
        "annual_volume_bias_mae": 0.20,
        "seasonal_volume_bias_mae": 0.25,
        "recession_relative_error": 0.50,
        "event_recession_rel_error_median": 0.45,
        "flood_event_count": 6.0,
        "event_peak_rel_error_median": 0.40,
        "event_peak_timing_steps_median": 2.0,
        "event_volume_rel_error_median": 0.30,
    }
    metrics.update(overrides)
    return metrics


def test_water_balance_can_improve_even_when_nse_drops():
    gate = HydrologicPhaseGate()
    result = gate.evaluate(
        phase=CalibrationPhase.WATER_BALANCE,
        base_scheme_id="base",
        candidate_scheme_id="cand",
        experiment_id="e1",
        base_metrics=base_metrics(nse=0.45, volume_rel_error=0.30),
        candidate_metrics=base_metrics(
            nse=0.30,
            volume_rel_error=0.12,
            annual_volume_bias_mae=0.12,
            seasonal_volume_bias_mae=0.18,
        ),
    )
    assert result.status == PhaseGateStatus.CONTINUE
    assert result.adopt_candidate is True
    assert result.progress_metric == "water_balance_lexicographic_loss"


def test_water_balance_rejects_seasonal_gain_that_breaks_passed_total_volume():
    gate = HydrologicPhaseGate()
    result = gate.evaluate(
        phase=CalibrationPhase.WATER_BALANCE,
        base_scheme_id="base",
        candidate_scheme_id="cand",
        experiment_id="lowman-regression",
        base_metrics=base_metrics(
            volume_rel_error=0.0982,
            annual_volume_bias_mae=0.0893,
            seasonal_volume_bias_mae=1.161,
        ),
        candidate_metrics=base_metrics(
            volume_rel_error=0.3141,
            annual_volume_bias_mae=0.3170,
            seasonal_volume_bias_mae=0.828,
        ),
    )
    assert result.status == PhaseGateStatus.ROLLBACK
    assert result.adopt_candidate is False
    assert "water_balance_upstream_regression" in result.reasons
    assert result.metrics["base_water_balance_tier_rank"] == 1.0
    assert result.metrics["candidate_water_balance_tier_rank"] == 3.0


def test_water_balance_moves_to_next_tier_only_with_upstream_constraints_preserved():
    gate = HydrologicPhaseGate()
    annual_to_seasonal = gate.evaluate(
        phase=CalibrationPhase.WATER_BALANCE,
        base_scheme_id="base",
        candidate_scheme_id="annual-pass",
        experiment_id="annual-pass",
        base_metrics=base_metrics(
            volume_rel_error=0.09,
            annual_volume_bias_mae=0.25,
            seasonal_volume_bias_mae=0.40,
        ),
        candidate_metrics=base_metrics(
            volume_rel_error=0.095,
            annual_volume_bias_mae=0.14,
            seasonal_volume_bias_mae=0.40,
        ),
    )
    assert annual_to_seasonal.status == PhaseGateStatus.CONTINUE
    assert annual_to_seasonal.adopt_candidate is True
    assert annual_to_seasonal.metrics["candidate_water_balance_tier_rank"] == 1.0

    seasonal_pass = gate.evaluate(
        phase=CalibrationPhase.WATER_BALANCE,
        base_scheme_id="annual-pass",
        candidate_scheme_id="all-pass",
        experiment_id="seasonal-pass",
        base_metrics=base_metrics(
            volume_rel_error=0.095,
            annual_volume_bias_mae=0.14,
            seasonal_volume_bias_mae=0.40,
        ),
        candidate_metrics=base_metrics(
            volume_rel_error=0.095,
            annual_volume_bias_mae=0.14,
            seasonal_volume_bias_mae=0.18,
        ),
    )
    assert seasonal_pass.status == PhaseGateStatus.PHASE_PASS
    assert seasonal_pass.advance_phase is True


def test_recession_improvement_rolls_back_if_water_balance_regresses():
    gate = HydrologicPhaseGate()
    result = gate.evaluate(
        phase=CalibrationPhase.SOURCE_RECESSION,
        base_scheme_id="base",
        candidate_scheme_id="cand",
        experiment_id="e2",
        base_metrics=base_metrics(volume_rel_error=0.08, recession_relative_error=0.50),
        candidate_metrics=base_metrics(
            volume_rel_error=0.20,
            recession_relative_error=0.20,
            event_recession_rel_error_median=0.20,
        ),
    )
    assert result.status == PhaseGateStatus.ROLLBACK
    assert result.adopt_candidate is False
    assert "water_balance_regression" in result.reasons


def test_routing_requires_representative_flood_events():
    gate = HydrologicPhaseGate()
    result = gate.evaluate(
        phase=CalibrationPhase.ROUTING_EVENT,
        base_scheme_id="base",
        candidate_scheme_id="cand",
        experiment_id="e3",
        base_metrics=base_metrics(),
        candidate_metrics=base_metrics(
            flood_event_count=0.0,
            event_peak_rel_error_median=0.0,
            event_peak_timing_steps_median=0.0,
            event_volume_rel_error_median=0.0,
        ),
    )
    assert result.status == PhaseGateStatus.DATA_LIMIT
    assert result.stop_search is True


def test_joint_nse_gain_cannot_break_hydrologic_guardrails():
    gate = HydrologicPhaseGate()
    result = gate.evaluate(
        phase=CalibrationPhase.JOINT_REFINE,
        base_scheme_id="base",
        candidate_scheme_id="cand",
        experiment_id="e4",
        base_metrics=base_metrics(nse=0.55, volume_rel_error=0.08),
        candidate_metrics=base_metrics(
            nse=0.80,
            kge=0.70,
            volume_rel_error=0.30,
            event_peak_rel_error_median=0.20,
            event_peak_timing_steps_median=1.0,
            event_volume_rel_error_median=0.15,
        ),
    )
    assert result.status == PhaseGateStatus.ROLLBACK
    assert result.adopt_candidate is False
    assert "hydrologic_guardrail_failed" in result.reasons


def test_development_validation_needs_physics_statistics_and_standard_grade():
    gate = HydrologicPhaseGate()
    metrics = base_metrics(
        nse=0.75,
        kge=0.65,
        volume_rel_error=0.08,
        event_peak_rel_error_median=0.20,
        event_peak_timing_steps_median=1.0,
        event_volume_rel_error_median=0.15,
    )
    passed = gate.evaluate(
        phase=CalibrationPhase.DEVELOPMENT_VALIDATION,
        base_scheme_id="best",
        candidate_scheme_id="best",
        experiment_id="dev",
        base_metrics=metrics,
        candidate_metrics=metrics,
        development_grade_ok=True,
    )
    failed = gate.evaluate(
        phase=CalibrationPhase.DEVELOPMENT_VALIDATION,
        base_scheme_id="best",
        candidate_scheme_id="best",
        experiment_id="dev2",
        base_metrics=metrics,
        candidate_metrics=metrics,
        development_grade_ok=False,
    )
    assert passed.status == PhaseGateStatus.PHASE_PASS
    assert passed.advance_phase is True
    assert failed.status != PhaseGateStatus.PHASE_PASS
