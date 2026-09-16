import json
from pathlib import Path

from hydro_agent.skills import SkillRegistry
from hydro_agent.skills.catalog import GovernedKnowledgeRepository
from hydro_agent.skills.expert import ExpertPriorEngine
from hydro_agent.skills.governance import KnowledgeQueryContext
from hydro_agent.skills.manager import SkillManager


def _write_skill(root: Path, name: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: {name} skill
---

# {name}
""",
        encoding="utf-8",
    )
    return skill_dir


def test_user_focused_skill_assets_drive_expert_priors(monkeypatch, tmp_path: Path):
    builtin_root = tmp_path / "builtin"
    user_root = tmp_path / "user"
    builtin = _write_skill(builtin_root, "xaj-calibration-diagnosis")
    expert_dir = builtin / "assets" / "expert"
    expert_dir.mkdir(parents=True)
    payload = {
        "knowledge_id": "xaj-calibration-diagnosis-priors-v1",
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
    (expert_dir / "xaj-calibration-diagnosis-priors-v1.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    monkeypatch.setenv("HYDRO_AGENT_SKILLS_DIR", str(user_root))

    registry = SkillRegistry(builtin_root=builtin_root, user_root=user_root)
    manager = SkillManager(registry)
    manager.copy_from_builtin("xaj-calibration-diagnosis")
    payload["rules"][0]["threshold"] = 25.0
    manager.save_resource(
        "xaj-calibration-diagnosis",
        "assets/expert/xaj-calibration-diagnosis-priors-v1.json",
        json.dumps(payload),
    )

    engine = ExpertPriorEngine()
    context = KnowledgeQueryContext(model_id="xaj", allow_unverified_expert_priors=True)
    assert (
        engine.advise(
            {"metrics": {"pbias_percent": 20.0}},
            source_id="xaj-calibration-diagnosis-priors-v1",
            governance_context=context,
        ).matched_prior_refs
        == ()
    )
    assert engine.advise(
        {"metrics": {"pbias_percent": 30.0}},
        source_id="xaj-calibration-diagnosis-priors-v1",
        governance_context=context,
    ).matched_prior_refs == ("expert.water_balance_first@1",)


def test_user_focused_skill_assets_drive_governed_catalog(monkeypatch, tmp_path: Path):
    builtin_root = tmp_path / "builtin"
    user_root = tmp_path / "user"
    builtin = _write_skill(builtin_root, "xaj-calibration-diagnosis")
    governed_dir = builtin / "assets" / "governed"
    governed_dir.mkdir(parents=True)
    claim = {
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
    (governed_dir / "claims.json").write_text(json.dumps({"entries": [claim]}), encoding="utf-8")
    monkeypatch.setenv("HYDRO_AGENT_SKILLS_DIR", str(user_root))

    registry = SkillRegistry(builtin_root=builtin_root, user_root=user_root)
    manager = SkillManager(registry)
    manager.copy_from_builtin("xaj-calibration-diagnosis")
    claim.update(revision=2, claim="user claim", source_id="user", source_hash="sha256:user")
    manager.save_resource(
        "xaj-calibration-diagnosis",
        "assets/governed/claims.json",
        json.dumps({"entries": [claim]}),
    )

    repository = GovernedKnowledgeRepository()
    assert repository.entry("expert.example", 2).claim == "user claim"


def test_builtin_routing_prior_matches_peak_lag_hours():
    engine = ExpertPriorEngine()
    context = KnowledgeQueryContext(model_id="xaj", allow_unverified_expert_priors=True)
    advice = engine.advise(
        {"metrics": {"peak_lag_hours": 2.5, "nse": 0.55, "pbias_percent": 4.0}},
        governance_context=context,
    )
    assert "expert.routing_when_peak_lag_large@1" in advice.matched_prior_refs
    assert advice.recommended_param_groups == ("routing",)


def test_builtin_governed_claims_are_split_by_domain():
    repository = GovernedKnowledgeRepository()
    ids = {entry.knowledge_id for entry in repository.entries()}
    assert "expert.yaogu.xaj.water-balance-kc" in ids
    assert "expert.yaogu.xaj.recession-routing-dp1" in ids
    assert "case.yaogu.xaj.local-sensitivity-ranking" in ids
    assert "constraint.xaj.kg-ki-boundary.external-v3" in ids
