from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel, Identifier

GateStatus = Literal[
    "ACCEPT",
    "CONTINUE",
    "CONVERGED",
    "ROLLBACK",
    "STRUCTURAL_LIMIT",
]
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
    # Improvement large enough to be treated as a meaningful new experiment result.
    min_primary_delta: float = 0.01
    max_single_lead_drop: float = Field(default=0.02, ge=0)
    max_high_flow_mae_relative_increase: float = Field(default=0.05, ge=0)
    # Absolute skill floor: even a large relative gain cannot ACCEPT below this.
    min_candidate_primary: float = 0.0
    # Legacy NSE/DC floor (GB/T 表1 丙级 DC≥0.50). Prefer min_scheme_grade + GBT report.
    accept_primary_floor: float = 0.5
    # GB/T 22482 §6.5.6 minimum scheme grade for final ACCEPT.
    min_scheme_grade: SchemeGrade = "丙"
    require_gbt_grade: bool = True

    # Dynamic convergence control. max rounds/cycles are safety ceilings only; these
    # fields decide whether another calibration experiment is scientifically useful.
    convergence_window: int = Field(default=4, ge=3, le=10)
    convergence_min_points: int = Field(default=3, ge=3, le=10)
    convergence_gain_tolerance: float = Field(default=0.015, ge=0)
    convergence_slope_tolerance: float = Field(default=0.006, ge=0)
    convergence_oscillation_tolerance: float = Field(default=0.02, ge=0)
    structural_warning_patience: int = Field(default=2, ge=1, le=10)


class GateDecision(FrozenModel):
    status: GateStatus
    base_scheme_id: Identifier
    candidate_scheme_id: Identifier
    reasons: tuple[str, ...]
    primary_delta: float
    scheme_grade: SchemeGrade | None = None
    gbt_summary: str | None = None
    # Side-effect guidance for A09_RESOLVE.
    adopt_candidate: bool = False
    should_stop: bool = False
    # Convergence diagnostics over best-so-far validation NSE/DC.
    best_primary: float | None = None
    convergence_slope: float | None = None
    convergence_gain: float | None = None
    convergence_span: float | None = None
    history_points: int = 0
