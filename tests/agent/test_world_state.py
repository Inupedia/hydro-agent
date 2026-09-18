from datetime import datetime, timezone

import pytest

from hydro_agent.agent.contracts import ActionCode, EvidencePacket
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository

ISSUE = datetime(2020, 5, 1, tzinfo=timezone.utc)


@pytest.fixture
def database(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    return db


@pytest.fixture
def seeded_repository(database):
    repo = HydroRepository(database)
    repo.create_task(task_id="task-1", basin_id="camels_13235000", phase="B", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-base",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={
            "model_id": "xaj",
            "warmup_days": 2,
            "parameters": {"K": 0.7},
            "workbench": {
                "calibration_objective": "composite",
                "allow_unverified_expert_priors": True,
                "forbidden_evidence_dataset_ids": ["same-campaign-observations"],
            },
        },
        content_hash="scheme-hash",
    )
    repo.create_snapshot(
        snapshot_id="snap-1",
        task_id="task-1",
        source="fixture",
        available_at=ISSUE,
        manifest={"files": []},
        content_hash="snap-hash",
    )
    return repo


def test_world_state_contains_only_decision_relevant_projection(seeded_repository):
    view = WorldStateBuilder(seeded_repository).build("task-1")
    assert view.task.task_id == "task-1"
    assert view.model.model_id == "xaj"
    assert view.model.validation_status == "source_verified"
    assert view.model.implementation_name == "pinned hydromodel XAJ teacher kernel"
    assert view.scheme.scheme_id == "scheme-base"
    assert view.hydro.campaign_objective == "composite"
    assert view.hydro.allow_unverified_expert_priors is True
    assert view.hydro.forbidden_evidence_dataset_ids == ("same-campaign-observations",)
    assert view.permissions.safe_actions
    assert not hasattr(view, "database_url")
    assert not hasattr(view, "filesystem_root")


def test_v1_task_cannot_be_reinterpreted_by_v2_agent_runtime(database):
    repo = HydroRepository(database)
    repo.create_task(
        task_id="legacy-task",
        basin_id="b",
        phase="B",
        forcing_mode="R",
        workflow_id="hydro-agent-calibration",
        workflow_version="1.0.0",
        workflow_hash="sha256:historical",
    )
    with pytest.raises(ValueError, match="bound to workflow 1.0.0"):
        WorldStateBuilder(repo).build("legacy-task")


def test_world_state_surfaces_audited_basin_prior_from_diagnosis(seeded_repository):
    seeded_repository.ensure_task_state("task-1", current_scheme_id="scheme-base")
    seeded_repository.add_evidence(
        EvidencePacket(
            evidence_id="ev-diagnosis-1",
            task_id="task-1",
            action=ActionCode.A04_DIAGNOSE,
            status="succeeded",
            observations=(
                'basin_attributes_json={"aridity": 0.62, "runoff_ratio": 0.41}',
            ),
            metrics={"nse": 0.2},
            gates={
                "hypothesis": "MODEL",
                "recommended_action": "A05_OPTIMIZE",
                "recommended_strategy_id": "xaj-bounded-v1",
            },
            new_information_hash="hash-diagnosis-1",
        )
    )

    view = WorldStateBuilder(seeded_repository).build("task-1")
    attrs = view.hydro.diagnosis["basin_attributes"]
    assert attrs == {"aridity": 0.62, "runoff_ratio": 0.41}
    assert view.hydro.diagnosis["metrics"]["nse"] == 0.2


def test_agent_budget_survives_repository_reopen(database, seeded_repository):
    seeded_repository.ensure_task_state("task-1", current_scheme_id="scheme-base")
    seeded_repository.update_task_state(
        "task-1",
        current_scheme_id="scheme-base",
        agent_rounds_used=3,
        optimization_cycles_used=1,
        paused=False,
        needs_follow_up=True,
    )
    reopened = HydroRepository(database)
    state = reopened.get_task_state("task-1")
    assert state.agent_rounds_used == 3
    assert state.optimization_cycles_used == 1



def test_world_state_uses_frozen_experience_skill_revision(tmp_path):
    from hydro_agent.experience.compiler import ExperienceSkillCompiler
    from hydro_agent.experience.contracts import ExperienceEntry, ExperienceScope
    from hydro_agent.experience.skill_versions import ExperienceSkillVersionStore
    from hydro_agent.skills import SkillRegistry

    db = Database(f"sqlite+pysqlite:///{tmp_path}/experience-world.db")
    db.create_schema()
    repo = HydroRepository(db)
    repo.create_task(
        task_id="task-exp",
        basin_id="basin-a",
        phase="B",
        forcing_mode="R",
    )
    repo.create_scheme(
        scheme_id="scheme-exp",
        task_id="task-exp",
        model_id="xaj",
        status="base",
        config={"parameters": {}, "workbench": {}},
        content_hash="scheme-exp-hash",
    )
    repo.ensure_task_state("task-exp", current_scheme_id="scheme-exp")
    entry_v1 = ExperienceEntry(
        experience_id="EXP-XAJ-1",
        revision=1,
        category="model",
        scope=ExperienceScope(model_ids=("xaj",), basin_ids=("basin-a",)),
        pattern={},
        decision={"prefer_param_groups": ["routing"]},
        supporting_evidence=(),
        contradicting_evidence=(),
        confidence=0.9,
        status="active",
    )
    repo.append_experience_revision(entry_v1)

    store = ExperienceSkillVersionStore(tmp_path / "experience-store", repository=repo)
    compiled = ExperienceSkillCompiler().compile(1, (entry_v1,))
    store.create_candidate(compiled)
    store.promote(1)

    skills = SkillRegistry(
        builtin_root=tmp_path / "builtin",
        agent_root=store.current_root,
        user_root=tmp_path / "user",
        repository=repo,
    )
    view = WorldStateBuilder(repo, skills=skills).build("task-exp")

    assert view.hydro.experience.skill_version == 1
    assert view.hydro.experience.skill_hash == compiled.sha256
    assert view.hydro.experience.source_revisions == {"EXP-XAJ-1": 1}
    assert [match.experience_id for match in view.hydro.experience.matches] == ["EXP-XAJ-1"]
    assert view.hydro.experience.matches[0].revision == 1

    repo.append_experience_revision(entry_v1.model_copy(update={"revision": 2, "confidence": 0.2}))
    rebuilt = WorldStateBuilder(repo, skills=skills).build("task-exp")
    assert rebuilt.hydro.experience.skill_version == 1
    assert rebuilt.hydro.experience.matches[0].revision == 1
    assert rebuilt.hydro.experience.matches[0].confidence == 0.9


    # A later task keeps the same structural Skill v1, but freezes the latest
    # state optimization (revision 2) at its own start.
    repo.create_task(
        task_id="task-exp-next",
        basin_id="basin-a",
        phase="B",
        forcing_mode="R",
    )
    repo.create_scheme(
        scheme_id="scheme-exp-next",
        task_id="task-exp-next",
        model_id="xaj",
        status="base",
        config={"parameters": {}, "workbench": {}},
        content_hash="scheme-exp-next-hash",
    )
    repo.ensure_task_state("task-exp-next", current_scheme_id="scheme-exp-next")
    next_view = WorldStateBuilder(repo, skills=skills).build("task-exp-next")
    assert next_view.hydro.experience.skill_version == 1
    assert next_view.hydro.experience.source_revisions == {"EXP-XAJ-1": 2}
    assert next_view.hydro.experience.matches[0].revision == 2
    assert next_view.hydro.experience.matches[0].confidence == 0.2
