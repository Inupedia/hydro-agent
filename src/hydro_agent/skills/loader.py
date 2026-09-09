"""Load agentskills.io SKILL.md packages from disk (stdlib frontmatter parser)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_DEFAULT_NSE_GOOD_ENOUGH = 0.6


@dataclass(frozen=True)
class LoadedSkill:
    skill_id: str
    name: str
    description: str
    body: str
    metadata: dict[str, str] = field(default_factory=dict)
    root: Path | None = None

    def meta(self, key: str, default: str = "") -> str:
        return str(self.metadata.get(key, default) or default)

    def meta_list(self, key: str) -> tuple[str, ...]:
        raw = self.meta(key)
        if not raw:
            return ()
        if "|" in raw and "," not in raw:
            parts = raw.split("|")
        else:
            parts = raw.split(",")
        return tuple(p.strip() for p in parts if p.strip())


def default_skills_root() -> Path:
    return Path(__file__).resolve().parent


def parse_skill_md(text: str, *, directory_name: str, root: Path | None = None) -> LoadedSkill:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"SKILL.md missing YAML frontmatter: {directory_name}")
    meta_block, body = match.group(1), match.group(2).strip()
    flat = _parse_frontmatter(meta_block)
    name = str(flat.get("name") or "").strip()
    description = str(flat.get("description") or "").strip()
    if not name or not description:
        raise ValueError(f"SKILL.md requires name and description: {directory_name}")
    if name != directory_name:
        raise ValueError(f"skill name {name!r} must match directory {directory_name!r}")
    _validate_skill_name(name)
    metadata = {
        str(k): str(v)
        for k, v in flat.items()
        if k not in {"name", "description", "license", "compatibility", "allowed-tools"}
        and not str(k).startswith("_")
    }
    # Nested metadata: keys may be prefixed as metadata.foo from parser
    nested = flat.get("_metadata")
    if isinstance(nested, dict):
        for k, v in nested.items():
            metadata[str(k)] = str(v)
    return LoadedSkill(
        skill_id=name,
        name=name,
        description=description,
        body=body,
        metadata=metadata,
        root=root,
    )


def load_skills(root: Path | None = None) -> dict[str, LoadedSkill]:
    base = Path(root) if root is not None else default_skills_root()
    skills: dict[str, LoadedSkill] = {}
    if not base.is_dir():
        return skills
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        skill_path = child / "SKILL.md"
        if not skill_path.is_file():
            continue
        text = skill_path.read_text(encoding="utf-8")
        loaded = parse_skill_md(text, directory_name=child.name, root=child)
        skills[loaded.skill_id] = loaded
    return skills


def read_reference(skill: LoadedSkill, relative: str, *, max_chars: int = 4000) -> str:
    if skill.root is None:
        return ""
    path = (skill.root / relative).resolve()
    if not str(path).startswith(str(skill.root.resolve())):
        raise ValueError("reference path escapes skill root")
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    if len(text) > max_chars:
        return text[: max_chars - 20] + "\n\n…(truncated)…"
    return text


def parse_nse_good_enough(metadata: dict[str, str], *, default: float = _DEFAULT_NSE_GOOD_ENOUGH) -> float:
    raw = metadata.get("nse_good_enough", "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return value


def _validate_skill_name(name: str) -> None:
    if not (1 <= len(name) <= 64):
        raise ValueError(f"invalid skill name length: {name!r}")
    if name[0] == "-" or name[-1] == "-":
        raise ValueError(f"skill name cannot start/end with hyphen: {name!r}")
    if "--" in name:
        raise ValueError(f"skill name cannot contain consecutive hyphens: {name!r}")
    if not re.fullmatch(r"[a-z0-9-]+", name):
        raise ValueError(f"skill name must be lowercase alphanumeric/hyphen: {name!r}")


def _parse_frontmatter(block: str) -> dict:
    """Minimal YAML subset: top-level scalars + one-level metadata map."""
    result: dict = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        if line.startswith(" ") or line.startswith("\t"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if key == "metadata" and (rest == "" or rest == "{}"):
            nested: dict[str, str] = {}
            i += 1
            while i < len(lines):
                nested_line = lines[i]
                if nested_line and not nested_line[0].isspace():
                    break
                stripped = nested_line.strip()
                if not stripped or stripped.startswith("#"):
                    i += 1
                    continue
                if ":" not in stripped:
                    i += 1
                    continue
                nk, _, nv = stripped.partition(":")
                nested[nk.strip()] = _unquote(nv.strip())
                i += 1
            result["_metadata"] = nested
            continue
        result[key] = _unquote(rest)
        i += 1
    # Flatten metadata into result for convenience
    if "_metadata" in result and isinstance(result["_metadata"], dict):
        for k, v in result["_metadata"].items():
            result.setdefault(k, v)
    return result


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
