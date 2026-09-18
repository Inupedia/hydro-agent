from hydro_agent.experience.contracts import ExperienceEntry, ExperienceScope
from hydro_agent.experience.retrieval import ExperienceRetriever
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository


def _entry(
    experience_id,
    *,
    category="model",
    model_ids=("xaj",),
    basin_ids=(),
    pattern=None,
    confidence=0.8,
    revision=1,
):
    return ExperienceEntry(
        experience_id=experience_id,
        revision=revision,
        category=category,
        scope=ExperienceScope(model_ids=model_ids, basin_ids=basin_ids),
        pattern=pattern or {},
        decision={"prefer_param_groups": ["routing"]},
        supporting_evidence=(),
        contradicting_evidence=(),
        confidence=confidence,
        status="active",
    )


def _repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/retrieval.db")
    db.create_schema()
    return HydroRepository(db)


def test_retrieval_scope_order_is_deterministic(tmp_path):
    repository = _repository(tmp_path)
    repository.append_experience_revision(
        _entry("EXP-SAME", basin_ids=("basin-a",), pattern={"peak_bias": "negative"})
    )
    repository.append_experience_revision(
        _entry("EXP-TRANSFER", basin_ids=("basin-b",), pattern={"peak_bias": "negative"})
    )
    repository.append_experience_revision(
        _entry("EXP-MODEL", pattern={"peak_bias": "negative"})
    )
    repository.append_experience_revision(
        _entry(
            "EXP-GENERAL",
            category="general",
            model_ids=(),
            pattern={"peak_bias": "negative"},
        )
    )

    matches = ExperienceRetriever(repository).retrieve(
        model_id="xaj",
        basin_id="basin-a",
        diagnosis={"peak_bias": "negative"},
    )

    assert [item.experience_id for item in matches] == [
        "EXP-SAME",
        "EXP-TRANSFER",
        "EXP-MODEL",
        "EXP-GENERAL",
    ]
    assert [item.scope_rank for item in matches] == [4, 3, 2, 1]
    assert matches[0].transfer_weight == 1.0
    assert matches[-1].transfer_weight == 0.5


def test_unknown_pattern_keys_do_not_guess_a_match(tmp_path):
    repository = _repository(tmp_path)
    repository.append_experience_revision(
        _entry("EXP-UNKNOWN", pattern={"unknown_signal": "high"})
    )
    repository.append_experience_revision(
        _entry("EXP-GENERAL", pattern={})
    )

    matches = ExperienceRetriever(repository).retrieve(
        model_id="xaj",
        basin_id="basin-a",
        diagnosis={"metrics": {"nse": 0.4}},
    )

    assert [item.experience_id for item in matches] == ["EXP-GENERAL"]


def test_retrieval_uses_frozen_revision_map_instead_of_latest_state(tmp_path):
    repository = _repository(tmp_path)
    repository.append_experience_revision(
        _entry(
            "EXP-FROZEN",
            revision=1,
            pattern={"peak_bias": "negative"},
            confidence=0.6,
        )
    )
    repository.append_experience_revision(
        _entry(
            "EXP-FROZEN",
            revision=2,
            pattern={"peak_bias": "negative"},
            confidence=0.95,
        )
    )

    frozen = ExperienceRetriever(repository).retrieve(
        model_id="xaj",
        basin_id="basin-a",
        diagnosis={"peak_bias": "negative"},
        revision_map={"EXP-FROZEN": 1},
    )

    assert len(frozen) == 1
    assert frozen[0].revision == 1
    assert frozen[0].confidence == 0.6
