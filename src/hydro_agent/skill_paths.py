"""Filesystem locations for built-in and user-managed Agent Skills."""

from __future__ import annotations

import os
from pathlib import Path


def builtin_skills_root() -> Path:
    # Repository Skills are the editable source of truth. Wheels carry a build
    # copy under the Python package so installed runtimes use the same assets.
    source = Path(__file__).resolve().parents[2] / "skills"
    if source.is_dir():
        return source
    return Path(__file__).resolve().with_name("skills") / "data"


def user_skills_root() -> Path:
    configured = os.getenv("HYDRO_AGENT_SKILLS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / ".agents" / "skills"


def active_skill_root(skill_id: str) -> Path:
    """Return the active user override when present, otherwise the built-in skill."""
    user = user_skills_root() / skill_id
    if (user / "SKILL.md").is_file():
        return user
    return builtin_skills_root() / skill_id
