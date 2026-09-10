from hydro_agent.calibration.contracts import CalibrationPhase, SearchProgressPoint
from hydro_agent.calibration.convergence import SearchConvergenceController


def point(experiment_id: str, value: float, *, phase=CalibrationPhase.WATER_BALANCE):
    return SearchProgressPoint(
        experiment_id=experiment_id,
        phase=phase,
        value=value,
        higher_is_better=False,
    )


def test_duplicate_gate_never_becomes_a_new_curve_point():
    controller = SearchConvergenceController()
    history = (point("e1", 2.0), point("e2", 1.5), point("e3", 1.2))
    result = controller.evaluate(history, point("e3", 1.2))
    assert result.duplicate is True
    assert result.plateau is False
    assert result.unique_points == 3


def test_no_change_search_does_not_add_scientific_point():
    controller = SearchConvergenceController()
    history = (point("e1", 2.0), point("e2", 1.5), point("e3", 1.2))
    first = controller.evaluate_no_change(
        history,
        phase=CalibrationPhase.WATER_BALANCE,
        repeated=False,
    )
    repeated = controller.evaluate_no_change(
        history,
        phase=CalibrationPhase.WATER_BALANCE,
        repeated=True,
    )
    assert first.unique_points == 3
    assert first.plateau is False
    assert first.reason == "no_parameter_change_try_alternate_strategy"
    assert repeated.unique_points == 3
    assert repeated.plateau is True
    assert repeated.reason == "repeated_no_parameter_change"


def test_plateau_requires_four_unique_experiments():
    controller = SearchConvergenceController()
    history = (point("e1", 1.000), point("e2", 0.995), point("e3", 0.991))
    result = controller.evaluate(history, point("e4", 0.990))
    assert result.duplicate is False
    assert result.unique_points == 4
    assert result.plateau is True


def test_same_phase_only_contributes_to_plateau():
    controller = SearchConvergenceController()
    history = (
        point("p2-1", 1.2),
        point("p3-1", 1.0, phase=CalibrationPhase.SOURCE_RECESSION),
        point("p3-2", 0.9, phase=CalibrationPhase.SOURCE_RECESSION),
    )
    result = controller.evaluate(history, point("p2-2", 1.1))
    assert result.unique_points == 2
    assert result.plateau is False
