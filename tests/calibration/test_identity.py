import re
from datetime import date

from hydro_agent.calibration.identity import (
    calibration_experiment_id,
    development_validation_id,
    parameter_signature,
)

IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def experiment_id(*, candidate, strategy="xaj-local-refine-v1"):
    return calibration_experiment_id(
        phase="P2_WATER_BALANCE",
        base_parameters={"K": 1.0, "B": 0.3},
        candidate_parameters=candidate,
        strategy_id=strategy,
        objective="water_balance",
        calibration_start=date(2011, 1, 1),
        calibration_end=date(2017, 12, 31),
    )


def test_parameter_signature_is_order_invariant():
    assert parameter_signature({"K": 1.0, "B": 0.3}) == parameter_signature(
        {"B": 0.3, "K": 1.0}
    )


def test_calibration_experiment_id_tracks_scientific_outcome_not_runtime_id():
    first = experiment_id(candidate={"K": 0.9, "B": 0.35})
    same = experiment_id(candidate={"B": 0.35, "K": 0.9})
    changed_vector = experiment_id(candidate={"K": 0.85, "B": 0.35})
    changed_strategy = experiment_id(
        candidate={"K": 0.9, "B": 0.35},
        strategy="xaj-bounded-v1",
    )
    assert first == same
    assert first != changed_vector
    assert first != changed_strategy
    assert first.startswith("exp-")
    assert IDENTIFIER_RE.fullmatch(first)


def test_development_validation_id_is_separate_namespace():
    value = development_validation_id(
        "scheme-a",
        date(2018, 1, 1),
        date(2019, 12, 31),
    )
    assert value.startswith("dev-")
    assert IDENTIFIER_RE.fullmatch(value)
