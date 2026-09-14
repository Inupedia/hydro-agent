"""Govern external and learned knowledge before it can influence Agent planning.

The calibration Agent may use expert material as evidence for a falsifiable
experiment, but text files are never execution authority. Hard parameter
constraints, scoring windows, objective profiles, budgets and release rules
remain owned by versioned protocol/model validators.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel

KnowledgeCategory = Literal[
    "model_fact",
    "model_constraint_evidence",
    "expert_diagnostic_prior",
    "experiment_case",
    "calibration_case",
    "policy_suggestion",
    "quarantine",
]
KnowledgeAuthority = Literal[
    "advisory_only",
    "validator_evidence",
    "provenance_only",
    "runtime_prohibited",
]
VerificationStatus = Literal[
    "unverified",
    "verified_in_scope",
    "disputed",
    "rejected",
    "superseded",
]
ReviewStatus = Literal["pending", "approved"]
ExposureTag = Literal["calibration", "development", "final_test"]


class KnowledgeApplicability(FrozenModel):
    """Compatibility keys that must match before an entry is considered."""

    model_ids: tuple[str, ...] = ()
    kernel_versions: tuple[str, ...] = ()
    adapter_versions: tuple[str, ...] = ()
    basin_ids: tuple[str, ...] = ()
    execution_representations: tuple[str, ...] = ()
    timesteps: tuple[str, ...] = ()
    evaporation_semantics: tuple[str, ...] = ()


class KnowledgeEntry(FrozenModel):
    """Atomic, source-addressable knowledge claim.

    ``review_status`` answers whether a human approved the entry for its stated
    role. ``verification_status`` answers whether the claim itself has been
    reproduced/verified. Those are deliberately independent.

    ``authority`` is deliberately explicit. Only ``advisory_only`` entries may
    enter Agent planning; constraint evidence, benchmark provenance and policy
    text can be stored and audited without acquiring runtime authority.
    """

    knowledge_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    category: KnowledgeCategory
    authority: KnowledgeAuthority = "advisory_only"
    claim: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_hash: str = Field(min_length=1)
    source_locator: str = Field(min_length=1)
    applicability: KnowledgeApplicability = Field(default_factory=KnowledgeApplicability)
    verification_status: VerificationStatus = "unverified"
    review_status: ReviewStatus = "pending"
    exposure_tags: tuple[ExposureTag, ...] = ()
    # IDs of datasets whose observations or derived metrics were used to form
    # this claim. A campaign may forbid same-dataset priors even when the claim
    # does not literally carry a final_test tag, preventing indirect leakage.
    evidence_dataset_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()


class KnowledgeQueryContext(FrozenModel):
    """Planning-time scope and leakage policy for knowledge retrieval."""

    model_id: str = Field(min_length=1)
    kernel_version: str | None = None
    adapter_version: str | None = None
    basin_id: str | None = None
    execution_representation: str | None = None
    timestep: str | None = None
    evaporation_semantic: str | None = None
    allow_unverified_expert_priors: bool = False
    forbidden_exposure_tags: tuple[ExposureTag, ...] = ("final_test",)
    forbidden_evidence_dataset_ids: tuple[str, ...] = ()


class KnowledgeFilterDecision(FrozenModel):
    knowledge_id: str
    revision: int
    accepted: bool
    reasons: tuple[str, ...] = ()


class KnowledgeEvidenceBundle(FrozenModel):
    """Auditable retrieval result; empty means no compatible knowledge."""

    entries: tuple[KnowledgeEntry, ...] = ()
    decisions: tuple[KnowledgeFilterDecision, ...] = ()

    @property
    def knowledge_refs(self) -> tuple[str, ...]:
        return tuple(f"{entry.knowledge_id}@{entry.revision}" for entry in self.entries)


def _scope_matches(value: str | None, allowed: tuple[str, ...]) -> bool:
    if not allowed:
        return True
    if value is None:
        return False
    return value in allowed


def _rejection_reasons(entry: KnowledgeEntry, context: KnowledgeQueryContext) -> tuple[str, ...]:
    reasons: list[str] = []
    if entry.category == "quarantine":
        reasons.append("category_quarantined")
    if entry.authority != "advisory_only":
        reasons.append(f"authority_not_planning:{entry.authority}")
    if entry.review_status != "approved":
        reasons.append("review_not_approved")
    if entry.verification_status in {"disputed", "rejected", "superseded"}:
        reasons.append(f"verification_{entry.verification_status}")
    elif entry.verification_status == "unverified":
        allowed_prior = (
            context.allow_unverified_expert_priors
            and entry.category == "expert_diagnostic_prior"
        )
        if not allowed_prior:
            reasons.append("unverified_not_allowed")

    forbidden = set(context.forbidden_exposure_tags)
    leaked = forbidden.intersection(entry.exposure_tags)
    if leaked:
        reasons.append("forbidden_exposure:" + ",".join(sorted(leaked)))

    forbidden_datasets = set(context.forbidden_evidence_dataset_ids)
    leaked_datasets = forbidden_datasets.intersection(entry.evidence_dataset_ids)
    if leaked_datasets:
        reasons.append("forbidden_evidence_dataset:" + ",".join(sorted(leaked_datasets)))

    scope = entry.applicability
    checks = (
        (context.model_id, scope.model_ids, "model"),
        (context.kernel_version, scope.kernel_versions, "kernel"),
        (context.adapter_version, scope.adapter_versions, "adapter"),
        (context.basin_id, scope.basin_ids, "basin"),
        (
            context.execution_representation,
            scope.execution_representations,
            "execution_representation",
        ),
        (context.timestep, scope.timesteps, "timestep"),
        (context.evaporation_semantic, scope.evaporation_semantics, "evaporation_semantic"),
    )
    for value, allowed, label in checks:
        if not _scope_matches(value, allowed):
            reasons.append(f"scope_mismatch:{label}")
    return tuple(reasons)


def select_knowledge_entries(
    entries: Iterable[KnowledgeEntry],
    *,
    context: KnowledgeQueryContext,
    categories: Iterable[KnowledgeCategory] | None = None,
) -> KnowledgeEvidenceBundle:
    """Strictly filter before any semantic ranking or Agent use.

    The function intentionally has no "best effort" fallback. If every entry is
    incompatible, callers receive an empty bundle and must use the registered
    baseline rather than weakening trust/scope/final-test filters to fill context.
    """

    category_filter = set(categories or ())
    accepted: list[KnowledgeEntry] = []
    decisions: list[KnowledgeFilterDecision] = []
    for entry in entries:
        reasons = list(_rejection_reasons(entry, context))
        if category_filter and entry.category not in category_filter:
            reasons.append("category_not_requested")
        decision = KnowledgeFilterDecision(
            knowledge_id=entry.knowledge_id,
            revision=entry.revision,
            accepted=not reasons,
            reasons=tuple(reasons),
        )
        decisions.append(decision)
        if decision.accepted:
            accepted.append(entry)

    accepted.sort(key=lambda item: (item.knowledge_id, item.revision))
    decisions.sort(key=lambda item: (item.knowledge_id, item.revision))
    return KnowledgeEvidenceBundle(entries=tuple(accepted), decisions=tuple(decisions))
