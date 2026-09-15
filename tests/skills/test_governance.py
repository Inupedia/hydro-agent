from hydro_agent.skills.governance import (
    KnowledgeApplicability,
    KnowledgeEntry,
    KnowledgeQueryContext,
    select_knowledge_entries,
)


def test_skill_claim_filter_has_no_scope_fallback():
    entry = KnowledgeEntry(
        knowledge_id="expert.example",
        revision=1,
        category="expert_diagnostic_prior",
        authority="advisory_only",
        claim="example",
        source_id="source",
        source_hash="sha256:x",
        source_locator="asset.json",
        applicability=KnowledgeApplicability(model_ids=("xaj",), basin_ids=("yaogu",)),
        verification_status="verified_in_scope",
        review_status="approved",
    )
    bundle = select_knowledge_entries(
        (entry,), context=KnowledgeQueryContext(model_id="xaj", basin_id="other")
    )
    assert bundle.entries == ()
    assert "scope_mismatch:basin" in bundle.decisions[0].reasons
