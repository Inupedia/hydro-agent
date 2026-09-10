from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel, Identifier

CalibrationObjective = Literal[
    "nse",
    "peak",
    "composite",
    "water_balance",
    "recession",
    "routing_event",
    "joint",
]


class ActionCode(StrEnum):
    A01_CHECK_DATA = "A01_CHECK_DATA"
    A02_REPAIR_DATA = "A02_REPAIR_DATA"
    A03_VALIDATE_SCHEME = "A03_VALIDATE_SCHEME"
    A04_REBUILD_STATE = "A04_REBUILD_STATE"
    A05_FORECAST = "A05_FORECAST"
    A06_DIAGNOSE = "A06_DIAGNOSE"
    A07_OPTIMIZE = "A07_OPTIMIZE"
    A08_GATE = "A08_GATE"
    A09_RESOLVE = "A09_RESOLVE"
    A10_FREEZE = "A10_FREEZE"
    A11_REPLAY = "A11_REPLAY"
    A12_EVALUATE_REPORT = "A12_EVALUATE_REPORT"


class ProblemHypothesis(StrEnum):
    DATA = "DATA"
    TIMING = "TIMING"
    STATE = "STATE"
    FORCING = "FORCING"
    MODEL = "MODEL"
    RESOURCE = "RESOURCE"
    UNKNOWN = "UNKNOWN"


class AgentDecision(FrozenModel):
    action: ActionCode
    hypothesis: ProblemHypothesis
    strategy_id: str | None = None
    # Optional optimize controls — agent selects groups/objective, never raw vectors.
    param_groups: tuple[Literal["evap", "runoff", "routing"], ...] | None = None
    objective: CalibrationObjective | None = None
    rationale_summary: str = Field(min_length=1, max_length=600)


class EvidencePacket(FrozenModel):
    evidence_id: Identifier
    task_id: Identifier
    action_run_id: Identifier | None = None
    action: ActionCode
    status: Literal[
        "succeeded",
        "failed",
        "blocked",
        "KEEP",
        "ACCEPT",
        "CONTINUE",
        "PHASE_PASS",
        "ROLLBACK",
        "PLATEAU_PASS",
        "PLATEAU_FAIL",
        "DATA_LIMIT",
        "FORCING_LIMIT",
        "STRUCTURAL_LIMIT",
        "HARD_BUDGET",
    ]
    observations: tuple[str, ...] = ()
    metrics: dict[str, float] = Field(default_factory=dict)
    gates: dict[str, str] = Field(default_factory=dict)
    artifact_ids: tuple[str, ...] = ()
    new_information_hash: str = Field(min_length=1)


class TaskSummary(FrozenModel):
    task_id: Identifier
    basin_id: str
    phase: Literal["B", "F", "E"]
    forcing_mode: Literal["R", "F"]
    terminal_status: str | None = None
    allow_optimization: bool = True


class ModelSummary(FrozenModel):
    model_id: Identifier
    capabilities: tuple[str, ...]


class SchemeSummary(FrozenModel):
    scheme_id: Identifier
    status: str
    content_hash: str


class BudgetSummary(FrozenModel):
    agent_rounds_remaining: int = Field(ge=0)
    optimization_cycles_remaining: int = Field(ge=0)
    max_agent_rounds: int = Field(ge=1)
    max_optimization_cycles: int = Field(ge=0)


class PermissionSummary(FrozenModel):
    safe_actions: tuple[ActionCode, ...]
    paused: bool = False


class EvidenceSummary(FrozenModel):
    evidence_id: Identifier
    action: ActionCode
    status: str
    new_information_hash: str
    observations: tuple[str, ...] = ()
    metrics: dict[str, float] = Field(default_factory=dict)
    gates: dict[str, str] = Field(default_factory=dict)


class HydroContext(FrozenModel):
    """Decision-relevant hydrologic context beyond ids/hashes."""

    current_parameters: dict[str, float] = Field(default_factory=dict)
    candidate_parameters: dict[str, float] | None = None
    parameter_delta: dict[str, float] = Field(default_factory=dict)
    latest_forecast_leads: dict[int, float] = Field(default_factory=dict)
    available_skills: tuple[str, ...] = ()
    available_strategies: tuple[str, ...] = ()
    available_param_groups: tuple[str, ...] = ("evap", "runoff", "routing")
    available_objectives: tuple[str, ...] = (
        "water_balance",
        "recession",
        "routing_event",
        "joint",
        "nse",
        "peak",
        "composite",
    )
    diagnosis: dict[str, object] = Field(default_factory=dict)
    calibration_phase: str = "P2_WATER_BALANCE"
    phase_history: tuple[str, ...] = ()
    experiment_history: tuple[str, ...] = ()
    skill_cards: tuple[dict[str, object], ...] = ()


class WorldStateView(FrozenModel):
    task: TaskSummary
    model: ModelSummary
    scheme: SchemeSummary
    permissions: PermissionSummary
    budget: BudgetSummary
    evidence_summary: tuple[EvidenceSummary, ...] = ()
    latest_forecast_id: str | None = None
    last_information_hash: str | None = None
    last_decision_fingerprint: str | None = None
    needs_follow_up: bool = True
    hydro: HydroContext = Field(default_factory=HydroContext)


# Hard ceilings only. Scientific stopping is phase/Gate/convergence controlled.
MAX_AGENT_ROUNDS = 100
MAX_OPTIMIZATION_CYCLES = 20
MAX_TECHNICAL_RETRIES = 2
