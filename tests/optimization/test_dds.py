import json

import pytest

from hydro_agent.optimization.dds import DdsCheckpoint, optimize_dds


def test_dds_respects_budget_and_improves_simple_objective():
    def score(params):
        x = params["x"]
        y = params["y"]
        return -((x - 0.25) ** 2 + (y - 0.75) ** 2)

    result = optimize_dds(
        bounds={"x": (0.0, 1.0), "y": (0.0, 1.0)},
        score_fn=score,
        evaluation_budget=128,
        random_seed=20260913,
        initial_parameters={"x": 0.9, "y": 0.1},
    )

    assert result.evaluations == 128
    assert result.best_score > -0.02
    assert abs(result.best_parameters["x"] - 0.25) < 0.2
    assert abs(result.best_parameters["y"] - 0.75) < 0.2
    assert result.improvement_history
    assert result.checkpoint.evaluations == 128


def test_dds_is_reproducible_for_same_seed():
    kwargs = dict(
        bounds={"x": (-1.0, 1.0)},
        score_fn=lambda p: -((p["x"] - 0.1) ** 2),
        evaluation_budget=32,
        random_seed=7,
        initial_parameters={"x": 0.8},
    )
    first = optimize_dds(**kwargs)
    second = optimize_dds(**kwargs)
    assert first.best_parameters == second.best_parameters
    assert first.best_score == second.best_score
    assert first.improvement_history == second.improvement_history


def test_dds_resume_matches_uninterrupted_run_without_replaying_completed_calls():
    bounds = {"x": (-1.0, 1.0), "y": (-1.0, 1.0)}
    budget = 64

    def objective(params):
        return -((params["x"] - 0.2) ** 2 + (params["y"] + 0.35) ** 2)

    uninterrupted = optimize_dds(
        bounds=bounds,
        score_fn=objective,
        evaluation_budget=budget,
        random_seed=42,
        initial_parameters={"x": 0.9, "y": 0.8},
    )

    captured: DdsCheckpoint | None = None
    first_run_calls = 0

    class SimulatedInterruption(RuntimeError):
        pass

    def first_score(params):
        nonlocal first_run_calls
        first_run_calls += 1
        return objective(params)

    def checkpoint_and_interrupt(state: DdsCheckpoint):
        nonlocal captured
        captured = state
        if state.evaluations == 17:
            raise SimulatedInterruption("worker stopped after durable checkpoint")

    with pytest.raises(SimulatedInterruption):
        optimize_dds(
            bounds=bounds,
            score_fn=first_score,
            evaluation_budget=budget,
            random_seed=42,
            initial_parameters={"x": 0.9, "y": 0.8},
            checkpoint_fn=checkpoint_and_interrupt,
        )

    assert captured is not None
    assert captured.evaluations == 17
    assert first_run_calls == 17

    # The persistence representation must be strict JSON, not a Python-only RNG object.
    persisted = json.loads(json.dumps(captured.as_dict(), allow_nan=False))
    restored = DdsCheckpoint.from_dict(persisted)
    resumed_calls = 0

    def resumed_score(params):
        nonlocal resumed_calls
        resumed_calls += 1
        return objective(params)

    resumed = optimize_dds(
        bounds=bounds,
        score_fn=resumed_score,
        evaluation_budget=budget,
        random_seed=42,
        initial_parameters={"x": 0.9, "y": 0.8},
        resume_from=restored,
    )

    assert resumed_calls == budget - 17
    assert first_run_calls + resumed_calls == budget
    assert resumed.evaluations == uninterrupted.evaluations == budget
    assert resumed.best_parameters == uninterrupted.best_parameters
    assert resumed.best_score == uninterrupted.best_score
    assert resumed.improvement_history == uninterrupted.improvement_history


def test_dds_rejects_checkpoint_from_different_search_contract():
    checkpoint = optimize_dds(
        bounds={"x": (0.0, 1.0)},
        score_fn=lambda p: -((p["x"] - 0.4) ** 2),
        evaluation_budget=8,
        random_seed=3,
    ).checkpoint

    with pytest.raises(ValueError, match="parameter/bounds contract mismatch"):
        optimize_dds(
            bounds={"x": (0.0, 2.0)},
            score_fn=lambda p: -((p["x"] - 0.4) ** 2),
            evaluation_budget=8,
            random_seed=3,
            resume_from=checkpoint,
        )
