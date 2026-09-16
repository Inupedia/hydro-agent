from __future__ import annotations

from pathlib import Path

from hydro_agent.skills.aliases import (
    LEGACY_SKILL_ALIASES,
    canonical_skill_id,
    migrate_user_skill_overrides,
)
from hydro_agent.skills.manager import SkillManager
from hydro_agent.skills import SkillRegistry


def test_canonical_skill_id_maps_former_twelve():
    assert canonical_skill_id("xaj-water-balance") == "xaj-calibration-diagnosis"
    assert canonical_skill_id("hydro-error-diagnosis") == "hydrologic-evidence-review"
    assert canonical_skill_id("hydrology-reporting") == "hydrology-reporting"
    assert set(LEGACY_SKILL_ALIASES) >= {
        "hydro-data-readiness",
        "xaj-calibration",
        "hydro-report-closeout",
    }


def test_migrate_user_skill_overrides_renames_legacy_dirs(tmp_path: Path):
    legacy = tmp_path / "xaj-water-balance"
    legacy.mkdir()
    (legacy / "SKILL.md").write_text(
        "---\nname: xaj-water-balance\ndescription: legacy overlay\n---\n\n# body\n",
        encoding="utf-8",
    )
    binding_dir = tmp_path / ".bindings"
    binding_dir.mkdir()
    (binding_dir / "xaj-water-balance.json").write_text(
        '{"skill_id":"xaj-water-balance","activation_stages":["diagnosis"],'
        '"activation_model_ids":["xaj"]}\n',
        encoding="utf-8",
    )
    reports = migrate_user_skill_overrides(tmp_path)
    assert reports == [
        {
            "legacy_id": "xaj-water-balance",
            "canonical_id": "xaj-calibration-diagnosis",
            "status": "migrated",
            "detail": "moved user overlay xaj-water-balance → xaj-calibration-diagnosis",
        }
    ]
    assert not legacy.exists()
    assert (tmp_path / "xaj-calibration-diagnosis" / "SKILL.md").is_file()
    binding = (binding_dir / "xaj-calibration-diagnosis.json").read_text(encoding="utf-8")
    assert '"skill_id": "xaj-calibration-diagnosis"' in binding
    skill_md = (tmp_path / "xaj-calibration-diagnosis" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: xaj-calibration-diagnosis" in skill_md
    assert "name: xaj-water-balance" not in skill_md


def test_manager_migrate_legacy_overrides_reloads(tmp_path: Path):
    user = tmp_path / "user"
    builtin = tmp_path / "builtin"
    user.mkdir()
    builtin.mkdir()
    # Minimal builtin so registry reload stays valid after migrate.
    dest = builtin / "xaj-calibration-diagnosis"
    dest.mkdir()
    (dest / "SKILL.md").write_text(
        "---\nname: xaj-calibration-diagnosis\ndescription: diagnose xaj\n---\n\n# body\n",
        encoding="utf-8",
    )
    legacy = user / "xaj-routing-diagnosis"
    legacy.mkdir()
    (legacy / "SKILL.md").write_text(
        "---\nname: xaj-routing-diagnosis\ndescription: routing overlay\n---\n\n# body\n",
        encoding="utf-8",
    )
    registry = SkillRegistry(user_root=user, builtin_root=builtin)
    manager = SkillManager(registry)
    result = manager.migrate_legacy_overrides()
    assert result["count"] == 1
    assert result["migrated"][0]["canonical_id"] == "xaj-calibration-diagnosis"
    assert registry.source("xaj-calibration-diagnosis") == "user"
