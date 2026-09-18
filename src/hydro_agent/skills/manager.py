"""Writable management layer for user Agent Skills.

Package-owned built-in skills are read-only. Creates and edits write only under
the user overlay. Scripts are intentionally not writable through this API.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path, PurePosixPath

from hydro_agent.skills import SkillRegistry
from hydro_agent.skills.aliases import LEGACY_SKILL_ALIASES, migrate_user_skill_overrides
from hydro_agent.skills.binding import ACTIVATION_STAGES, binding_path, validate_binding
from hydro_agent.skills.loader import (
    LoadedSkill,
    load_skill_content,
    parse_skill_md,
    validate_skill_name,
)

_EDITABLE_RESOURCE_ROOTS = {"references", "assets"}
_BUILTIN_READONLY = "built-in skills are read-only; create a new user skill instead"
_AGENT_READONLY = "agent-managed skills are read-only; they are generated from validated Experience"
_CORE_SKILL_IDS = frozenset(LEGACY_SKILL_ALIASES.values()) | {
    "hydrology-data-review",
    "hydrologic-evidence-review",
    "xaj-calibration-diagnosis",
    "gr4j-calibration-diagnosis",
    "hbv-calibration-diagnosis",
    "tank-calibration-diagnosis",
    "sac-sma-calibration-diagnosis",
    "calibration-experiment-design",
    "calibration-result-review",
    "hydrology-reporting",
}


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
        loaded = load_skill_content(self._require_loaded(skill_id))
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
        unknown_stages = set(parsed.meta_list("activation_stages")) - ACTIVATION_STAGES
        if unknown_stages:
            raise ValueError(f"unknown activation_stages: {', '.join(sorted(unknown_stages))}")
        source = self._source_or_none(skill_id)
        if source == "builtin":
            raise ValueError(_BUILTIN_READONLY)
        if source == "agent":
            raise ValueError(_AGENT_READONLY)
        if source == "memory":
            raise ValueError("in-memory skills are read-only")
        user_dir = self._ensure_user_dir(skill_id, create=True)
        self._atomic_write(user_dir / "SKILL.md", skill_md)
        self.registry.reload()
        return self.detail_payload(skill_id)

    def validate_skill(self, skill_id: str, skill_md: str) -> dict:
        """Check a draft without writing it or activating its instructions."""
        errors: list[str] = []
        warnings: list[str] = []
        if len(skill_md) > self.max_skill_chars:
            errors.append(f"SKILL.md exceeds {self.max_skill_chars} characters")
        try:
            parsed = parse_skill_md(skill_md, directory_name=skill_id)
        except ValueError as exc:
            errors.append(str(exc))
            return {"standard_compatible": False, "domain_ready": False,
                    "errors": errors, "warnings": warnings}
        standard_compatible = not errors
        unknown_stages = set(parsed.meta_list("activation_stages")) - ACTIVATION_STAGES
        if unknown_stages:
            errors.append(f"unknown activation_stages: {', '.join(sorted(unknown_stages))}")
        source = self._source_or_none(skill_id)
        if source == "user":
            root = self.registry.user_root / skill_id
        elif source == "agent":
            root = self.registry.agent_root / skill_id
        elif self.registry.builtin_root is not None:
            root = self.registry.builtin_root / skill_id
        else:
            root = self.registry.user_root / skill_id
        for relative in parsed.meta_list("prompt_references"):
            try:
                normalized = self._validate_resource_relative(relative, writable=False)
            except ValueError as exc:
                errors.append(f"invalid prompt Reference {relative}: {exc}")
                continue
            if normalized.parts[0] != "references":
                errors.append(f"prompt Reference must be under references/: {relative}")
                continue
            path = (root / normalized).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                errors.append(f"prompt Reference is missing or escapes package: {relative}")
        try:
            binding = self.registry.binding_for(skill_id)
        except KeyError:
            binding = {"activation_stages": []}
        if not binding["activation_stages"] and not parsed.meta_list("activation_stages"):
            warnings.append("Skill has no Workflow Binding and will not activate")
        return {"standard_compatible": standard_compatible, "domain_ready": not errors and not warnings,
                "errors": errors, "warnings": warnings}

    def save_binding(
        self, skill_id: str, *, activation_stages: tuple[str, ...], activation_model_ids: tuple[str, ...]
    ) -> dict:
        source = self._source_or_none(skill_id)
        if source != "user":
            raise ValueError(_AGENT_READONLY if source == "agent" else _BUILTIN_READONLY)
        validate_binding(activation_stages, activation_model_ids)
        path = binding_path(self.registry.user_root, skill_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(
            path,
            json.dumps(
                {
                    "activation_stages": list(dict.fromkeys(activation_stages)),
                    "activation_model_ids": list(dict.fromkeys(activation_model_ids)),
                },
                ensure_ascii=False,
                sort_keys=True,
            ) + "\n",
        )
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
            raise ValueError(_AGENT_READONLY if source == "agent" else _BUILTIN_READONLY)
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
        binding_path(self.registry.user_root, skill_id).unlink(missing_ok=True)
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
            "activation_stages": self.registry.binding_for(skill_id)["activation_stages"] if loaded else [],
            "activation_model_ids": self.registry.binding_for(skill_id)["activation_model_ids"] if loaded else [],
            "recommended_actions": list(card.recommended_actions),
            "core": skill_id in _CORE_SKILL_IDS,
        }

    def copy_from_builtin(self, skill_id: str) -> dict:
        """Copy a package-owned skill into the writable user overlay for customization."""
        validate_skill_name(skill_id)
        user_root = self.registry.user_root
        user_dir = user_root / skill_id
        if user_dir.exists():
            raise ValueError(f"user skill already exists: {skill_id}")
        source = self._source_or_none(skill_id)
        if source != "builtin":
            raise ValueError("only built-in skills can be copied into the user overlay")
        builtin_root = self.registry.builtin_root
        if builtin_root is None:
            raise ValueError("no built-in skill root configured")
        src = (builtin_root / skill_id).resolve()
        if not (src / "SKILL.md").is_file():
            raise KeyError(skill_id)
        user_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, user_dir)
        self.registry.reload()
        return self.detail_payload(skill_id)

    def migrate_legacy_overrides(self) -> dict:
        """Rename user overlays that still use the retired twelve Skill IDs."""

        reports = migrate_user_skill_overrides(self.registry.user_root)
        if reports:
            self.registry.reload()
        return {
            "migrated": [row for row in reports if row["status"] == "migrated"],
            "conflicts": [row for row in reports if row["status"] == "conflict"],
            "count": len(reports),
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
        previous = path.read_bytes() if path.is_file() else b""
        has_bom = previous.startswith(b"\xef\xbb\xbf")
        previous_body = previous[3:] if has_bom else previous
        newline = "\r\n" if b"\r\n" in previous_body else "\n"
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        if newline == "\r\n":
            normalized = normalized.replace("\n", "\r\n")
        normalized = normalized.lstrip("\ufeff")
        with temp.open("w", encoding="utf-8-sig" if has_bom else "utf-8", newline="") as stream:
            stream.write(normalized)
        temp.replace(path)
