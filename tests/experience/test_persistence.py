import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from hydro_agent.experience.contracts import (
    ExperienceEntry,
    ExperienceEvidenceRef,
    ExperienceScope,
)
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


@pytest.fixture
def database(tmp_path):
    return Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")


@pytest.fixture
def repository(database):
    database.create_schema()
    return HydroRepository(database)


def make_entry(
    experience_id="EXP-XAJ-1",
    revision=1,
    model_ids=("xaj",),
    basin_ids=("basin-a",),
    status="active",
    confidence=0.7,
):
    return ExperienceEntry(
        experience_id=experience_id,
        revision=revision,
        category="model",
        scope=ExperienceScope(
            model_ids=model_ids,
            basin_ids=basin_ids,
        ),
        pattern={"peak_bias": "negative"},
        decision={"prefer_param_groups": ["routing"]},
        supporting_evidence=(
            ExperienceEvidenceRef(
                task_id="task-1",
                experiment_id="experiment-1",
                evidence_id="evidence-1",
            ),
        ),
        contradicting_evidence=(),
        confidence=confidence,
        status=status,
    )


def test_database_creates_experience_tables(database):
    database.create_schema()

    names = set(inspect(database.engine).get_table_names())
    assert "experience_revisions" in names
    assert "experience_skill_versions" in names
    assert "experience_evolution_events" in names


def test_append_revision_and_read_latest(repository):
    first = repository.append_experience_revision(make_entry())
    repository.append_experience_revision(
        make_entry(revision=2, confidence=0.8)
    )

    assert first.source_hash
    assert repository.get_experience("EXP-XAJ-1", 1).confidence == 0.7
    latest = repository.get_experience("EXP-XAJ-1")
    assert latest.revision == 2
    assert latest.confidence == 0.8


def test_duplicate_revision_is_rejected(repository):
    repository.append_experience_revision(make_entry())
    with pytest.raises(IntegrityError):
        repository.append_experience_revision(make_entry())


def test_latest_non_active_revision_does_not_revive_old_active(repository):
    repository.append_experience_revision(make_entry())
    repository.append_experience_revision(
        make_entry(revision=2, status="superseded")
    )

    assert repository.list_active_experiences(
        model_id="xaj",
        basin_id="basin-a",
    ) == []


def test_active_query_filters_scope_and_keeps_global_experience(repository):
    repository.append_experience_revision(make_entry(experience_id="same"))
    repository.append_experience_revision(
        make_entry(
            experience_id="other-model",
            model_ids=("gr4j",),
        )
    )
    repository.append_experience_revision(
        make_entry(
            experience_id="global",
            model_ids=(),
            basin_ids=(),
            confidence=0.6,
        )
    )

    entries = repository.list_active_experiences(
        model_id="xaj",
        basin_id="basin-a",
    )
    assert [entry.experience_id for entry in entries] == ["global", "same"]


def test_current_promoted_skill_version_uses_latest_promoted(repository):
    assert repository.get_current_experience_skill_version() is None

    repository.create_experience_skill_version(
        version=1,
        parent_version=None,
        status="promoted",
        skill_hash="hash-v1",
        manifest={"added": ["EXP-1"]},
    )
    repository.create_experience_skill_version(
        version=2,
        parent_version=1,
        status="candidate",
        skill_hash="hash-v2",
        manifest={"added": ["EXP-2"]},
    )
    assert repository.get_current_experience_skill_version().version == 1

    repository.set_experience_skill_version_status(
        2,
        "promoted",
        regression={"passed": True},
    )
    current = repository.get_current_experience_skill_version()
    assert current.version == 2
    assert current.regression_json == {"passed": True}

    with pytest.raises(ValueError, match="invalid experience skill version transition"):
        repository.set_experience_skill_version_status(2, "candidate")


def test_evolution_event_keeps_provenance(repository):
    evidence_ref = ExperienceEvidenceRef(
        task_id="task-1",
        experiment_id="experiment-1",
        evidence_id="evidence-1",
    )
    row = repository.append_experience_evolution_event(
        event_type="REINFORCE",
        reason="routing adjustment worked again",
        task_id="task-1",
        experience_id="EXP-XAJ-1",
        from_revision=1,
        to_revision=2,
        evidence_refs=(evidence_ref,),
    )

    assert row.evidence_refs_json[0]["evidence_id"] == "evidence-1"
    events = repository.list_experience_evolution_events()
    assert [event.event_type for event in events] == ["REINFORCE"]


def test_atomic_transition_rolls_back_all_revisions(repository):
    repository.append_experience_revision(
        make_entry(experience_id="parent", confidence=0.8)
    )
    repository.append_experience_revision(
        make_entry(experience_id="taken-child", confidence=0.6)
    )
    parent = repository.get_experience("parent")
    superseded_parent = parent.model_copy(
        update={
            "revision": 2,
            "status": "superseded",
            "source_hash": None,
        }
    )
    duplicate_child = make_entry(
        experience_id="taken-child",
        revision=1,
        confidence=0.7,
    )

    with pytest.raises(ValueError, match="does not follow"):
        repository.commit_experience_transition(
            entries=(superseded_parent, duplicate_child),
            event_type="SPLIT",
            reason="test atomic rollback",
            task_id="task-1",
            experience_id="parent",
            from_revision=1,
            to_revision=2,
        )

    latest_parent = repository.get_experience("parent")
    assert latest_parent.revision == 1
    assert latest_parent.status == "active"
    assert repository.list_experience_evolution_events() == []
