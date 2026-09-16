"""Hydro-Agent workflow bindings stored outside portable Skill packages."""

from __future__ import annotations

import json
from pathlib import Path

from hydro_agent.skills.loader import validate_skill_name

ACTIVATION_STAGES = frozenset({"data", "diagnosis", "experiment", "gate", "report"})


def binding_path(root: Path, skill_id: str) -> Path:
    validate_skill_name(skill_id)
    return root / ".bindings" / f"{skill_id}.json"


def validate_binding(stages: tuple[str, ...], model_ids: tuple[str, ...]) -> None:
    unknown = set(stages) - ACTIVATION_STAGES
    if unknown:
        raise ValueError(f"unknown activation_stages: {', '.join(sorted(unknown))}")
    if any(not model_id.strip() or len(model_id) > 64 for model_id in model_ids):
        raise ValueError("activation_model_ids must be non-empty identifiers of at most 64 chars")


def read_binding(root: Path, skill_id: str) -> dict | None:
    path = binding_path(root, skill_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid Skill binding: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Skill binding must be an object: {path}")
    stages = payload.get("activation_stages", [])
    models = payload.get("activation_model_ids", [])
    if not isinstance(stages, list) or not all(isinstance(item, str) for item in stages):
        raise ValueError(f"invalid activation_stages in Skill binding: {path}")
    if not isinstance(models, list) or not all(isinstance(item, str) for item in models):
        raise ValueError(f"invalid activation_model_ids in Skill binding: {path}")
    validate_binding(tuple(stages), tuple(models))
    return {"activation_stages": stages, "activation_model_ids": models}
