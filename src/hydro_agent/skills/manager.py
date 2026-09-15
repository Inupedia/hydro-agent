"""Writable management layer for user Agent Skills.

Package-owned built-in skills are read-only. Creates and edits write only under
the user overlay. Scripts are intentionally not writable through this API.
"""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath

from hydro_agent.skills import SkillRegistry
from hydro_agent.skills.loader import LoadedSkill, parse_skill_md, validate_skill_name

_EDITABLE_RESOURCE_ROOTS = {"references", "assets"}
_BUILTIN_READONLY = "built-in skills are read-only; create a new user skill instead"
_ACTIVATION_STAGES = {"data", "diagnosis", "experiment", "gate", "report"}


class SkillManager:
    def __init__(
        self,
        registry: SkillRegistry,
        *,
        max_skill_chars: int = 200_000,
        max_resource_chars: int = 200_000,
    ) -> None:
        self.registry = registry
        self.max_skill_chars = max_skill_chars
        self.max_resource_chars = max_resource_chars

    def list_payload(self) -> list[dict]:
        return [self._summary_payload(card.skill_id) for card in self.registry.list()]

    def detail_payload(self, skill_id: str) -> dict:
        loaded = self._require_loaded(skill_id)
        payload = self._summary_payload(skill_id)
        payload.update(
            {
                "skill_md": loaded.raw_text,
                "body": loaded.body,
                "metadata": dict(loaded.metadata),
                "license": loaded.license or None,
                "compatibility": loaded.compatibility or None,
                "allowed_tools": loaded.allowed_tools or None,
                "resources": self.list_resources(skill_id),
            }
        )
        return payload

    def save_skill(self, skill_id: str, skill_md: str) -> dict:
        validate_skill_name(skill_id)
        if len(skill_md) > self.max_skill_chars:
            raise ValueError(f"SKILL.md exceeds {self.max_skill_chars} characters")
        parsed = parse_skill_md(skill_md, directory_name=skill_id)
        unknown_stages = set(parsed.meta_list("activation_stages")) - _ACTIVATION_STAGES
        if unknown_stages:
            raise ValueError(f"unknown activation_stages: {', '.join(sorted(unknown_stages))}")
        source = self._source_or_none(skill_id)
        if source == "builtin":
            raise ValueError(_BUILTIN_READONLY)
        if source == "memory":
            raise ValueError("in-memory skills are read-only")
        user_dir = self._ensure_user_dir(skill_id, create=True)
        self._atomic_write(user_dir / "SKILL.md", skill_md)
        self.registry.reload()
        return self.detail_payload(skill_id)

    def list_resources(self, skill_id: str) -> list[dict]:
        skill = self._require_loaded(skill_id)
        if skill.root is None:
            return []
        editable = self._source_or_none(skill_id) == "user"
        rows: list[dict] = []
        for category in ("references", "assets", "scripts"):
            base = skill.root / category
            if not base.is_dir():
                continue
            for path in sorted(item for item in base.rglob("*") if item.is_file()):
                relative = path.relative_to(skill.root).as_posix()
                rows.append(
                    {
                        "path": relative,
                        "category": category,
                        "editable": editable and category in _EDITABLE_RESOURCE_ROOTS,
                        "size": path.stat().st_size,
                    }
                )
        return rows

    def read_resource(self, skill_id: str, relative: str) -> str:
        skill = self._require_loaded(skill_id)
        path = self._resource_path(skill, relative, writable=False)
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("resource is not UTF-8 text") from exc

    def save_resource(self, skill_id: str, relative: str, content: str) -> dict:
        if len(content) > self.max_resource_chars:
            raise ValueError(f"resource exceeds {self.max_resource_chars} characters")
        source = self._source_or_none(skill_id)
        if source != "user":
            raise ValueError(_BUILTIN_READONLY)
        normalized = self._validate_resource_relative(relative, writable=True)
        user_dir = self._ensure_user_dir(skill_id, create=False)
        path = (user_dir / normalized).resolve()
        if not path.is_relative_to(user_dir.resolve()):
            raise ValueError("resource path escapes skill root")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(path, content)
        self.registry.reload()
        return {
            "skill_id": skill_id,
            "path": normalized.as_posix(),
            "content": content,
            "source": self.registry.source(skill_id),
        }

    def delete_override(self, skill_id: str) -> dict:
        validate_skill_name(skill_id)
        user_dir = self.registry.user_root / skill_id
        if not user_dir.is_dir():
            raise KeyError(f"no user override for skill: {skill_id}")
        shutil.rmtree(user_dir)
        active = self.registry.reload()
        restored = skill_id in active
        return {
            "skill_id": skill_id,
            "override_deleted": True,
            "restored_builtin": restored and self.registry.source(skill_id) == "builtin",
            "active": restored,
        }

    def _summary_payload(self, skill_id: str) -> dict:
        card = self.registry.get(skill_id)
        loaded = self.registry.get_loaded(skill_id)
        source = self.registry.source(skill_id)
        return {
            "skill_id": card.skill_id,
            "name": loaded.name if loaded is not None else card.skill_id,
            "description": loaded.description if loaded is not None else card.description,
            "title_zh": card.title_zh,
            "purpose_zh": card.purpose_zh,
            "source": source,
            "editable": source == "user",
        }

    def _source_or_none(self, skill_id: str) -> str | None:
        try:
            return self.registry.source(skill_id)
        except KeyError:
            return None

    def _require_loaded(self, skill_id: str) -> LoadedSkill:
        loaded = self.registry.get_loaded(skill_id)
        if loaded is None:
            if skill_id in {card.skill_id for card in self.registry.list()}:
                raise ValueError(f"skill has no file-backed SKILL.md: {skill_id}")
            raise KeyError(skill_id)
        return loaded

    def _ensure_user_dir(self, skill_id: str, *, create: bool) -> Path:
        user_root = self.registry.user_root
        user_dir = user_root / skill_id
        if user_dir.is_dir():
            return user_dir
        if not create:
            raise KeyError(skill_id)
        user_root.mkdir(parents=True, exist_ok=True)
        user_dir.mkdir(parents=True, exist_ok=False)
        return user_dir

    def _resource_path(self, skill: LoadedSkill, relative: str, *, writable: bool) -> Path:
        if skill.root is None:
            raise ValueError(f"skill has no file root: {skill.skill_id}")
        normalized = self._validate_resource_relative(relative, writable=writable)
        base = skill.root.resolve()
        path = (skill.root / normalized).resolve()
        if not path.is_relative_to(base):
            raise ValueError("resource path escapes skill root")
        if not path.is_file():
            raise KeyError(relative)
        return path

    @staticmethod
    def _validate_resource_relative(relative: str, *, writable: bool) -> PurePosixPath:
        path = PurePosixPath(relative)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("invalid resource path")
        category = path.parts[0]
        if category not in {"references", "assets", "scripts"}:
            raise ValueError("resource must be under references/, assets/, or scripts/")
        if writable and category not in _EDITABLE_RESOURCE_ROOTS:
            raise ValueError("scripts/ is read-only; executable uploads are disabled")
        return path

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temp = path.with_name(f".{path.name}.tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(path)
