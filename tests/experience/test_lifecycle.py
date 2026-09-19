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
    promoted_v2 = repository.get_experience_skill_version(2)
    changes = promoted_v2.manifest_json["structural_changes"]
    assert changes[0]["operation"] == "CREATE"
    assert changes[0]["proposal_ids"]
    assert "successful calibration" in changes[0]["reason"]

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


def test_reprocessing_same_completed_task_does_not_mint_new_version(
    repository,
    tmp_path,
):
    store = ExperienceSkillVersionStore(
        tmp_path / "experience-store-idempotent",
        repository=repository,
    )
    service = ExperienceEvolutionService(
        repository,
        version_store=store,
        promotion_service=AlwaysPromote(store),
    )
    service.ensure_baseline()

    seed_completed_task(repository, "task-once")
    first = service.process_completed_task("task-once")
    second = service.process_completed_task("task-once")

    assert first.candidate_version == 2
    assert first.promotion_accepted is True
    assert second.structural_change is False
    assert second.candidate_version is None
    assert "ALREADY_PROCESSED" in second.reasons
    assert [
        row.version
        for row in repository.list_experience_skill_versions()
    ] == [1, 2]


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



def test_pending_candidate_uses_next_task_as_holdout_before_reflection(
    repository,
    tmp_path,
):
    store = ExperienceSkillVersionStore(
        tmp_path / "pending-lifecycle-store",
        repository=repository,
    )
    skills = SkillRegistry(
        builtin_root=tmp_path / "builtin-pending",
        agent_root=store.current_root,
        user_root=tmp_path / "user-pending",
        repository=repository,
    )

    class PendingThenPromote:
        def __init__(self):
            self.calls = []

        def validate_and_promote(self, candidate_version: int):
            self.calls.append(candidate_version)
            if len(self.calls) == 1:
                return PromotionDecision(
                    accepted=False,
                    reasons=("INSUFFICIENT_REGRESSION_CASES",),
                )
            store.promote(
                candidate_version,
                regression={"passed": True, "holdout": "task-b"},
            )
            return PromotionDecision(
                accepted=True,
                reasons=("NON_DEGRADING",),
            )

    promotion = PendingThenPromote()
    service = ExperienceEvolutionService(
        repository,
        version_store=store,
        promotion_service=promotion,
        skill_registry=skills,
    )
    service.ensure_baseline()

    seed_completed_task(repository, "task-a")
    first = service.process_completed_task("task-a")
    assert first.candidate_version == 2
    assert first.promotion_accepted is False
    assert repository.get_experience_skill_version(2).status == "candidate"
    experience_id = repository.list_active_experiences()[0].experience_id
    assert repository.get_experience(experience_id).revision == 1

    seed_completed_task(repository, "task-b")
    second = service.process_completed_task("task-b")

    # The pending v2 is validated first, before task-b is reflected into the
    # Experience State. Only after promotion does task-b REINFORCE the rule.
    assert promotion.calls == [2, 2]
    assert second.candidate_version == 2
    assert second.promotion_accepted is True
    assert repository.get_current_experience_skill_version().version == 2
    reinforced = repository.get_experience(experience_id)
    assert reinforced.revision == 2
    assert {ref.task_id for ref in reinforced.supporting_evidence} == {
        "task-a",
        "task-b",
    }



def test_single_p1_hypothesis_case_does_not_auto_create_validated_rule(
    repository,
    tmp_path,
):
    store = ExperienceSkillVersionStore(
        tmp_path / "experience-store-p1-case",
        repository=repository,
    )
    service = ExperienceEvolutionService(
        repository,
        version_store=store,
        promotion_service=AlwaysPromote(store),
    )
    service.ensure_baseline()
    seed_completed_task(repository, "task-p1")
    repository.add_evidence(
        EvidencePacket(
            evidence_id="task-p1-optimize",
            task_id="task-p1",
            action=ActionCode.A05_OPTIMIZE,
            status="succeeded",
            observations=(),
            metrics={"model_evaluations": 32.0},
            gates={
                "calibration_hypothesis_id": "routing-too-slow",
                "diagnostic_signature_json": '["repeated_late_peaks"]',
                "adjustment_direction": "accelerate_routing",
                "direction_verification_status": "supported",
                "direction_evidence_ids_json": '["event-001","event-004"]',
                "strategy_id": "xaj-bounded-v1",
                "param_groups": "routing",
                "objective": "nse",
            },
            new_information_hash="task-p1-optimize-hash",
        )
    )

    outcome = service.process_completed_task("task-p1")

    assert outcome.structural_change is False
    assert outcome.candidate_version is None
    assert repository.list_active_experiences() == []
    assert repository.get_current_experience_skill_version().version == 1
