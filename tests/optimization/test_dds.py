from hydro_agent.optimization.dds import optimize_dds


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


def test_dds_is_reproducible_for_same_seed():
    kwargs = dict(
        bounds={"x": (-1.0, 1.0)},
        score_fn=lambda p: -(p["x"] - 0.1) ** 2,
        evaluation_budget=32,
        random_seed=7,
        initial_parameters={"x": 0.8},
    )
    first = optimize_dds(**kwargs)
    second = optimize_dds(**kwargs)
    assert first.best_parameters == second.best_parameters
    assert first.best_score == second.best_score
    assert first.improvement_history == second.improvement_history
