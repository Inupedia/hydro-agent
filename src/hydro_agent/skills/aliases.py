"""Map retired twelve-skill IDs onto the six task-oriented packages."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

# Former built-in packages → current SSOT under top-level ``skills/``.
LEGACY_SKILL_ALIASES: dict[str, str] = {
    "hydro-data-readiness": "hydrology-data-review",
    "hydro-modeling-prep": "hydrology-data-review",
    "hydro-error-diagnosis": "hydrologic-evidence-review",
    "openhydronet-diagnosis": "hydrologic-evidence-review",
    "xaj-calibration": "xaj-calibration-diagnosis",
    "xaj-water-balance": "xaj-calibration-diagnosis",
    "xaj-runoff-generation": "xaj-calibration-diagnosis",
    "xaj-routing-diagnosis": "xaj-calibration-diagnosis",
    "hydro-experiment-design": "calibration-experiment-design",
    "hydro-campaign-design": "calibration-experiment-design",
    "gbt-22482-accuracy": "calibration-result-review",
    "hydro-report-closeout": "hydrology-reporting",
}


def canonical_skill_id(skill_id: str) -> str:
    """Resolve a possibly-legacy Skill id to the six-package canonical id."""

    return LEGACY_SKILL_ALIASES.get(skill_id, skill_id)


def migrate_user_skill_overrides(user_root: Path) -> list[dict[str, str]]:
    """Rename leftover user overlay dirs from the former twelve IDs.

    Complete-package override semantics are preserved: the whole directory moves
    to the canonical id. If both legacy and canonical dirs exist, the legacy
    copy is left untouched and reported as a conflict. Frontmatter ``name`` is
    rewritten to the canonical id so agentskills naming still validates.
    """

    root = Path(user_root)
    if not root.is_dir():
        return []
    reports: list[dict[str, str]] = []
    for legacy_id, canonical_id in sorted(LEGACY_SKILL_ALIASES.items()):
        src = root / legacy_id
        if not src.is_dir():
            continue
        dest = root / canonical_id
        if dest.exists():
            reports.append(
                {
                    "legacy_id": legacy_id,
                    "canonical_id": canonical_id,
                    "status": "conflict",
                    "detail": f"{canonical_id} already exists; left {legacy_id} unchanged",
                }
            )
            continue
        shutil.move(str(src), str(dest))
        skill_md = dest / "SKILL.md"
        if skill_md.is_file():
            text = skill_md.read_text(encoding="utf-8-sig")
            rewritten = text.replace(f"name: {legacy_id}", f"name: {canonical_id}", 1)
            if rewritten != text:
                skill_md.write_text(rewritten, encoding="utf-8")
        binding_src = root / ".bindings" / f"{legacy_id}.json"
        binding_dest = root / ".bindings" / f"{canonical_id}.json"
        if binding_src.is_file() and not binding_dest.exists():
            binding_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(binding_src), str(binding_dest))
            payload = json.loads(binding_dest.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("skill_id") == legacy_id:
                payload["skill_id"] = canonical_id
                binding_dest.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        reports.append(
            {
                "legacy_id": legacy_id,
                "canonical_id": canonical_id,
                "status": "migrated",
                "detail": f"moved user overlay {legacy_id} → {canonical_id}",
            }
        )
    return reports
