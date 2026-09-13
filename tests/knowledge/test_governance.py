from hydro_agent.knowledge.governance import (
    KnowledgeApplicability,
    KnowledgeEntry,
    KnowledgeQueryContext,
    select_knowledge_entries,
)


def _entry(**overrides):
    payload = {
        "knowledge_id": "expert.yaogu.routing",
        "revision": 1,
        "category": "expert_diagnostic_prior",
        "claim": "Routing-shape evidence suggests testing the routing group.",
        "source_id": "xaj-skill-v3-2026-09-13",
        "source_hash": "sha256:test",
        "source_locator": "skill_v3.md:L101-L137",
        "applicability": KnowledgeApplicability(
            model_ids=("xaj",),
            basin_ids=("yaogu",),
            execution_representations=("lumped",),
            timesteps=("1d",),
        ),
        "verification_status": "verified_in_scope",
        "review_status": "approved",
    }
    payload.update(overrides)
    return KnowledgeEntry.model_validate(payload)


def _context(**overrides):
    payload = {
        "model_id": "xaj",
        "basin_id": "yaogu",
        "execution_representation": "lumped",
        "timestep": "1d",
    }
    payload.update(overrides)
    return KnowledgeQueryContext.model_validate(payload)


def test_verified_approved_entry_is_available_only_inside_scope():
    entry = _entry()

    accepted = select_knowledge_entries((entry,), context=_context())
    rejected = select_knowledge_entries((entry,), context=_context(basin_id="usgs_02472000"))

    assert accepted.knowledge_refs == ("expert.yaogu.routing@1",)
    assert rejected.entries == ()
    assert "scope_mismatch:basin" in rejected.decisions[0].reasons


def test_pending_or_disputed_knowledge_never_enters_agent_context():
    pending = _entry(knowledge_id="expert.pending", review_status="pending")
    disputed = _entry(knowledge_id="expert.disputed", verification_status="disputed")

    bundle = select_knowledge_entries((pending, disputed), context=_context())

    assert bundle.entries == ()
    reasons = {decision.knowledge_id: decision.reasons for decision in bundle.decisions}
    assert "review_not_approved" in reasons["expert.pending"]
    assert "verification_disputed" in reasons["expert.disputed"]


def test_unverified_prior_requires_explicit_opt_in_and_review():
    prior = _entry(
        knowledge_id="expert.unverified-prior",
        verification_status="unverified",
        review_status="approved",
    )

    default = select_knowledge_entries((prior,), context=_context())
    opted_in = select_knowledge_entries(
        (prior,),
        context=_context(allow_unverified_expert_priors=True),
    )

    assert default.entries == ()
    assert opted_in.knowledge_refs == ("expert.unverified-prior@1",)


def test_final_test_exposure_is_blocked_from_same_campaign_planning():
    leaked = _entry(
        knowledge_id="expert.final-test-derived",
        exposure_tags=("final_test",),
    )

    bundle = select_knowledge_entries((leaked,), context=_context())

    assert bundle.entries == ()
    assert bundle.decisions[0].reasons == ("forbidden_exposure:final_test",)


def test_no_compatible_knowledge_returns_empty_instead_of_weakening_filters():
    leaf_only = _entry(
        knowledge_id="expert.leaf-only",
        applicability=KnowledgeApplicability(
            model_ids=("xaj",),
            basin_ids=("usgs_02472000",),
            execution_representations=("lumped",),
            timesteps=("1d",),
        ),
    )

    bundle = select_knowledge_entries((leaf_only,), context=_context())

    assert bundle.entries == ()
    assert bundle.knowledge_refs == ()
