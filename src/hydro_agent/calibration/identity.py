from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:24]
    return f"{prefix}-{digest}"


def parameter_signature(parameters: Mapping[str, object]) -> str:
    """Return a stable signature for one physical parameter vector."""

    raw = json.dumps(
        dict(parameters),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def calibration_experiment_id(
    *,
    phase: str,
    base_parameters: Mapping[str, object],
    candidate_parameters: Mapping[str, object],
    strategy_id: str,
    objective: str,
    calibration_start: date,
    calibration_end: date,
) -> str:
    """Identify one scientific calibration outcome, independent of runtime ids.

    Re-running the same phase/search strategy from the same physical base and
    returning the same candidate vector is the same experiment for convergence
    purposes. ``action_run_id`` remains audit metadata, but it must not create a
    fake new point on the scientific progress curve.
    """

    return _stable_id(
        "exp",
        phase,
        parameter_signature(base_parameters),
        parameter_signature(candidate_parameters),
        strategy_id,
        objective,
        calibration_start.isoformat(),
        calibration_end.isoformat(),
    )


def development_validation_id(
    scheme_id: str,
    development_start: date,
    development_end: date,
) -> str:
    """Return a stable id for one development-validation evaluation."""

    return _stable_id(
        "dev",
        scheme_id,
        development_start.isoformat(),
        development_end.isoformat(),
    )
