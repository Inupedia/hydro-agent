import pytest

from hydro_agent.optimization.sceua import optimize_sceua

pytest.importorskip("numpy")


def test_sceua_converges_and_is_deterministic():
    def score(params):
        return -((params["x"] - 1.0) ** 2 + (params["y"] + 2.0) ** 2)

    kwargs = dict(
        bounds={"x": (-5.0, 5.0), "y": (-5.0, 5.0)},
        score_fn=score,
        evaluation_budget=100,
        random_seed=1,
        initial_parameters={"x": 4.0, "y": 4.0},
    )
    first = optimize_sceua(**kwargs)
    second = optimize_sceua(**kwargs)

    assert first == second
    assert first.evaluations == 100
    assert first.best_score > -0.02
    assert first.best_parameters["x"] == pytest.approx(1.0, abs=0.15)
    assert first.best_parameters["y"] == pytest.approx(-2.0, abs=0.15)
    assert first.improvement_history


def test_sceua_rejects_empty_bounds():
    with pytest.raises(ValueError, match="at least one"):
        optimize_sceua(bounds={}, score_fn=lambda _p: 0.0, evaluation_budget=10, random_seed=1)
