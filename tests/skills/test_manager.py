from pathlib import Path

import pytest

from hydro_agent.skills import SkillRegistry
from hydro_agent.skills.manager import SkillManager


def _write_skill(root: Path, name: str, description: str, *, body: str = "# Body") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: {description}
metadata:
  title_zh: "{name}"
---

{body}
""",
        encoding="utf-8",
    )
    return skill_dir


def test_builtin_skills_are_read_only(tmp_path: Path):
    builtin_root = tmp_path / "builtin"
    user_root = tmp_path / "user"
    builtin = _write_skill(builtin_root, "demo-skill", "builtin description")
    (builtin / "references").mkdir()
    (builtin / "references" / "guide.md").write_text("builtin guide\n", encoding="utf-8")
    original = (builtin / "SKILL.md").read_text(encoding="utf-8")

    registry = SkillRegistry(builtin_root=builtin_root, user_root=user_root)
    manager = SkillManager(registry)
    assert registry.source("demo-skill") == "builtin"
    assert manager.detail_payload("demo-skill")["editable"] is False

    updated = """---
name: demo-skill
description: user override description
metadata:
  title_zh: "用户版本"
---

# User body
"""
    with pytest.raises(ValueError, match="read-only"):
        manager.save_skill("demo-skill", updated)
    with pytest.raises(ValueError, match="read-only"):
        manager.save_resource("demo-skill", "references/guide.md", "nope\n")

    assert registry.source("demo-skill") == "builtin"
    assert not (user_root / "demo-skill").exists()
    assert (builtin / "SKILL.md").read_text(encoding="utf-8") == original


def test_user_skill_edit_preserves_existing_bom_and_crlf(tmp_path: Path):
    user_root = tmp_path / "user"
    user_dir = user_root / "bom-skill"
    user_dir.mkdir(parents=True)
    original = "---\r\nname: bom-skill\r\ndescription: sample\r\n---\r\n\r\n# First\r\n"
    (user_dir / "SKILL.md").write_bytes(b"\xef\xbb\xbf" + original.encode("utf-8"))
    registry = SkillRegistry(builtin_root=tmp_path / "builtin", user_root=user_root)
    manager = SkillManager(registry)
    updated = "---\nname: bom-skill\ndescription: sample\n---\n\n# Second\n"
    manager.save_skill("bom-skill", updated)
    raw = (user_dir / "SKILL.md").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n# Second\r\n" in raw


def test_validate_skill_draft_reports_missing_reference_without_writing(tmp_path: Path):
    user_root = tmp_path / "user"
    _write_skill(user_root, "review-skill", "review")
    registry = SkillRegistry(builtin_root=tmp_path / "builtin", user_root=user_root)
    manager = SkillManager(registry)
    original = (user_root / "review-skill" / "SKILL.md").read_bytes()
    draft = """---
name: review-skill
description: Review evidence.
metadata:
  prompt_references: references/missing.md
---

# Review
"""
    result = manager.validate_skill("review-skill", draft)
    assert result["standard_compatible"] is True
    assert result["domain_ready"] is False
    assert any("missing" in error for error in result["errors"])
    assert (user_root / "review-skill" / "SKILL.md").read_bytes() == original


def test_copy_builtin_skill_to_user_overlay(tmp_path: Path):
    builtin_root = tmp_path / "builtin"
    user_root = tmp_path / "user"
    builtin = _write_skill(builtin_root, "demo-skill", "builtin description", body="# Builtin")
    (builtin / "references").mkdir()
    (builtin / "references" / "guide.md").write_text("guide\n", encoding="utf-8")

    registry = SkillRegistry(builtin_root=builtin_root, user_root=user_root)
    manager = SkillManager(registry)
    detail = manager.copy_from_builtin("demo-skill")
    assert detail["source"] == "user"
    assert detail["editable"] is True
    assert (user_root / "demo-skill" / "SKILL.md").is_file()
    assert manager.read_resource("demo-skill", "references/guide.md") == "guide\n"
    with pytest.raises(ValueError, match="already exists"):
        manager.copy_from_builtin("demo-skill")


def test_user_skill_edit_and_delete_restores_builtin(tmp_path: Path):
    builtin_root = tmp_path / "builtin"
    user_root = tmp_path / "user"
    _write_skill(builtin_root, "demo-skill", "builtin description")
    _write_skill(user_root, "demo-skill", "user description", body="# User body")

    registry = SkillRegistry(builtin_root=builtin_root, user_root=user_root)
    manager = SkillManager(registry)
    assert registry.source("demo-skill") == "user"
    assert manager.detail_payload("demo-skill")["editable"] is True

    updated = """---
name: demo-skill
description: edited user description
metadata:
  title_zh: "用户版本"
---

# Edited
"""
    detail = manager.save_skill("demo-skill", updated)
    assert detail["source"] == "user"
    assert registry.get_loaded("demo-skill").description == "edited user description"

    result = manager.delete_override("demo-skill")
    assert result["restored_builtin"] is True
    assert registry.source("demo-skill") == "builtin"
    assert registry.get_loaded("demo-skill").description == "builtin description"


def test_user_binding_is_external_and_overrides_legacy_metadata(tmp_path: Path):
    user_root = tmp_path / "user"
    registry = SkillRegistry(builtin_root=tmp_path / "builtin", user_root=user_root)
    manager = SkillManager(registry)
    skill_md = """---
