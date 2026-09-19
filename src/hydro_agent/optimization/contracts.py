from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel, Identifier

GateStatus = Literal["ACCEPT", "KEEP", "ROLLBACK"]
AdoptionStatus = Literal["ADOPT", "KEEP", "REJECT"]
QualificationStatus = Literal["QUALIFIED", "UNQUALIFIED", "NOT_EVALUATED"]
SchemeGrade = Literal["甲", "乙", "丙", "不合格"]
SensitivityMethod = Literal["none", "morris"]
CalibrationObjective = Literal["nse", "kge", "peak", "composite"]


class CalibrationStrategy(FrozenModel):
    """Scientific search strategy; it does not contain raw parameter values.

    ``composite`` remains accepted only as a compatibility alias for historical
    serialized strategies. New strategies should use the explicit ``kge`` name.
    """

    strategy_id: str = Field(min_length=1)
    # Legacy field name retained for API compatibility. Semantically this is a
    # hard model-evaluation budget for the selected numerical optimizer plus any
    # preregistered sensitivity-screening stage. The old 500-evaluation ceiling
    # was too small for research-grade calibration, so the contract permits up
    # to 10k model evaluations.
    max_candidates: int = Field(ge=1, le=10_000)
    random_seed: int
    objective: CalibrationObjective = "nse"
    local_scale: float | None = Field(default=None, ge=0.0, le=1.0)
    # Model-scoped group ids (XAJ: evap/runoff/routing; GR4J: production/...).
    param_groups: tuple[str, ...] = (
        "evap",
        "runoff",
        "routing",
    )
    optimizer: Literal["dds", "sce-ua", "random-search", "manual"] = "sce-ua"

    sensitivity_method: SensitivityMethod = "none"
    sensitivity_trajectories: int = Field(default=0, ge=0, le=50)
    sensitivity_levels: int = Field(default=6, ge=4, le=20)
    sensitivity_min_relative_mu_star: float = Field(default=0.10, ge=0.0, le=1.0)
    sensitivity_min_effects: int = Field(default=2, ge=1, le=50)
    active_parameter_limit: int | None = Field(default=None, ge=1, le=15)
    min_active_parameters: int = Field(default=2, ge=1, le=15)

    @property
    def evaluation_budget(self) -> int:
        return int(self.max_candidates)

    @property
    def canonical_objective(self) -> Literal["nse", "kge", "peak"]:
        return "kge" if self.objective == "composite" else self.objective


class LeadMetrics(FrozenModel):
    lead: Literal[1, 2, 3]
    nse: float
    mae: float
    bias: float
    high_flow_mae: float
    sample_count: int = Field(default=0, ge=0)


class EvaluationBundle(FrozenModel):
    """Independent development evidence available for one or more forecast leads.

    Short smoke windows may not contain enough in-window target dates to score all
    three leads without leaking into final_test. Only leads with at least two legal
    target observations are materialized; formal research windows normally retain
    all three. ``primary_score`` is the mean NSE over exactly those evaluated leads.
    """

    scheme_id: Identifier
    leads: tuple[LeadMetrics, ...]
    primary_score: float


class GatePolicy(FrozenModel):
    min_primary_delta: float
    max_single_lead_drop: float = Field(ge=0)
    max_high_flow_mae_relative_increase: float = Field(ge=0)
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
    adoption_status: AdoptionStatus = "KEEP"
    qualification_status: QualificationStatus = "NOT_EVALUATED"
    qualification_reasons: tuple[str, ...] = ()
    scheme_grade: SchemeGrade | None = None
    gbt_summary: str | None = None


class ParameterDirectionalEffect(FrozenModel):
    parameter: str
    negative_delta: float | None = None
    positive_delta: float | None = None
    expected_signature_change: dict[str, float] = Field(default_factory=dict)


class DirectionalProbeResult(FrozenModel):
    requested_direction: str
    status: Literal["supported", "refuted", "inconclusive"]
    parameter_effects: tuple[ParameterDirectionalEffect, ...]
    supporting_parameters: tuple[str, ...] = ()
    contradictory_parameters: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
