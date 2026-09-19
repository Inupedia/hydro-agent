import pytest
from pydantic import ValidationError

from hydro_agent.experience.contracts import (
    ExperienceEntry,
    ExperienceEvidenceRef,
    ExperienceScope,
)
from hydro_agent.experience.diff import ExperienceDiff, is_structural_change
from hydro_agent.experience.reflection import (
    ExperienceDiffApplier,
    ExperienceReflectionEngine,
    build_hypothesis_outcome_cases,
)
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


def entry(experience_id: str, *, confidence: float = 0.65):
    return ExperienceEntry(
        experience_id=experience_id,
        revision=1,
        category="model",
        scope=ExperienceScope(model_ids=("xaj",), basin_ids=("basin-a",)),
        pattern={"peak_bias": "negative"},
        decision={"prefer_param_groups": ["routing"]},
        supporting_evidence=(),
        contradicting_evidence=(),
        confidence=confidence,
        status="active",
    )


def evidence(evidence_id: str = "evidence-1"):
    return ExperienceEvidenceRef(
        task_id="task-1",
        experiment_id="exp-1",
        evidence_id=evidence_id,
    )


@pytest.fixture
def repository(tmp_path):
    database = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    database.create_schema()
    return HydroRepository(database)


def test_reinforce_is_not_structural():
    diff = ExperienceDiff(
        operation="REINFORCE",
        experience_id="EXP-XAJ-1",
        evidence_refs=(evidence(),),
        reason="routing improvement repeated",
    )
    assert is_structural_change(diff) is False


def test_split_is_structural():
    diff = ExperienceDiff(
        operation="SPLIT",
        experience_id="EXP-XAJ-1",
        proposals=(entry("EXP-XAJ-1A"), entry("EXP-XAJ-1B")),
        reason="counterexamples show two distinct regimes",
    )
    assert is_structural_change(diff) is True


def test_create_requires_exactly_one_new_active_revision():
    with pytest.raises(ValidationError, match="exactly one proposal"):
        ExperienceDiff(operation="CREATE", proposals=(), reason="new pattern")

    bad = entry("EXP-NEW").model_copy(update={"revision": 2})
    with pytest.raises(ValidationError, match="revision 1"):
        ExperienceDiff(operation="CREATE", proposals=(bad,), reason="new pattern")


def test_merge_requires_multiple_sources_and_one_result():
    with pytest.raises(ValidationError, match="at least two source_ids"):
        ExperienceDiff(
            operation="MERGE",
            source_ids=("EXP-1",),
            proposals=(entry("EXP-MERGED"),),
            reason="same decision rule",
        )

    diff = ExperienceDiff(
        operation="MERGE",
        source_ids=("EXP-1", "EXP-2"),
        proposals=(entry("EXP-MERGED"),),
        reason="same decision rule",
    )
    assert is_structural_change(diff) is True


def test_reinforce_and_weaken_require_evidence():
    for operation in ("REINFORCE", "WEAKEN"):
        with pytest.raises(ValidationError, match="requires evidence_refs"):
            ExperienceDiff(
                operation=operation,
                experience_id="EXP-XAJ-1",
                reason="evidence is mandatory",
            )


class ScriptedReflectionProvider:
    def __init__(self, diffs):
        self.diffs = tuple(diffs)
        self.received = None

    def reflect(self, reflection_input):
        self.received = reflection_input
        return self.diffs


def test_reflection_engine_collects_active_task_context(repository):
    repository.create_task(
        task_id="task-1",
        basin_id="basin-a",
        phase="B",
        forcing_mode="R",
        workflow_id="test",
        workflow_version="1",
        workflow_hash="hash",
    )
    repository.create_scheme(
        scheme_id="scheme-1",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={},
        content_hash="scheme-hash",
    )
    repository.append_experience_revision(entry("EXP-R"))

    keep = ExperienceDiff(
        operation="KEEP",
        experience_id="EXP-R",
        reason="current rule remains supported",
    )
    provider = ScriptedReflectionProvider((keep,))
    result = ExperienceReflectionEngine(repository, provider=provider).reflect("task-1")

    assert result.diffs == (keep,)
    assert provider.received.model_id == "xaj"
    assert provider.received.basin_id == "basin-a"
    assert [item.experience_id for item in provider.received.active_experiences] == ["EXP-R"]


def test_applier_reinforces_and_splits_without_provider_writes(repository):
    repository.append_experience_revision(entry("EXP-R"))
    repository.append_experience_revision(entry("EXP-S", confidence=0.8))

    reinforce = ExperienceDiff(
        operation="REINFORCE",
        experience_id="EXP-R",
        evidence_refs=(evidence("evidence-new"),),
        reason="routing adjustment improved another similar case",
    )
    split = ExperienceDiff(
        operation="SPLIT",
        experience_id="EXP-S",
        proposals=(entry("EXP-S-WET"), entry("EXP-S-DRY")),
        evidence_refs=(evidence("counterexample-1"),),
        reason="wet and dry regimes require different priorities",
    )

    result = ExperienceDiffApplier(repository).apply(
        "task-1",
        (reinforce, split),
    )

    assert result.accepted == (reinforce, split)
    assert result.rejected == ()
    assert result.structural_change is True

    reinforced = repository.get_experience("EXP-R")
    assert reinforced.revision == 2
    assert reinforced.confidence == pytest.approx(0.70)
    assert reinforced.supporting_evidence[-1].evidence_id == "evidence-new"

    superseded = repository.get_experience("EXP-S")
    assert superseded.revision == 2
    assert superseded.status == "superseded"
    assert repository.get_experience("EXP-S-WET").status == "active"
    assert repository.get_experience("EXP-S-DRY").status == "active"

    events = repository.list_experience_evolution_events()
    assert [event.event_type for event in events] == ["REINFORCE", "SPLIT"]


