from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel, Identifier

GateStatus = Literal["ACCEPT", "KEEP", "ROLLBACK"]
SchemeGrade = Literal["甲", "乙", "丙", "不合格"]


class CalibrationStrategy(FrozenModel):
    strategy_id: str = Field(min_length=1)
    max_candidates: int = Field(ge=1, le=2000)
    random_seed: int
    objective: Literal["nse", "peak", "composite"] = "nse"
    local_scale: float | None = Field(default=None, ge=0.0, le=1.0)
    param_groups: tuple[Literal["evap", "runoff", "routing"], ...] = (
        "evap",
        "runoff",
        "routing",
    )


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
    """Generic forecast-candidate gate used outside the staged calibration protocol."""

    min_primary_delta: float = 0.01
    max_single_lead_drop: float = Field(default=0.02, ge=0)
    max_high_flow_mae_relative_increase: float = Field(default=0.05, ge=0)
    min_candidate_primary: float = 0.0
    accept_primary_floor: float = 0.5
    min_scheme_grade: SchemeGrade = "丙"
    require_gbt_grade: bool = True


class GateDecision(FrozenModel):
    status: GateStatus
    base_scheme_id: Identifier
    candidate_scheme_id: Identifier
    reasons: tuple[str, ...]
    primary_delta: float
    scheme_grade: SchemeGrade | None = None
    gbt_summary: str | None = None
