from hydro_agent.optimization.directional_probe import run_directional_probe


def _routing_evaluator(params):
    lag = 4.0 - params["L"]
    return {
        "objective_value": 1.0 - abs(lag) * 0.1,
        "peak_timing_lag_steps": lag,
        "volume_relative_error": 0.01,
        "high_flow_relative_error": 0.02,
        "evidence_ids": ("event-001", "event-002"),
    }


def test_probe_supports_direction_when_positive_perturbation_improves_expected_signature():
    result = run_directional_probe(
        baseline={"L": 3.0},
        bounds={"L": (0.0, 10.0)},
        parameters=("L",),
        relative_step=0.10,
        evaluate=_routing_evaluator,
        requested_direction="accelerate_routing",
    )

    assert result.status == "supported"
    assert result.parameter_effects
    assert result.supporting_parameters == ("L",)
    assert result.contradictory_parameters == ()
    assert result.evidence_ids == ("event-001", "event-002")


def test_probe_never_moves_outside_absolute_bounds():
    seen = []

    def evaluate(params):
        seen.append(params["L"])
        return {
            "objective_value": 1.0,
            "peak_timing_lag_steps": 1.0,
            "volume_relative_error": 0.0,
            "high_flow_relative_error": 0.0,
        }

    run_directional_probe(
        baseline={"L": 9.8},
        bounds={"L": (0.0, 10.0)},
        parameters=("L",),
        relative_step=0.10,
        evaluate=evaluate,
        requested_direction="accelerate_routing",
    )

    assert min(seen) >= 0.0
    assert max(seen) <= 10.0
    assert 10.0 in seen


def test_probe_returns_inconclusive_when_active_parameters_disagree():
    def evaluate(params):
        if params["A"] != 0.5:
            lag = 1.0 - (params["A"] - 0.5) * 4.0
        else:
            lag = 1.0 + (params["B"] - 0.5) * 4.0
        return {
            "objective_value": 1.0,
            "peak_timing_lag_steps": lag,
            "volume_relative_error": 0.0,
            "high_flow_relative_error": 0.0,
        }

    result = run_directional_probe(
        baseline={"A": 0.5, "B": 0.5},
        bounds={"A": (0.0, 1.0), "B": (0.0, 1.0)},
        parameters=("A", "B"),
        relative_step=0.10,
        evaluate=evaluate,
        requested_direction="accelerate_routing",
    )

    assert result.status == "inconclusive"
    assert "A" in result.supporting_parameters
    assert "B" in result.contradictory_parameters
