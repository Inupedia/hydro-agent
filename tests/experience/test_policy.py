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



def _match(
    experience_id,
    *,
    confidence=0.9,
    transfer_weight=1.0,
    scope_rank=4,
    decision=None,
    supporting_count=5,
    contradicting_count=0,
):
    from hydro_agent.experience.retrieval import ExperienceMatch

    return ExperienceMatch(
        experience_id=experience_id,
        revision=1,
        category="model",
        relevance=1.0,
        transfer_weight=transfer_weight,
        confidence=confidence,
        scope_rank=scope_rank,
        decision=decision or {"prefer_param_groups": ["routing"]},
        pattern={"peak_bias": "negative"},
        supporting_count=supporting_count,
        contradicting_count=contradicting_count,
    )


def test_high_confidence_same_basin_exploits_experience():
    from hydro_agent.experience.policy import ExperiencePolicy

    policy = ExperiencePolicy()
    advice = policy.advise_plan(
        matches=(_match("EXP-ROUTING"),),
        diagnosis={"recommended_param_groups": ["routing", "runoff"]},
        available_param_groups=("evap", "runoff", "routing"),
        available_strategies=("xaj-bounded-v1",),
    )

    assert advice.mode == "exploitation"
    assert advice.exploration_level > 0
    assert advice.param_groups[0] == "routing"
    assert "EXP-ROUTING" in advice.experience_refs


def test_low_confidence_transfer_experience_increases_exploration():
    from hydro_agent.experience.policy import ExperiencePolicy

    mode, level = ExperiencePolicy().choose_mode(
        (
            _match(
                "EXP-TRANSFER",
                confidence=0.3,
                transfer_weight=0.78,
                scope_rank=3,
            ),
        )
    )

    assert mode == "exploration"
    assert level >= 0.45


def test_historical_failure_penalizes_repeated_direction():
    from hydro_agent.experience.policy import ExperiencePolicy

    scores = ExperiencePolicy().score_param_groups(
        matches=(
            _match(
                "EXP-FAIL",
                decision={
                    "prefer_param_groups": ["routing"],
                    "failed_param_groups": ["evap"],
                },
            ),
        ),
        diagnosis={"recommended_param_groups": ["routing", "evap"]},
        available_param_groups=("evap", "routing"),
    )

    by_id = {item.candidate_id: item for item in scores}
    assert by_id["evap"].failure_penalty > 0
    assert by_id["routing"].total > by_id["evap"].total


def test_policy_ranking_is_stable_for_same_inputs():
    from hydro_agent.experience.policy import ExperiencePolicy

    kwargs = dict(
        matches=(_match("EXP-A"),),
        diagnosis={"recommended_param_groups": ["routing", "runoff"]},
        available_param_groups=("runoff", "routing", "evap"),
    )
    policy = ExperiencePolicy()

    assert policy.score_param_groups(**kwargs) == policy.score_param_groups(**kwargs)