def test_applier_rejects_missing_target_without_mutating_state(repository):
    diff = ExperienceDiff(
        operation="WEAKEN",
        experience_id="EXP-MISSING",
        evidence_refs=(evidence(),),
        reason="counterexample",
    )
    result = ExperienceDiffApplier(repository).apply("task-1", (diff,))

    assert result.accepted == ()
    assert result.structural_change is False
    assert result.rejected and result.rejected[0].startswith("WEAKEN:")
    assert repository.list_experience_evolution_events() == []



def test_hypothesis_outcome_case_preserves_supported_direction_evidence():
    cases = build_hypothesis_outcome_cases(
        "task-1",
        (
            {
                "evidence_id": "opt-1",
                "action": "A05_OPTIMIZE",
                "status": "succeeded",
                "gates": {
                    "calibration_hypothesis_id": "routing-too-slow",
                    "diagnostic_signature_json": '["water_balance_near_neutral","repeated_late_peaks"]',
                    "adjustment_direction": "accelerate_routing",
                    "direction_verification_status": "supported",
                    "direction_evidence_ids_json": '["event-001","event-004"]',
                },
            },
            {
                "evidence_id": "resolve-1",
                "action": "A07_RESOLVE",
                "status": "ACCEPT",
                "gates": {"candidate_adopted": "true"},
            },
        ),
    )

    assert len(cases) == 1
    case = cases[0]
    assert case.hypothesis_id == "routing-too-slow"
    assert case.hypothesis_status == "supported"
    assert case.direction == "accelerate_routing"
    assert case.direction_verification_status == "supported"
    assert "event-001" in case.evidence_refs
    assert case.maturity == "case"


def test_refuted_and_inconclusive_direction_cases_are_not_discarded():
    refuted = build_hypothesis_outcome_cases(
        "task-1",
        (
            {
                "evidence_id": "opt-r",
                "action": "A05_OPTIMIZE",
                "status": "blocked",
                "gates": {
                    "calibration_hypothesis_id": "routing-too-slow",
                    "diagnostic_signature_json": '["repeated_late_peaks"]',
                    "adjustment_direction": "accelerate_routing",
                    "direction_verification_status": "refuted",
                    "direction_evidence_ids_json": '["event-001"]',
                },
            },
        ),
    )
    inconclusive = build_hypothesis_outcome_cases(
        "task-2",
        (
            {
                "evidence_id": "opt-i",
                "action": "A05_OPTIMIZE",
                "status": "blocked",
                "gates": {
                    "calibration_hypothesis_id": "routing-too-slow",
                    "diagnostic_signature_json": '["repeated_late_peaks"]',
                    "adjustment_direction": "accelerate_routing",
                    "direction_verification_status": "inconclusive",
                    "direction_evidence_ids_json": '["event-002"]',
                },
            },
        ),
    )

    assert refuted[0].hypothesis_status == "refuted"
    assert inconclusive[0].hypothesis_status == "inconclusive"
    assert refuted[0].maturity == inconclusive[0].maturity == "case"


def test_reflection_engine_exposes_persisted_hypothesis_case_without_promoting_rule(repository):
    from hydro_agent.agent.contracts import ActionCode, EvidencePacket

    repository.create_task(
        task_id="task-case",
        basin_id="basin-a",
        phase="B",
        forcing_mode="R",
        workflow_id="test",
        workflow_version="1",
        workflow_hash="hash",
    )
    repository.create_scheme(
        scheme_id="scheme-case",
        task_id="task-case",
        model_id="xaj",
        status="base",
        config={},
        content_hash="scheme-hash",
    )
    repository.add_evidence(
        EvidencePacket(
            evidence_id="opt-case",
            task_id="task-case",
            action=ActionCode.A05_OPTIMIZE,
            status="blocked",
            observations=(),
            metrics={},
            gates={
                "calibration_hypothesis_id": "routing-too-slow",
                "diagnostic_signature_json": '["repeated_late_peaks"]',
                "adjustment_direction": "accelerate_routing",
                "direction_verification_status": "refuted",
                "direction_evidence_ids_json": '["event-001"]',
            },
            new_information_hash="case-hash",
        )
    )

    provider = ScriptedReflectionProvider(())
    ExperienceReflectionEngine(repository, provider=provider).reflect("task-case")

    assert provider.received.hypothesis_cases[0].hypothesis_status == "refuted"
    assert provider.received.hypothesis_cases[0].evidence_refs == ("event-001", "opt-case")
    assert provider.received.active_experiences == ()
