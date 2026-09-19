from typing import Literal, TypeAlias

from pydantic import Field, JsonValue

from hydro_agent.execution.contracts import FrozenModel

ExperienceCategory = Literal["general", "model", "basin"]
ExperienceStatus = Literal["active", "superseded", "rejected", "inactive"]
ExperienceSkillVersionStatus = Literal["candidate", "promoted", "rejected", "superseded"]
ExperienceEvolutionEventType = Literal[
    "KEEP",
    "REINFORCE",
    "WEAKEN",
    "CREATE",
    "MERGE",
    "SPLIT",
    "SUPERSEDE",
    "REJECT",
]
ExperiencePattern: TypeAlias = dict[str, JsonValue]
ExperienceDecision: TypeAlias = dict[str, JsonValue]
HypothesisOutcomeStatus = Literal["supported", "refuted", "inconclusive"]
DirectionVerificationStatus = Literal["not_required", "supported", "refuted", "inconclusive"]


class HypothesisOutcomeCase(FrozenModel):
    """One persisted calibration-hypothesis outcome, not yet a reusable rule."""

    task_id: str
    hypothesis_id: str = Field(min_length=1)
    hypothesis_status: HypothesisOutcomeStatus
    diagnostic_signature: tuple[str, ...] = ()
    direction: str = "unknown"
    direction_verification_status: DirectionVerificationStatus = "not_required"
    evidence_refs: tuple[str, ...] = ()
    maturity: Literal["case"] = "case"


class ExperienceScope(FrozenModel):
    model_ids: tuple[str, ...] = ()
    basin_ids: tuple[str, ...] = ()


class ExperienceEvidenceRef(FrozenModel):
    task_id: str
    experiment_id: str | None = None
    evidence_id: str | None = None


class ExperienceEntry(FrozenModel):
    experience_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    category: ExperienceCategory
    scope: ExperienceScope = Field(default_factory=ExperienceScope)
    pattern: ExperiencePattern = Field(default_factory=dict)
    decision: ExperienceDecision = Field(default_factory=dict)
    supporting_evidence: tuple[ExperienceEvidenceRef, ...] = ()
    contradicting_evidence: tuple[ExperienceEvidenceRef, ...] = ()
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    status: ExperienceStatus = "active"
    source_hash: str | None = None
