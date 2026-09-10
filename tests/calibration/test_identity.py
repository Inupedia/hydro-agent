import re
from datetime import date

from hydro_agent.calibration.identity import (
    calibration_experiment_id,
    development_validation_id,
)

IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def test_calibration_experiment_id_is_stable_safe_and_sensitive():
    start = date(2018, 1, 1)
    end = date(2019, 12, 31)
    first = calibration_experiment_id("run-1", "scheme-a", start, end)
    same = calibration_experiment_id("run-1", "scheme-a", start, end)
    changed = calibration_experiment_id("run-2", "scheme-a", start, end)
    assert first == same
    assert first != changed
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
