"""Filesystem locations for built-in and user-managed Agent Skills."""

from __future__ import annotations

import os
from pathlib import Path


def builtin_skills_root() -> Path:
    return Path(__file__).resolve().parent


def user_skills_root() -> Path:
    configured = os.getenv("HYDRO_AGENT_SKILLS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / ".agents" / "skills"


def active_skill_root(skill_id: str) -> Path:
    user = user_skills_root() / skill_id
    if (user / "SKILL.md").is_file():
        return user
    return builtin_skills_root() / skill_id
