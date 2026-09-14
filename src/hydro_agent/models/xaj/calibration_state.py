"""Durable per-workspace state for resumable XAJ calibration.

The execution workspace is the audit boundary for one A07 action run. State in
``work/calibration-state`` is not promoted as a scientific result; it only lets a
trusted numerical runtime continue the same preregistered search after a worker
interruption without replaying completed model evaluations.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TypeAlias

from hydro_agent.optimization.dds import DdsCheckpoint
from hydro_agent.optimization.morris import MorrisCheckpoint

CacheKey: TypeAlias = tuple[tuple[str, float], ...]
CacheValue: TypeAlias = tuple[float | None, list[float], dict[str, float]]
EvaluationCache: TypeAlias = dict[CacheKey, CacheValue]

_STATE_DIR = "calibration-state"
_DDS_CHECKPOINT = "dds-checkpoint.json"
_MORRIS_CHECKPOINT = "morris-checkpoint.json"
_SCREENING_RESULT = "screening-result.json"


def state_root(workspace: Path) -> Path:
    root = Path(workspace) / "work" / _STATE_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _cache_digest(key: CacheKey) -> str:
    payload = json.dumps(list(key), separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _evaluation_directory(workspace: Path) -> Path:
    return state_root(workspace) / "evaluations"


def evaluation_count(workspace: Path) -> int:
    """Count durable completed physical simulations without loading hydrographs."""

    directory = _evaluation_directory(workspace)
    if not directory.is_dir():
        return 0
    return sum(1 for path in directory.glob("*.json") if path.is_file())


def load_evaluation_cache(workspace: Path) -> EvaluationCache:
    directory = _evaluation_directory(workspace)
    if not directory.is_dir():
        return {}
    cache: EvaluationCache = {}
    for path in sorted(directory.glob("*.json")):
        raw = _read_json(path)
        if not isinstance(raw, dict):
            raise ValueError(f"invalid calibration cache entry: {path.name}")
        raw_key = raw.get("key")
        raw_full = raw.get("full_values")
        raw_parameters = raw.get("parameters")
        if not isinstance(raw_key, list) or not isinstance(raw_full, list) or not isinstance(
            raw_parameters, dict
        ):
            raise ValueError(f"invalid calibration cache entry: {path.name}")
        key = tuple((str(item[0]), float(item[1])) for item in raw_key)
        score = raw.get("score")
        cache[key] = (
            float(score) if score is not None else None,
            [float(value) for value in raw_full],
            {str(name): float(value) for name, value in raw_parameters.items()},
        )
    return cache


def persist_evaluation(
    workspace: Path,
    *,
    key: CacheKey,
    score: float | None,
    full_values: list[float],
    parameters: dict[str, float],
) -> None:
    directory = _evaluation_directory(workspace)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_cache_digest(key)}.json"
    if path.exists():
        return
    _atomic_write_json(
        path,
        {
            "key": [list(item) for item in key],
            "score": score,
            "full_values": [float(value) for value in full_values],
            "parameters": {str(name): float(value) for name, value in parameters.items()},
        },
    )


def load_dds_checkpoint(workspace: Path) -> DdsCheckpoint | None:
    path = state_root(workspace) / _DDS_CHECKPOINT
    if not path.is_file():
        return None
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ValueError("invalid DDS checkpoint payload")
    return DdsCheckpoint.from_dict(raw)


def save_dds_checkpoint(workspace: Path, checkpoint: DdsCheckpoint) -> None:
    _atomic_write_json(state_root(workspace) / _DDS_CHECKPOINT, checkpoint.as_dict())


def load_morris_checkpoint(workspace: Path) -> MorrisCheckpoint | None:
    path = state_root(workspace) / _MORRIS_CHECKPOINT
    if not path.is_file():
        return None
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ValueError("invalid Morris checkpoint payload")
    return MorrisCheckpoint.from_dict(raw)


def save_morris_checkpoint(workspace: Path, checkpoint: MorrisCheckpoint) -> None:
    _atomic_write_json(state_root(workspace) / _MORRIS_CHECKPOINT, checkpoint.as_dict())


def load_screening_result(workspace: Path) -> dict[str, object] | None:
    path = state_root(workspace) / _SCREENING_RESULT
    if not path.is_file():
        return None
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ValueError("invalid screening result payload")
    return dict(raw)


def save_screening_result(workspace: Path, payload: dict[str, object]) -> None:
    _atomic_write_json(state_root(workspace) / _SCREENING_RESULT, payload)


def has_resumable_state(workspace: Path) -> bool:
    root = state_root(workspace)
    return evaluation_count(workspace) > 0 or any(
        (root / name).is_file()
        for name in (_DDS_CHECKPOINT, _MORRIS_CHECKPOINT, _SCREENING_RESULT)
    )
