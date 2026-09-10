from __future__ import annotations

import hashlib
from datetime import date


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:24]
    return f"{prefix}-{digest}"


def calibration_experiment_id(
    action_run_id: str,
    candidate_scheme_id: str,
    development_start: date,
    development_end: date,
) -> str:
    """Return a stable, repository-safe id for one numerical experiment."""

    return _stable_id(
        "exp",
        action_run_id,
        candidate_scheme_id,
        development_start.isoformat(),
        development_end.isoformat(),
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
