import pytest
from pydantic import ValidationError

from hydro_agent.experience.contracts import ExperienceEntry, ExperienceEvidenceRef, ExperienceScope
from hydro_agent.experience.diff import ExperienceDiff, is_structural_change


def entry(experience_id: str):
    return ExperienceEntry(
        experience_id=experience_id,
        revision=1,
        category="model",
        scope=ExperienceScope(model_ids=("xaj",), basin_ids=("basin-a",)),
        pattern={"peak_bias": "negative"},
        decision={"prefer_param_groups": ["routing"]},
        supporting_evidence=(),
        contradicting_evidence=(),
        confidence=0.65,
        status="active",
    )


def evidence():
    return ExperienceEvidenceRef(
        task_id="task-1",
        experiment_id="exp-1",
        evidence_id="evidence-1",
    )


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
