import json

import pytest

from hydro_agent.optimization.morris import (
    MorrisCheckpoint,
    morris_direction_evidence,
    screen_morris,
)


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


def test_morris_resume_matches_uninterrupted_without_replaying_score_calls():
    bounds = {"a": (0.0, 2.0), "b": (-1.0, 1.0), "c": (0.0, 3.0)}

    def objective(params):
        return 2.0 * params["a"] - params["b"] ** 2 + 0.25 * params["c"]

    uninterrupted_calls = 0

    def uninterrupted_score(params):
        nonlocal uninterrupted_calls
        uninterrupted_calls += 1
        return objective(params)

    uninterrupted = screen_morris(
        bounds=bounds,
        score_fn=uninterrupted_score,
        trajectories=6,
        levels=6,
        random_seed=42,
        min_active_parameters=1,
    )

    class SimulatedInterruption(RuntimeError):
        pass

    first_calls = 0
    captured: MorrisCheckpoint | None = None

    def interrupted_score(params):
        nonlocal first_calls
        first_calls += 1
        return objective(params)

    def checkpoint(state: MorrisCheckpoint):
        nonlocal captured
        captured = MorrisCheckpoint.from_dict(json.loads(json.dumps(state.as_dict())))
        if state.score_calls == 9:
            raise SimulatedInterruption("worker stopped after durable Morris checkpoint")

    with pytest.raises(SimulatedInterruption):
        screen_morris(
            bounds=bounds,
            score_fn=interrupted_score,
            trajectories=6,
            levels=6,
            random_seed=42,
            min_active_parameters=1,
            checkpoint_fn=checkpoint,
        )

    assert captured is not None
    assert captured.score_calls == 9

    resumed_calls = 0

    def resumed_score(params):
        nonlocal resumed_calls
        resumed_calls += 1
        return objective(params)

    resumed = screen_morris(
        bounds=bounds,
        score_fn=resumed_score,
        trajectories=6,
        levels=6,
        random_seed=42,
        min_active_parameters=1,
        resume_from=captured,
    )

    assert resumed.as_dict() == uninterrupted.as_dict()
    assert first_calls + resumed_calls == uninterrupted_calls


def test_morris_rejects_checkpoint_from_different_screening_contract():
    checkpoint = screen_morris(
        bounds={"x": (0.0, 1.0), "y": (0.0, 1.0)},
        score_fn=lambda p: p["x"] + p["y"],
        trajectories=3,
        levels=6,
        random_seed=3,
        min_active_parameters=1,
    ).checkpoint
    assert checkpoint is not None

    with pytest.raises(ValueError, match="parameter/bounds contract mismatch"):
        screen_morris(
            bounds={"x": (0.0, 2.0), "y": (0.0, 1.0)},
            score_fn=lambda p: p["x"] + p["y"],
            trajectories=3,
            levels=6,
            random_seed=3,
            min_active_parameters=1,
            resume_from=checkpoint,
        )



def test_morris_direction_adapter_preserves_importance_and_probe_status():
    screening = screen_morris(
        bounds={"L": (0.0, 10.0), "K": (0.0, 1.0)},
        score_fn=lambda p: 2.0 * p["L"] + 0.1 * p["K"],
        trajectories=4,
        levels=6,
        random_seed=7,
        min_active_parameters=1,
    )
    evidence = morris_direction_evidence(screening, direction_probe_status="supported")
    by_name = {item["parameter"]: item for item in evidence}

    assert by_name["L"]["mu_star"] is not None
    assert by_name["L"]["effects_count"] >= 1
    assert by_name["L"]["direction_probe_status"] == "supported"
