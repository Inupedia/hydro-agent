from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel, Identifier

GateStatus = Literal["ACCEPT", "KEEP", "ROLLBACK"]
AdoptionStatus = Literal["ADOPT", "KEEP", "REJECT"]
QualificationStatus = Literal["QUALIFIED", "UNQUALIFIED", "NOT_EVALUATED"]
SchemeGrade = Literal["甲", "乙", "丙", "不合格"]


class CalibrationStrategy(FrozenModel):
    """Scientific search strategy; it does not contain raw parameter values."""

    strategy_id: str = Field(min_length=1)
    # Legacy field name retained for API compatibility. Semantically this is a
    # hard model-evaluation budget for the selected numerical optimizer. The old
    # 500-evaluation ceiling was too small for research-grade calibration, so the
    # contract now permits preregistered budgets up to 10k model evaluations.
    max_candidates: int = Field(ge=1, le=10_000)
    random_seed: int
    objective: Literal["nse", "peak", "composite"] = "nse"
    local_scale: float | None = Field(default=None, ge=0.0, le=1.0)
    param_groups: tuple[Literal["evap", "runoff", "routing"], ...] = (
        "evap",
        "runoff",
        "routing",
    )
    optimizer: Literal["dds", "sce-ua", "random-search", "manual"] = "sce-ua"

    @property
    def evaluation_budget(self) -> int:
        return int(self.max_candidates)


class LeadMetrics(FrozenModel):
    lead: Literal[1, 2, 3]
    nse: float
    mae: float
    bias: float
    high_flow_mae: float


class EvaluationBundle(FrozenModel):
    scheme_id: Identifier
    leads: tuple[LeadMetrics, LeadMetrics, LeadMetrics]
    primary_score: float


class GatePolicy(FrozenModel):
    # Adoption threshold: a candidate must make a meaningful improvement before
    # it replaces the current working scheme. This is intentionally independent
    # from whether the candidate already meets the final qualification standard.
    min_primary_delta: float
    max_single_lead_drop: float = Field(ge=0)
    max_high_flow_mae_relative_increase: float = Field(ge=0)
    # Qualification floor. A candidate may still be ADOPTed below this value so
    # later experiments can accumulate progress without calling the run complete.
    min_candidate_primary: float = 0.0
    # Legacy NSE/DC floor. Runtime standard thresholds come from KnowledgeRepository.
    accept_primary_floor: float = 0.5
    # GB/T 22482 §6.5.6 minimum scheme grade for qualification.
    min_scheme_grade: SchemeGrade = "丙"
    # When True, qualification is determined by the GB/T scheme grade rather
    # than a numeric NSE fallback. Adoption remains based on independent evidence.
    require_gbt_grade: bool = True


class GateDecision(FrozenModel):
    # ``status`` remains for workflow compatibility and now represents the
    # adoption outcome: ACCEPT=adopt candidate, KEEP=keep working scheme,
    # ROLLBACK=reject a harmful candidate.
    status: GateStatus
    base_scheme_id: Identifier
    candidate_scheme_id: Identifier
    reasons: tuple[str, ...]
    primary_delta: float
    adoption_status: AdoptionStatus = "KEEP"
    qualification_status: QualificationStatus = "NOT_EVALUATED"
    qualification_reasons: tuple[str, ...] = ()
    scheme_grade: SchemeGrade | None = None
    gbt_summary: str | None = None
