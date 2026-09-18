from typing import Literal

from pydantic import Field, model_validator

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.experience.contracts import ExperienceEntry, ExperienceEvidenceRef

ExperienceDiffOperation = Literal[
    "KEEP",
    "REINFORCE",
    "WEAKEN",
    "CREATE",
    "MERGE",
    "SPLIT",
    "SUPERSEDE",
    "REJECT",
]

_STRUCTURAL_OPERATIONS = {"CREATE", "MERGE", "SPLIT", "SUPERSEDE"}


class ExperienceDiff(FrozenModel):
    operation: ExperienceDiffOperation
    experience_id: str | None = None
    source_ids: tuple[str, ...] = ()
    proposals: tuple[ExperienceEntry, ...] = ()
    evidence_refs: tuple[ExperienceEvidenceRef, ...] = ()
    reason: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def validate_operation_shape(self):
        op = self.operation

        if op in {"KEEP", "REINFORCE", "WEAKEN", "SPLIT", "SUPERSEDE", "REJECT"}:
            if not self.experience_id:
                raise ValueError(f"{op} requires experience_id")

        if op in {"REINFORCE", "WEAKEN"} and not self.evidence_refs:
            raise ValueError(f"{op} requires evidence_refs")

        if op == "CREATE":
            if len(self.proposals) != 1:
                raise ValueError("CREATE requires exactly one proposal")
            if self.source_ids or self.experience_id:
                raise ValueError("CREATE cannot declare a source experience")

        if op == "MERGE":
            if len(self.source_ids) < 2:
                raise ValueError("MERGE requires at least two source_ids")
            if len(set(self.source_ids)) != len(self.source_ids):
                raise ValueError("MERGE source_ids must be unique")
            if len(self.proposals) != 1:
                raise ValueError("MERGE requires exactly one proposal")
            if self.experience_id:
                raise ValueError("MERGE uses source_ids instead of experience_id")

        if op == "SPLIT" and len(self.proposals) < 2:
            raise ValueError("SPLIT requires at least two proposals")

        if op == "SUPERSEDE" and len(self.proposals) != 1:
            raise ValueError("SUPERSEDE requires exactly one replacement proposal")

        if op in {"KEEP", "REINFORCE", "WEAKEN", "REJECT"} and self.proposals:
            raise ValueError(f"{op} cannot include proposals")

        if op not in {"MERGE"} and self.source_ids:
            raise ValueError(f"{op} cannot include source_ids")

        if self.proposals:
            proposal_ids = [proposal.experience_id for proposal in self.proposals]
            if len(set(proposal_ids)) != len(proposal_ids):
                raise ValueError("proposal experience_ids must be unique")
            if any(proposal.revision != 1 for proposal in self.proposals):
                raise ValueError("new experience proposals must start at revision 1")
            if any(proposal.status != "active" for proposal in self.proposals):
                raise ValueError("new experience proposals must start active")

        return self


def is_structural_change(diff: ExperienceDiff) -> bool:
    return diff.operation in _STRUCTURAL_OPERATIONS
