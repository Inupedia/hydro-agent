import pytest

from hydro_agent.models.xaj.calibrate_runtime import _effective_range
from hydro_agent.optimization.contracts import ParameterBounds, ParameterGuidance
from hydro_agent.optimization.param_groups import resolve_phase_param_names


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
    # local_scale=0.10 means 15% of the full 1.5-wide upstream span around current.
    assert low == pytest.approx(0.85)
    assert high == pytest.approx(1.15)
