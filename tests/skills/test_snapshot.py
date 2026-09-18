import json
from pathlib import Path

import pytest

from hydro_agent.agent.contracts import (
    ActionCode,
    BudgetSummary,
    ModelSummary,
    PermissionSummary,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.skills import SkillRegistry
from hydro_agent.skills.expert import ExpertPriorEngine
from hydro_agent.skills.snapshot import build_snapshot, snapshot_file_bytes


def test_task_skill_snapshot_replays_original_package_after_edit_and_restart(tmp_path: Path):
    builtin_root = tmp_path / "builtin"
    skill_dir = builtin_root / "hydrology-data-review"
    (skill_dir / "references").mkdir(parents=True)
    skill_md = """---
name: hydrology-data-review
description: Review data evidence.
metadata:
  prompt_references: "references/data.md"
---

# Original instructions
"""
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (skill_dir / "references" / "data.md").write_text("Original reference\n", encoding="utf-8")
    (skill_dir / "assets" / "expert").mkdir(parents=True)
    prior_path = skill_dir / "assets" / "expert" / "prior.json"
    prior_path.write_text(
        json.dumps({"knowledge_id": "prior-source", "message": "Original prior", "rules": []}),
        encoding="utf-8",
    )

    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repository = HydroRepository(db)
    repository.create_task(task_id="task-snapshot", basin_id="yaogu", phase="B", forcing_mode="R")
    repository.create_scheme(
        scheme_id="base",
        task_id="task-snapshot",
        model_id="xaj",
        status="base",
        config={"parameters": {"K": 0.7}},
        content_hash="base-hash",
    )
    repository.ensure_task_state("task-snapshot", current_scheme_id="base")
    registry = SkillRegistry(
        builtin_root=builtin_root, user_root=tmp_path / "user", repository=repository
    )
    snapshot = registry.freeze_for_task("task-snapshot")
    assert SkillRegistry.from_snapshot(snapshot).get_loaded("hydrology-data-review").body == ""
    assert snapshot_file_bytes(
        snapshot["skills"]["hydrology-data-review"]["files"], "SKILL.md"
    ).decode("utf-8") == skill_md

    (skill_dir / "SKILL.md").write_text(skill_md.replace("Original", "Changed"), encoding="utf-8")
    (skill_dir / "references" / "data.md").write_text("Changed reference\n", encoding="utf-8")
    prior_path.write_text(
        json.dumps({"knowledge_id": "prior-source", "message": "Changed prior", "rules": []}),
        encoding="utf-8",
    )
    assert ExpertPriorEngine(snapshot=snapshot).source("prior-source")["message"] == "Original prior"
    view = WorldStateView(
        task=TaskSummary(task_id="task-snapshot", basin_id="yaogu", phase="B", forcing_mode="R"),
        model=ModelSummary(model_id="xaj", capabilities=("forecast",)),
        scheme=SchemeSummary(scheme_id="base", status="base", content_hash="base-hash"),
        permissions=PermissionSummary(safe_actions=(ActionCode.A02_VALIDATE_SCHEME,)),
        budget=BudgetSummary(
            agent_rounds_remaining=10,
            optimization_cycles_remaining=1,
            max_agent_rounds=10,
            max_optimization_cycles=1,
        ),
    )
    for active in (
        registry,
        SkillRegistry(builtin_root=builtin_root, user_root=tmp_path / "user", repository=repository),
    ):
        ids, prompt, audit = active.activated_for_prompt_with_audit(view)
        assert ids == ("hydrology-data-review",)
        assert "Original instructions" in prompt
        assert "Original reference" in prompt
        assert "Changed instructions" not in prompt
        assert audit[0]["skill_sha256"] == snapshot["skills"][ids[0]]["files"]["SKILL.md"]["sha256"]
        assert audit[0]["snapshot_sha256"] == snapshot["sha256"]
        assert len(audit[0]["binding_sha256"]) == 64
    with pytest.raises(ValueError, match="already frozen"):
        repository.set_skill_snapshot("task-snapshot", build_snapshot({}))



def test_agent_skill_is_captured_in_task_snapshot(tmp_path: Path):
    builtin_root = tmp_path / "builtin"
    agent_root = tmp_path / "agent"
    user_root = tmp_path / "user"
    skill_dir = agent_root / "calibration-experience"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: calibration-experience
description: Uses learned calibration experience during experiment planning.
metadata:
  activation_stages: "diagnosis,experiment"
---

# Agent experience
""",
        encoding="utf-8",
    )

    db = Database(f"sqlite+pysqlite:///{tmp_path}/agent-snapshot.db")
    db.create_schema()
    repository = HydroRepository(db)
    repository.create_task(
        task_id="task-agent-snapshot",
        basin_id="basin-a",
        phase="B",
        forcing_mode="R",
    )
    repository.create_scheme(
        scheme_id="base-agent",
        task_id="task-agent-snapshot",
        model_id="xaj",
        status="base",
        config={},
        content_hash="base-agent-hash",
    )
    repository.ensure_task_state(
        "task-agent-snapshot",
        current_scheme_id="base-agent",
    )

    registry = SkillRegistry(
        builtin_root=builtin_root,
        agent_root=agent_root,
        user_root=user_root,
        repository=repository,
    )
    snapshot = registry.freeze_for_task("task-agent-snapshot")

    assert snapshot["skills"]["calibration-experience"]["source"] == "agent"
    frozen = SkillRegistry.from_snapshot(snapshot)
    assert frozen.source("calibration-experience") == "agent"
