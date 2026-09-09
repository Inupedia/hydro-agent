from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel, Identifier

GateStatus = Literal["ACCEPT", "KEEP", "ROLLBACK"]


class CalibrationStrategy(FrozenModel):
    strategy_id: str = Field(min_length=1)
    max_candidates: int = Field(ge=1, le=500)
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
    min_primary_delta: float
    max_single_lead_drop: float = Field(ge=0)
    max_high_flow_mae_relative_increase: float = Field(ge=0)
    # Absolute skill floor: even a large relative gain cannot ACCEPT below this.
    min_candidate_primary: float = 0.0


class GateDecision(FrozenModel):
    status: GateStatus
    base_scheme_id: Identifier
    candidate_scheme_id: Identifier
    reasons: tuple[str, ...]
    primary_delta: float