name: binding-skill
description: Evidence review.
metadata:
  activation_stages: "data"
---

# Review
"""
    manager.save_skill("binding-skill", skill_md)
    assert registry.binding_for("binding-skill")["activation_stages"] == ["data"]
    detail = manager.save_binding(
        "binding-skill", activation_stages=("diagnosis",), activation_model_ids=("xaj",)
    )
    assert detail["activation_stages"] == ["diagnosis"]
    assert detail["activation_model_ids"] == ["xaj"]
    assert (user_root / "binding-skill" / "SKILL.md").read_text(encoding="utf-8") == skill_md
    assert (user_root / ".bindings" / "binding-skill.json").is_file()
    registry.reload()
    assert registry.binding_for("binding-skill")["activation_stages"] == ["diagnosis"]
    manager.delete_override("binding-skill")
    assert not (user_root / ".bindings" / "binding-skill.json").exists()


def test_create_skill_and_manage_reference_resource(tmp_path: Path):
    builtin_root = tmp_path / "builtin"
    user_root = tmp_path / "user"
    registry = SkillRegistry(builtin_root=builtin_root, user_root=user_root)
    manager = SkillManager(registry)

    skill_md = """---
name: custom-skill
description: user managed hydrology skill
metadata:
  title_zh: "自定义技能"
---

# Custom
"""
    detail = manager.save_skill("custom-skill", skill_md)
    assert detail["source"] == "user"
    assert detail["editable"] is True

    saved = manager.save_resource(
        "custom-skill", "references/diagnosis.md", "# Diagnosis\nwater balance\n"
    )
    assert saved["path"] == "references/diagnosis.md"
    assert manager.read_resource("custom-skill", "references/diagnosis.md") == (
        "# Diagnosis\nwater balance\n"
    )
    resources = manager.list_resources("custom-skill")
    assert resources == [
        {
            "path": "references/diagnosis.md",
            "category": "references",
            "editable": True,
            "size": 26,
        }
    ]


def test_reject_unknown_activation_stage_before_writing(tmp_path: Path):
    registry = SkillRegistry(builtin_root=tmp_path / "builtin", user_root=tmp_path / "user")
    manager = SkillManager(registry)
    with pytest.raises(ValueError, match="unknown activation_stages"):
        manager.save_skill(
            "bad-stage",
            """---
name: bad-stage
description: Invalid stage.
metadata:
  activation_stages: "guess"
---

# Body
""",
        )
    assert not (tmp_path / "user" / "bad-stage").exists()


def test_scripts_and_path_traversal_are_not_writable(tmp_path: Path):
    registry = SkillRegistry(builtin_root=tmp_path / "builtin", user_root=tmp_path / "user")
    manager = SkillManager(registry)
    manager.save_skill(
        "safe-skill",
        """---
name: safe-skill
description: safe skill
---

# Safe
""",
    )

    with pytest.raises(ValueError, match="scripts/ is read-only"):
        manager.save_resource("safe-skill", "scripts/run.py", "print('unsafe')\n")
    with pytest.raises(ValueError, match="invalid resource path"):
        manager.save_resource("safe-skill", "../outside.md", "no\n")
    with pytest.raises(ValueError, match="resource must be under"):
        manager.save_resource("safe-skill", "other/file.md", "no\n")


def test_reload_picks_up_direct_external_skill_edit(tmp_path: Path):
    builtin_root = tmp_path / "builtin"
    user_root = tmp_path / "user"
    _write_skill(builtin_root, "demo-skill", "builtin description")
    user_skill = _write_skill(user_root, "demo-skill", "first user description")

    registry = SkillRegistry(builtin_root=builtin_root, user_root=user_root)
    assert registry.source("demo-skill") == "user"
    assert registry.get_loaded("demo-skill").description == "first user description"

    (user_skill / "SKILL.md").write_text(
        """---
name: demo-skill
description: edited outside the process
---

# Reloaded
""",
        encoding="utf-8",
    )
    registry.reload()

    assert registry.get_loaded("demo-skill").description == "edited outside the process"



def test_agent_skill_is_read_only(tmp_path: Path):
    builtin_root = tmp_path / "builtin"
    agent_root = tmp_path / "agent"
    user_root = tmp_path / "user"
    _write_skill(agent_root, "calibration-experience", "agent generated experience")

    registry = SkillRegistry(
        builtin_root=builtin_root,
        agent_root=agent_root,
        user_root=user_root,
    )
    manager = SkillManager(registry)

    assert registry.source("calibration-experience") == "agent"
    detail = manager.detail_payload("calibration-experience")
    assert detail["source"] == "agent"
    assert detail["editable"] is False

    with pytest.raises(ValueError, match="agent-managed"):
        manager.save_skill(
            "calibration-experience",
            """---
name: calibration-experience
description: manual edit
---

# Manual
""",
        )
