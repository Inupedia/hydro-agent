from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel, Identifier


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
    rationale_summary: str = Field(min_length=1, max_length=600)


class EvidencePacket(FrozenModel):
    evidence_id: Identifier
    task_id: Identifier
    action_run_id: Identifier | None = None
    action: ActionCode
    status: Literal["succeeded", "failed", "blocked", "KEEP", "ACCEPT", "ROLLBACK"]
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


MAX_AGENT_ROUNDS = 20
MAX_OPTIMIZATION_CYCLES = 4
MAX_TECHNICAL_RETRIES = 2
