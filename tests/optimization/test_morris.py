import pytest

from hydro_agent.optimization.morris import screen_morris


def test_morris_ranks_normalized_elementary_effects_and_builds_active_set():
    result = screen_morris(
        bounds={"x": (0.0, 1.0), "y": (0.0, 100.0), "z": (-5.0, 5.0)},
        score_fn=lambda p: 10.0 * p["x"] + 0.002 * p["y"],
        trajectories=8,
        levels=6,
        random_seed=7,
        min_relative_mu_star=0.10,
        min_effects_per_parameter=2,
        min_active_parameters=1,
        active_parameter_limit=2,
    )

    by_name = {item.name: item for item in result.sensitivities}
    assert by_name["x"].mu_star == pytest.approx(10.0)
    # Physical y spans 0..100, but Morris effects are taken in normalized
    # coordinates, so its effect is 0.2 and directly comparable to x.
    assert by_name["y"].mu_star == pytest.approx(0.2)
    assert by_name["z"].mu_star == pytest.approx(0.0)
    assert result.active_parameters == ("x",)
    assert set(result.screened_out_parameters) == {"y", "z"}


def test_morris_is_deterministic_for_fixed_seed():
    kwargs = dict(
        bounds={"a": (0.0, 2.0), "b": (0.0, 1.0), "c": (0.0, 3.0)},
        score_fn=lambda p: p["a"] ** 2 + 0.5 * p["b"] * p["c"],
        trajectories=6,
        levels=6,
        random_seed=20260913,
        min_active_parameters=1,
    )
    first = screen_morris(**kwargs)
    second = screen_morris(**kwargs)
    assert first.as_dict() == second.as_dict()


def test_morris_fails_open_when_no_sensitivity_signal_exists():
    result = screen_morris(
        bounds={"a": (0.0, 1.0), "b": (0.0, 1.0), "c": (0.0, 1.0)},
        score_fn=lambda _p: 1.0,
        trajectories=4,
        levels=6,
        random_seed=3,
        min_active_parameters=1,
        active_parameter_limit=1,
    )
    assert result.active_parameters == ("a", "b", "c")
    assert result.screened_out_parameters == ()


def test_morris_keeps_parameters_with_insufficient_valid_effects():
    result = screen_morris(
        bounds={"a": (0.0, 1.0), "b": (0.0, 1.0)},
        score_fn=lambda _p: None,
        trajectories=3,
        levels=6,
        random_seed=5,
        min_effects_per_parameter=2,
        min_active_parameters=1,
        active_parameter_limit=1,
    )
    assert result.active_parameters == ("a", "b")
    assert set(result.insufficient_evidence_parameters) == {"a", "b"}
    assert all(item.status == "insufficient_evidence" for item in result.sensitivities)
