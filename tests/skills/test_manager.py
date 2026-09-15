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
