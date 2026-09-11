from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from hydro_agent.execution.hashing import sha256_bytes
from hydro_agent.workflow.models import WorkflowDefinition

CURRENT_VERSION = "1.0.0"
CURRENT_FILENAME = "hydro-agent.v1.json"


def repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "workflow" / CURRENT_FILENAME
        if candidate.is_file() and (parent / "pyproject.toml").is_file():
            return parent
    return None


def workflow_dir() -> Path:
    env = os.environ.get("HYDRO_WORKFLOW_DIR")
    if env:
        return Path(env)
    root = repo_root()
    if root is not None:
        return root / "workflow"
    packaged = Path(__file__).parent / "data"
    if (packaged / CURRENT_FILENAME).is_file():
        return packaged
    raise FileNotFoundError("workflow definition directory not found")


def _iter_definition_files() -> list[Path]:
    directory = workflow_dir()
    return sorted(path for path in directory.glob("hydro-agent.v*.json") if path.is_file())


def definition_path(version: str | None = None) -> Path:
    directory = workflow_dir()
    if version is None or version == CURRENT_VERSION:
        path = directory / CURRENT_FILENAME
        if path.is_file():
            return path
    for path in _iter_definition_files():
        definition = WorkflowDefinition.model_validate_json(path.read_text(encoding="utf-8"))
        if version is None or definition.version == version:
            return path
    raise FileNotFoundError(f"workflow definition version {version or CURRENT_VERSION} not found")


def definition_hash(raw: bytes) -> str:
    return "sha256:" + sha256_bytes(raw)


def current_binding(version: str | None = None) -> dict[str, str]:
    path = definition_path(version)
    raw = path.read_bytes()
    definition = WorkflowDefinition.model_validate_json(raw)
    return {
        "workflow_id": definition.workflow_id,
        "workflow_version": definition.version,
        "workflow_hash": definition_hash(raw),
    }


def list_versions() -> tuple[str, ...]:
    versions: list[str] = []
    for path in _iter_definition_files():
        definition = WorkflowDefinition.model_validate_json(path.read_text(encoding="utf-8"))
        versions.append(definition.version)
    return tuple(versions)


def version_html_names() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path in _iter_definition_files():
        definition = WorkflowDefinition.model_validate_json(path.read_text(encoding="utf-8"))
        mapping[definition.version] = definition.diagram.html_name
    return mapping


@lru_cache(maxsize=16)
def _load_cached(path: str, mtime_ns: int) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_definition(version: str | None = None) -> WorkflowDefinition:
    path = definition_path(version)
    stat = path.stat()
    return _load_cached(str(path), stat.st_mtime_ns)


def load_definition_by_version(version: str) -> WorkflowDefinition:
    return load_definition(version)


def clear_definition_cache() -> None:
    _load_cached.cache_clear()
