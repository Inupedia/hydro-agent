import pytest

from hydro_agent.agent.contracts import ActionCode, EvidencePacket
from hydro_agent.experience.lifecycle import ExperienceEvolutionService
from hydro_agent.experience.promotion import PromotionDecision
from hydro_agent.experience.skill_versions import ExperienceSkillVersionStore
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository
from hydro_agent.skills import SkillRegistry


@pytest.fixture
def repository(tmp_path):
    database = Database(f"sqlite+pysqlite:///{tmp_path}/experience-lifecycle.db")
    database.create_schema()
    return HydroRepository(database)


def seed_completed_task(repository, task_id: str, *, outcome: str = "ACCEPT"):
    repository.create_task(
        task_id=task_id,
        basin_id="basin-a",
        phase="E",
        forcing_mode="R",
    )
    repository.create_scheme(
        scheme_id=f"{task_id}-scheme",
        task_id=task_id,
        model_id="xaj",
        status="frozen",
        config={"parameters": {}, "workbench": {}},
        content_hash=f"{task_id}-hash",
    )
    repository.ensure_task_state(
        task_id,
        current_scheme_id=f"{task_id}-scheme",
    )
    repository.update_task_state(
        task_id,
        needs_follow_up=False,
        paused=False,
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id=f"{task_id}-diagnosis",
            task_id=task_id,
            action=ActionCode.A04_DIAGNOSE,
            status="succeeded",
            observations=("hypothesis=MODEL",),
            metrics={"nse": 0.3},
            gates={
                "hypothesis": "MODEL",
                "recommended_strategy_id": "xaj-bounded-v1",
                "recommended_param_groups": "routing",
                "recommended_objective": "nse",
            },
            new_information_hash=f"{task_id}-diagnosis-hash",
        )
    )
    repository.record_agent_decision(
        decision_id=f"{task_id}-decision",
        task_id=task_id,
        round_number=1,
        provider="fixture",
        model="fixture",
        world_state_hash=f"{task_id}-world",
        action="A05_OPTIMIZE",
        hypothesis="MODEL",
        strategy_id="xaj-bounded-v1",
        rationale_summary="test calibration",
        input_tokens=None,
        output_tokens=None,
        activated_skills_json=[],
        experience_audit_json=None,
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id=f"{task_id}-resolve",
            task_id=task_id,
            action=ActionCode.A07_RESOLVE,
            status=outcome,
            observations=(f"outcome={outcome}",),
            metrics={},
            gates={"experiment_plan_id": f"{task_id}-experiment"},
            new_information_hash=f"{task_id}-resolve-hash",
        )
    )


class AlwaysPromote:
    def __init__(self, store):
        self.store = store

    def validate_and_promote(self, candidate_version: int) -> PromotionDecision:
        self.store.promote(
            candidate_version,
            regression={"passed": True, "fixture": True},
        )
        return PromotionDecision(accepted=True, reasons=("NON_DEGRADING",))


def test_completed_tasks_create_then_reinforce_without_version_churn(
    repository,
    tmp_path,
):
    store = ExperienceSkillVersionStore(
        tmp_path / "experience-store",
        repository=repository,
    )
    skills = SkillRegistry(
        builtin_root=tmp_path / "builtin",
        agent_root=store.current_root,
        user_root=tmp_path / "user",
        repository=repository,
    )
    service = ExperienceEvolutionService(
        repository,
        version_store=store,
        promotion_service=AlwaysPromote(store),
        skill_registry=skills,
    )
    assert service.ensure_baseline() == 1

    seed_completed_task(repository, "task-a")
    first = service.process_completed_task("task-a")
    assert first.structural_change is True
    assert first.candidate_version == 2
    assert first.promotion_accepted is True
    assert repository.get_current_experience_skill_version().version == 2

    entries = repository.list_active_experiences()
    assert len(entries) == 1
    experience_id = entries[0].experience_id
    assert entries[0].revision == 1
    assert entries[0].confidence == pytest.approx(0.65)

    seed_completed_task(repository, "task-b")
    second = service.process_completed_task("task-b")
    assert second.structural_change is False
    assert second.candidate_version is None
    assert repository.get_current_experience_skill_version().version == 2

    reinforced = repository.get_experience(experience_id)
    assert reinforced.revision == 2
    assert reinforced.confidence == pytest.approx(0.70)
    assert {ref.task_id for ref in reinforced.supporting_evidence} == {
        "task-a",
        "task-b",
    }


def test_opposite_outcome_weakens_old_rule_and_creates_negative_rule(
    repository,
    tmp_path,
):
    store = ExperienceSkillVersionStore(
        tmp_path / "experience-store-opposite",
        repository=repository,
    )
    service = ExperienceEvolutionService(
        repository,
        version_store=store,
        promotion_service=AlwaysPromote(store),
    )
    service.ensure_baseline()

    seed_completed_task(repository, "task-positive")
    service.process_completed_task("task-positive")
    positive = repository.list_active_experiences()[0]

    seed_completed_task(repository, "task-negative", outcome="ROLLBACK")
    outcome = service.process_completed_task("task-negative")

    assert outcome.structural_change is True
    latest_positive = repository.get_experience(positive.experience_id)
    assert latest_positive.revision == 2
    assert latest_positive.confidence == pytest.approx(0.55)
    negatives = [
        entry
        for entry in repository.list_active_experiences()
        if entry.experience_id != positive.experience_id
    ]
    assert len(negatives) == 1
    assert negatives[0].decision["avoid_param_groups"] == ["routing"]
