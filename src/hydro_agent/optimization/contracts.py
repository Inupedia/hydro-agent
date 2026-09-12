from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel, Identifier

GateStatus = Literal["ACCEPT", "KEEP", "ROLLBACK"]
SchemeGrade = Literal["甲", "乙", "丙", "不合格"]


class CalibrationStrategy(FrozenModel):
    """Scientific search strategy; it does not contain raw parameter values."""

    strategy_id: str = Field(min_length=1)
    # Legacy field name retained for API compatibility. Semantically this is a
    # hard model-evaluation budget for the selected numerical optimizer.
    max_candidates: int = Field(ge=1, le=500)
    random_seed: int
    objective: Literal["nse", "peak", "composite"] = "nse"
    local_scale: float | None = Field(default=None, ge=0.0, le=1.0)
    param_groups: tuple[Literal["evap", "runoff", "routing"], ...] = (
        "evap",
        "runoff",
        "routing",
    )
    optimizer: Literal["sce-ua", "random-search", "manual"] = "sce-ua"

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
    min_primary_delta: float
    max_single_lead_drop: float = Field(ge=0)
    max_high_flow_mae_relative_increase: float = Field(ge=0)
    # Absolute skill floor: even a large relative gain cannot ACCEPT below this.
    min_candidate_primary: float = 0.0
    # Legacy NSE/DC floor. Runtime standard thresholds come from KnowledgeRepository.
    accept_primary_floor: float = 0.5
    # GB/T 22482 §6.5.6 minimum scheme grade for ACCEPT.
    min_scheme_grade: SchemeGrade = "丙"
    # When True, ACCEPT only via GB/T scheme grade (no ΔNSE shortcut).
    require_gbt_grade: bool = True


class GateDecision(FrozenModel):
    status: GateStatus
    base_scheme_id: Identifier
    candidate_scheme_id: Identifier
    reasons: tuple[str, ...]
    primary_delta: float
    scheme_grade: SchemeGrade | None = None
    gbt_summary: str | None = None
