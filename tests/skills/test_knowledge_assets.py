import json
from pathlib import Path

from hydro_agent.knowledge.catalog import GovernedKnowledgeRepository
from hydro_agent.knowledge.expert import ExpertPriorEngine
from hydro_agent.knowledge.governance import KnowledgeQueryContext
from hydro_agent.skills import SkillRegistry
from hydro_agent.skills.manager import SkillManager


def _write_skill(root: Path) -> Path:
    skill_dir = root / "xaj-calibration"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: xaj-calibration
description: XAJ calibration skill
---

# XAJ
""",
        encoding="utf-8",
    )
    return skill_dir


def test_user_skill_assets_drive_expert_priors(monkeypatch, tmp_path: Path):
    builtin_root = tmp_path / "builtin"
    user_root = tmp_path / "user"
    builtin = _write_skill(builtin_root)
    expert_dir = builtin / "assets" / "expert"
    expert_dir.mkdir(parents=True)
    payload = {
        "knowledge_id": "hydrologist-calibration-priors-v1",
        "status": "seed_prior",
        "authority": "advisory_only",
        "governance": {
            "revision": 1,
            "category": "expert_diagnostic_prior",
            "review_status": "approved",
            "verification_status": "unverified",
            "applicability": {"model_ids": ["xaj"]},
        },
        "rules": [
            {
                "rule_id": "expert.water_balance_first",
                "signal": "abs_pbias_percent_gte",
                "threshold": 10.0,
                "priority": 100,
                "recommendation": {"parameter_groups": ["evap", "runoff"]},
            }
        ],
    }
    (expert_dir / "hydrologist-calibration-priors-v1.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    monkeypatch.setenv("HYDRO_AGENT_SKILLS_DIR", str(user_root))

    registry = SkillRegistry(builtin_root=builtin_root, user_root=user_root)
    manager = SkillManager(registry)
    payload["rules"][0]["threshold"] = 25.0
    manager.save_resource(
        "xaj-calibration",
        "assets/expert/hydrologist-calibration-priors-v1.json",
        json.dumps(payload),
    )

    engine = ExpertPriorEngine()
    context = KnowledgeQueryContext(model_id="xaj", allow_unverified_expert_priors=True)
    below = engine.advise({"metrics": {"pbias_percent": 20.0}}, governance_context=context)
    above = engine.advise({"metrics": {"pbias_percent": 30.0}}, governance_context=context)

    assert below.matched_prior_refs == ()
    assert above.matched_prior_refs == ("expert.water_balance_first@1",)


def test_user_skill_assets_drive_governed_catalog(monkeypatch, tmp_path: Path):
    builtin_root = tmp_path / "builtin"
    user_root = tmp_path / "user"
    builtin = _write_skill(builtin_root)
    governed_dir = builtin / "assets" / "governed"
    governed_dir.mkdir(parents=True)
    (governed_dir / "claims.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "knowledge_id": "expert.example",
                        "revision": 1,
                        "category": "expert_diagnostic_prior",
                        "authority": "advisory_only",
                        "claim": "builtin claim",
                        "source_id": "builtin",
                        "source_hash": "sha256:builtin",
                        "source_locator": "claims.json",
                        "applicability": {"model_ids": ["xaj"]},
                        "verification_status": "verified_in_scope",
                        "review_status": "approved",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HYDRO_AGENT_SKILLS_DIR", str(user_root))

    registry = SkillRegistry(builtin_root=builtin_root, user_root=user_root)
    manager = SkillManager(registry)
    manager.save_resource(
        "xaj-calibration",
        "assets/governed/claims.json",
        json.dumps(
            {
                "entries": [
                    {
                        "knowledge_id": "expert.example",
                        "revision": 2,
                        "category": "expert_diagnostic_prior",
                        "authority": "advisory_only",
                        "claim": "user claim",
                        "source_id": "user",
                        "source_hash": "sha256:user",
                        "source_locator": "claims.json",
                        "applicability": {"model_ids": ["xaj"]},
                        "verification_status": "verified_in_scope",
                        "review_status": "approved",
                    }
                ]
            }
        ),
    )

    repository = GovernedKnowledgeRepository()
    assert repository.entry("expert.example", 2).claim == "user claim"
