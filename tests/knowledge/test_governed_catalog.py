from hydro_agent.knowledge import GovernedKnowledgeRepository
from hydro_agent.knowledge.governance import KnowledgeQueryContext


def _yaogu_context(**overrides):
    payload = {
        "model_id": "xaj",
        "basin_id": "yaogu",
        "execution_representation": "lumped",
        "timestep": "1d",
    }
    payload.update(overrides)
    return KnowledgeQueryContext.model_validate(payload)


def test_xaj_v3_source_is_atomized_without_becoming_runtime_truth():
    repository = GovernedKnowledgeRepository()

    entries = repository.entries()
    ids = {entry.knowledge_id for entry in entries}

    assert "expert.yaogu.xaj.water-balance-kc" in ids
    assert "expert.yaogu.xaj.recession-routing-dp1" in ids
    assert "constraint.xaj.kg-ki-boundary.external-v3" in ids
    assert "policy.xaj.v3-objective-weights" in ids
    assert "case.yaogu.xaj.v3-benchmarks" in ids

    # Default planning is conservative: externally supplied claims are not
    # silently activated just because they exist in the governed catalog.
    bundle = repository.query(context=_yaogu_context())
    assert bundle.entries == ()


def test_explicit_unverified_prior_opt_in_is_still_scope_limited():
    repository = GovernedKnowledgeRepository()

    bundle = repository.query(
        context=_yaogu_context(allow_unverified_expert_priors=True),
        categories=("expert_diagnostic_prior",),
    )

    assert set(bundle.knowledge_refs) == {
        "expert.yaogu.xaj.recession-routing-dp1@1",
        "expert.yaogu.xaj.water-balance-kc@1",
    }

    other_basin = repository.query(
        context=_yaogu_context(
            basin_id="usgs_02472000",
            allow_unverified_expert_priors=True,
        ),
        categories=("expert_diagnostic_prior",),
    )
    assert other_basin.entries == ()


def test_same_dataset_prior_is_blocked_even_with_explicit_opt_in():
    repository = GovernedKnowledgeRepository()

    bundle = repository.query(
        context=_yaogu_context(
            allow_unverified_expert_priors=True,
            forbidden_evidence_dataset_ids=("yaogu-academy-1989-2003",),
        ),
        categories=("expert_diagnostic_prior",),
    )

    assert bundle.entries == ()
    diagnostic_decisions = [
        decision
        for decision in bundle.decisions
        if decision.knowledge_id.startswith("expert.yaogu.xaj.")
    ]
    assert diagnostic_decisions
    assert all(
        "forbidden_evidence_dataset:yaogu-academy-1989-2003" in decision.reasons
        for decision in diagnostic_decisions
    )


def test_constraint_and_benchmark_claims_cannot_enter_agent_planning():
    repository = GovernedKnowledgeRepository()

    bundle = repository.query(
        context=_yaogu_context(allow_unverified_expert_priors=True),
    )
    reasons = {decision.knowledge_id: decision.reasons for decision in bundle.decisions}

    assert (
        "authority_not_planning:validator_evidence"
        in reasons["constraint.xaj.kg-ki-boundary.external-v3"]
    )
    assert "verification_disputed" in reasons["constraint.xaj.kg-ki-boundary.external-v3"]
    assert "authority_not_planning:provenance_only" in reasons["case.yaogu.xaj.v3-benchmarks"]
    assert "authority_not_planning:runtime_prohibited" in reasons["policy.xaj.v3-objective-weights"]
