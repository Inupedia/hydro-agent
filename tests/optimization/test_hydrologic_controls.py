import pytest

from hydro_agent.models.xaj.calibrate_runtime import _effective_range, _normalized_phase_loss
from hydro_agent.models.xaj.upstream import load_calibratable_params
from hydro_agent.optimization.contracts import ParameterBounds, ParameterGuidance
from hydro_agent.optimization.param_groups import resolve_phase_param_names


def _metrics(**overrides):
    values = {
        "volume_rel_error": 0.08,
        "annual_volume_bias_mae": 0.10,
        "seasonal_volume_bias_mae": 0.18,
        "recession_relative_error": 0.20,
        "event_recession_rel_error_median": 0.20,
        "event_peak_rel_error_median": 0.20,
        "event_peak_timing_steps_median": 1.0,
        "event_volume_rel_error_median": 0.15,
    }
    values.update(overrides)
    return values


def test_staged_xaj_objectives_have_disjoint_phase_whitelists():
    assert resolve_phase_param_names("water_balance") == ("K", "B", "DM")
    assert resolve_phase_param_names("recession") == ("SM", "KI", "KG")
    assert resolve_phase_param_names("routing_event") == ("CS", "CI", "L")
    assert resolve_phase_param_names("joint") == (
        "K",
        "B",
        "DM",
        "SM",
        "KI",
        "KG",
        "CS",
        "CI",
        "L",
    )
    assert resolve_phase_param_names("nse") is None


def test_phase_whitelist_is_intersected_with_teacher_calibratable_coordinates():
    calibratable = set(load_calibratable_params())
    p2 = tuple(
        name
        for name in resolve_phase_param_names("water_balance") or ()
        if name in calibratable
    )
    p3 = tuple(
        name for name in resolve_phase_param_names("recession") or () if name in calibratable
    )
    p4 = tuple(
        name
        for name in resolve_phase_param_names("routing_event") or ()
        if name in calibratable
    )

    assert p2 == ("K", "B", "DM")
    assert p3 == ("SM", "KI", "KG")
    # L belongs to the P4 hydrologic phase, but the pinned teacher kernel marks LAG
    # non-calibratable. Do not advertise it to the Agent until that kernel policy changes.
    assert p4 == ("CS", "CI")


def test_recession_optimizer_penalizes_candidates_that_break_p2():
    feasible = _normalized_phase_loss(_metrics(recession_relative_error=0.25), "recession")
    broken_water = _normalized_phase_loss(
        _metrics(
            seasonal_volume_bias_mae=0.30,
            recession_relative_error=0.10,
            event_recession_rel_error_median=0.10,
        ),
        "recession",
    )

    assert feasible <= 1.0
    assert broken_water > 1000.0


def test_routing_optimizer_penalizes_candidates_that_break_p3():
    feasible = _normalized_phase_loss(_metrics(event_peak_rel_error_median=0.25), "routing_event")
    broken_recession = _normalized_phase_loss(
        _metrics(
            recession_relative_error=0.40,
            event_recession_rel_error_median=0.35,
            event_peak_rel_error_median=0.10,
            event_peak_timing_steps_median=0.0,
            event_volume_rel_error_median=0.10,
        ),
        "routing_event",
    )

    assert feasible <= 1.0
    assert broken_recession > 1000.0


def test_joint_optimizer_uses_same_strict_upstream_envelope_as_gate():
    feasible = _normalized_phase_loss(_metrics(), "joint")
    broken_annual = _normalized_phase_loss(
        _metrics(annual_volume_bias_mae=0.20),
        "joint",
    )
    broken_recession = _normalized_phase_loss(
        _metrics(recession_relative_error=0.40),
        "joint",
    )

    assert feasible <= 1.0
    assert broken_annual > 1.0
    assert broken_recession > 1.0


def test_parameter_guidance_constrains_search_relative_to_current_value():
    ranges = {"K": (0.50, 2.00), "B": (0.10, 0.90), "DM": (10.0, 150.0)}
    base = {"K": 0.75, "B": 0.25, "DM": 40.0}
    guidance = ParameterGuidance(
        directions={"K": "decrease", "B": "increase"},
        bounds={"B": ParameterBounds(max_value=0.40)},
        frozen_parameters=("DM",),
    )

    assert _effective_range(
        "K", ranges, base_parameters=base, local_scale=None, guidance=guidance
    ) == pytest.approx((0.50, 0.75))
    assert _effective_range(
        "B", ranges, base_parameters=base, local_scale=None, guidance=guidance
    ) == pytest.approx((0.25, 0.40))
    assert _effective_range(
        "DM", ranges, base_parameters=base, local_scale=None, guidance=guidance
    ) == pytest.approx((40.0, 40.0))


def test_explicit_bounds_are_intersected_with_upstream_and_local_ranges():
    ranges = {"K": (0.50, 2.00)}
    base = {"K": 1.00}
    guidance = ParameterGuidance(
        bounds={"K": ParameterBounds(min_value=0.80, max_value=1.20)}
    )
    low, high = _effective_range(
        "K", ranges, base_parameters=base, local_scale=0.10, guidance=guidance
    )
    # local_scale=0.10 means 10% of the full 1.5-wide upstream span around current.
    assert low == pytest.approx(0.85)
    assert high == pytest.approx(1.15)
