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


def test_skill_api_builtin_readonly_and_user_crud(app_dependencies, tmp_path: Path):
    builtin_root = tmp_path / "builtin-skills"
    user_root = tmp_path / "user-skills"
    builtin = _write_skill(builtin_root, "demo-skill", "builtin description")
    original = (builtin / "SKILL.md").read_text(encoding="utf-8")
    app_dependencies.skills = SkillRegistry(builtin_root=builtin_root, user_root=user_root)

    app = create_app(app_dependencies)
    with TestClient(app) as client:
        listing = client.get("/api/skills")
        assert listing.status_code == 200
        item = listing.json()["items"][0]
        assert item["source"] == "builtin"
        assert item["editable"] is False

        blocked = client.put(
            "/api/skills/demo-skill",
            json={
                "skill_md": """---
name: demo-skill
description: should fail
---

# Nope
"""
            },
        )
        assert blocked.status_code == 422
        assert "read-only" in blocked.json()["detail"]
        assert (builtin / "SKILL.md").read_text(encoding="utf-8") == original

        created = """---
name: custom-skill
description: API managed user skill
metadata:
  title_zh: "自定义"
---

# Custom
"""
        response = client.put("/api/skills/custom-skill", json={"skill_md": created})
        assert response.status_code == 200
        assert response.json()["source"] == "user"
        assert response.json()["editable"] is True

        detail = client.get("/api/skills/custom-skill")
        assert detail.status_code == 200
        assert detail.json()["skill_md"] == created

        binding = client.put(
            "/api/skills/custom-skill/binding",
            json={"activation_stages": ["diagnosis"], "activation_model_ids": ["xaj"]},
        )
        assert binding.status_code == 200
        assert binding.json()["activation_stages"] == ["diagnosis"]
        assert binding.json()["activation_model_ids"] == ["xaj"]
        assert "activation_stages" not in binding.json()["skill_md"]

        validation = client.post(
            "/api/skills/custom-skill/validate",
            json={"skill_md": created},
        )
        assert validation.status_code == 200
        assert validation.json() == {
            "standard_compatible": True,
            "domain_ready": True,
            "errors": [],
            "warnings": [],
        }

        invalid = client.put(
            "/api/skills/custom-skill/binding",
            json={"activation_stages": ["unknown"], "activation_model_ids": []},
        )
        assert invalid.status_code == 422

        deleted = client.delete("/api/skills/custom-skill/override")
        assert deleted.status_code == 200
        assert deleted.json()["active"] is False
        assert deleted.json()["restored_builtin"] is False
    app.state.executor.shutdown()


def test_skill_api_resource_write_requires_user_skill(app_dependencies, tmp_path: Path):
    builtin_root = tmp_path / "builtin-skills"
    user_root = tmp_path / "user-skills"
    _write_skill(builtin_root, "demo-skill", "builtin description")
    app_dependencies.skills = SkillRegistry(builtin_root=builtin_root, user_root=user_root)

    app = create_app(app_dependencies)
    with TestClient(app) as client:
        blocked = client.put(
            "/api/skills/demo-skill/resources/references/notes.md",
            json={"content": "# Notes\nhello\n"},
        )
        assert blocked.status_code == 422
        assert "read-only" in blocked.json()["detail"]

        client.put(
            "/api/skills/custom-skill",
            json={
                "skill_md": """---
name: custom-skill
description: writable user skill
---

# Custom
"""
            },
        )
        response = client.put(
            "/api/skills/custom-skill/resources/references/notes.md",
            json={"content": "# Notes\nhello\n"},
        )
        assert response.status_code == 200
        assert response.json()["source"] == "user"

        resource = client.get("/api/skills/custom-skill/resources/references/notes.md")
        assert resource.status_code == 200
        assert resource.json()["content"] == "# Notes\nhello\n"

        script_blocked = client.put(
            "/api/skills/custom-skill/resources/scripts/run.py",
            json={"content": "print('blocked')\n"},
        )
        assert script_blocked.status_code == 422
        assert "read-only" in script_blocked.json()["detail"]
    app.state.executor.shutdown()


def test_skill_api_copy_from_builtin(app_dependencies, tmp_path: Path):
    builtin_root = tmp_path / "builtin-skills"
    user_root = tmp_path / "user-skills"
    builtin = _write_skill(builtin_root, "demo-skill", "builtin description")
    (builtin / "references").mkdir()
    (builtin / "references" / "notes.md").write_text("# Notes\n", encoding="utf-8")
    app_dependencies.skills = SkillRegistry(builtin_root=builtin_root, user_root=user_root)

    app = create_app(app_dependencies)
    with TestClient(app) as client:
        response = client.post("/api/skills/demo-skill/copy-from-builtin")
        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "user"
        assert payload["editable"] is True
        assert (user_root / "demo-skill" / "SKILL.md").is_file()

        again = client.post("/api/skills/demo-skill/copy-from-builtin")
        assert again.status_code == 422
        assert "already exists" in again.json()["detail"]
    app.state.executor.shutdown()
