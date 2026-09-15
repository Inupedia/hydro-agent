from pathlib import Path

from fastapi.testclient import TestClient

from hydro_agent.api.app import create_app
from hydro_agent.skills import SkillRegistry


def _write_skill(root: Path, name: str, description: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: {description}
metadata:
  title_zh: "测试技能"
---

# Test body
""",
        encoding="utf-8",
    )
    return skill_dir


def test_skill_api_override_and_restore(app_dependencies, tmp_path: Path):
    builtin_root = tmp_path / "builtin-skills"
    user_root = tmp_path / "user-skills"
    builtin = _write_skill(builtin_root, "demo-skill", "builtin description")
    original = (builtin / "SKILL.md").read_text(encoding="utf-8")
    app_dependencies.skills = SkillRegistry(builtin_root=builtin_root, user_root=user_root)

    app = create_app(app_dependencies)
    with TestClient(app) as client:
        listing = client.get("/api/skills")
        assert listing.status_code == 200
        assert listing.json()["items"][0]["source"] == "builtin"

        updated = """---
name: demo-skill
description: API managed override
metadata:
  title_zh: "API 覆盖"
---

# Updated body
"""
        response = client.put("/api/skills/demo-skill", json={"skill_md": updated})
        assert response.status_code == 200
        assert response.json()["source"] == "user"
        assert response.json()["description"] == "API managed override"
        assert (builtin / "SKILL.md").read_text(encoding="utf-8") == original

        detail = client.get("/api/skills/demo-skill")
        assert detail.status_code == 200
        assert detail.json()["skill_md"] == updated

        restored = client.delete("/api/skills/demo-skill/override")
        assert restored.status_code == 200
        assert restored.json()["restored_builtin"] is True

        detail = client.get("/api/skills/demo-skill")
        assert detail.status_code == 200
        assert detail.json()["source"] == "builtin"
        assert detail.json()["description"] == "builtin description"
    app.state.executor.shutdown()


def test_skill_api_resource_write_and_script_guard(app_dependencies, tmp_path: Path):
    builtin_root = tmp_path / "builtin-skills"
    user_root = tmp_path / "user-skills"
    _write_skill(builtin_root, "demo-skill", "builtin description")
    app_dependencies.skills = SkillRegistry(builtin_root=builtin_root, user_root=user_root)

    app = create_app(app_dependencies)
    with TestClient(app) as client:
        response = client.put(
            "/api/skills/demo-skill/resources/references/notes.md",
            json={"content": "# Notes\nhello\n"},
        )
        assert response.status_code == 200
        assert response.json()["source"] == "user"

        resource = client.get("/api/skills/demo-skill/resources/references/notes.md")
        assert resource.status_code == 200
        assert resource.json()["content"] == "# Notes\nhello\n"

        blocked = client.put(
            "/api/skills/demo-skill/resources/scripts/run.py",
            json={"content": "print('blocked')\n"},
        )
        assert blocked.status_code == 422
        assert "read-only" in blocked.json()["detail"]
    app.state.executor.shutdown()
