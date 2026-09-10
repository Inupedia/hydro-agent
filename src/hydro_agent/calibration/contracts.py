from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel, Identifier


class CalibrationPhase(StrEnum):
    """Hydrologist workflow phases, ordered from data checks to final holdout."""

    DATA_REGIME = "P0_DATA_REGIME"
    PARAMETER_PRIOR = "P1_PARAMETER_PRIOR"
    WATER_BALANCE = "P2_WATER_BALANCE"
    SOURCE_RECESSION = "P3_SOURCE_RECESSION"
    ROUTING_EVENT = "P4_ROUTING_EVENT"
    JOINT_REFINE = "P5_JOINT_REFINE"
    DEVELOPMENT_VALIDATION = "P6_DEVELOPMENT_VALIDATION"
    FINAL_HOLDOUT = "P7_FINAL_HOLDOUT"


class PhaseGateStatus(StrEnum):
    CONTINUE = "CONTINUE"
    PHASE_PASS = "PHASE_PASS"
    ROLLBACK = "ROLLBACK"
    PLATEAU_PASS = "PLATEAU_PASS"
    PLATEAU_FAIL = "PLATEAU_FAIL"
    DATA_LIMIT = "DATA_LIMIT"
    FORCING_LIMIT = "FORCING_LIMIT"
    STRUCTURAL_LIMIT = "STRUCTURAL_LIMIT"
    HARD_BUDGET = "HARD_BUDGET"


class HydrologicGatePolicy(FrozenModel):
    """Phase-specific hydrologic acceptance thresholds.

    Values are intentionally explicit and configurable. They are research defaults,
    not universal constants for every basin or forecast time step.
    """

    water_balance_rel_error: float = Field(default=0.10, ge=0.0)
    annual_water_balance_mae: float = Field(default=0.15, ge=0.0)
    seasonal_water_balance_mae: float = Field(default=0.20, ge=0.0)
    recession_relative_error: float = Field(default=0.30, ge=0.0)
    flood_peak_rel_error: float = Field(default=0.30, ge=0.0)
    flood_volume_rel_error: float = Field(default=0.20, ge=0.0)
    peak_timing_steps: float = Field(default=1.0, ge=0.0)
    joint_nse_floor: float = 0.50
    joint_kge_floor: float = 0.30
    # Guardrails: a candidate may improve a phase objective but must not destroy
    # already-solved upstream hydrologic behaviour.
    max_water_balance_regression: float = Field(default=0.03, ge=0.0)
    max_event_error_regression: float = Field(default=0.10, ge=0.0)


class SearchConvergencePolicy(FrozenModel):
    window: int = Field(default=4, ge=3, le=10)
    min_points: int = Field(default=4, ge=3, le=10)
    gain_tolerance: float = Field(default=0.015, ge=0.0)
    slope_tolerance: float = Field(default=0.006, ge=0.0)
    span_tolerance: float = Field(default=0.02, ge=0.0)


class SearchProgressPoint(FrozenModel):
    experiment_id: Identifier
    phase: CalibrationPhase
    value: float
    higher_is_better: bool = True


class SearchConvergenceDecision(FrozenModel):
    plateau: bool
    duplicate: bool = False
    unique_points: int = 0
    best_value: float | None = None
    gain: float | None = None
    slope: float | None = None
    span: float | None = None
    reason: str = ""


class PhaseGateDecision(FrozenModel):
    phase: CalibrationPhase
    status: PhaseGateStatus
    base_scheme_id: Identifier
    candidate_scheme_id: Identifier
    experiment_id: Identifier
    adopt_candidate: bool = False
    advance_phase: bool = False
    stop_search: bool = False
    progress_metric: str
    progress_value: float
    higher_is_better: bool = True
    reasons: tuple[str, ...] = ()
    metrics: dict[str, float] = Field(default_factory=dict)


PhaseObjective = Literal[
    "water_balance",
    "recession",
    "routing_event",
    "joint_skill",
    "development_validation",
]
