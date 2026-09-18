import pytest
from pydantic import ValidationError

from hydro_agent.experience.contracts import ExperienceEntry, ExperienceScope


def make_entry(**overrides):
    values = {
        "experience_id": "EXP-XAJ-0001",
        "revision": 1,
        "category": "model",
        "scope": ExperienceScope(model_ids=("xaj",), basin_ids=("basin-a",)),
        "pattern": {"peak_bias": "negative"},
        "decision": {"prefer_param_groups": ["routing"]},
        "supporting_evidence": (),
        "contradicting_evidence": (),
        "confidence": 0.7,
        "status": "active",
    }
    values.update(overrides)
    return ExperienceEntry(**values)


def test_experience_entry_has_no_user_scope():
    entry = make_entry()
    assert entry.scope.model_ids == ("xaj",)
    assert not hasattr(entry.scope, "user_ids")


def test_experience_entry_is_frozen_and_validated():
    with pytest.raises(ValidationError):
        make_entry(confidence=1.1)
    with pytest.raises(ValidationError):
        make_entry(revision=0)
    with pytest.raises(ValidationError):
        ExperienceScope(user_ids=("user-1",))

    entry = make_entry()
    with pytest.raises(ValidationError):
        entry.confidence = 0.8
