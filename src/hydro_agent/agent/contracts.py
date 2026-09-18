from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel, Identifier
from hydro_agent.experience.retrieval import ExperienceMatch
from hydro_agent.optimization.campaign import CampaignSnapshot


class ActionCode(StrEnum):
    A01_CHECK_DATA = "A01_CHECK_DATA"
    A02_VALIDATE_SCHEME = "A02_VALIDATE_SCHEME"
    A03_FORECAST = "A03_FORECAST"
    A04_DIAGNOSE = "A04_DIAGNOSE"
    A05_OPTIMIZE = "A05_OPTIMIZE"
    A06_GATE = "A06_GATE"
    A07_RESOLVE = "A07_RESOLVE"
    A08_FREEZE = "A08_FREEZE"
    A09_REPLAY = "A09_REPLAY"
    A10_EVALUATE_REPORT = "A10_EVALUATE_REPORT"


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
    param_groups: tuple[str, ...] | None = None
    objective: Literal["nse", "peak", "composite"] | None = None
    rationale_summary: str = Field(min_length=1, max_length=600)
    # Structured ExperimentPlan metadata is populated by the deterministic
    # planning guardrail, never invented as free-form model reasoning.
    experiment_plan_id: str | None = Field(default=None, max_length=96)
    experiment_signature: str | None = Field(default=None, max_length=64)
    experiment_reason_codes: tuple[str, ...] = ()
    experiment_evidence_refs: tuple[str, ...] = ()
    activated_skill_ids: tuple[str, ...] = ()
    activated_skills_audit: tuple[dict, ...] = ()
    experience_skill_version: int | None = Field(default=None, ge=1)
    experience_skill_hash: str | None = None
    experience_refs: tuple[str, ...] = ()
    experience_mode: Literal["exploitation", "exploration"] | None = None
    experience_influence: tuple[str, ...] = ()
    # User-facing audit trace. These are concise decision summaries, not hidden chain-of-thought.
    observation_zh: str = Field(default="", max_length=240)
    analysis_zh: str = Field(default="", max_length=600)
    decision_zh: str = Field(default="", max_length=240)


class EvidencePacket(FrozenModel):
    evidence_id: Identifier
    task_id: Identifier
    action_run_id: Identifier | None = None
    decision_id: Identifier | None = None
    round_number: int | None = None
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
    allow_optimization: bool = True


class ModelSummary(FrozenModel):
    model_id: Identifier
    capabilities: tuple[str, ...]
    validation_status: str = "unknown"
    implementation_name: str = "unspecified"
    limitations: tuple[str, ...] = ()


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


class ExperienceContext(FrozenModel):
    skill_version: int | None = Field(default=None, ge=1)
    skill_hash: str | None = None
    status: Literal["learning", "converging", "converged", "reopened"] = "learning"
    matches: tuple[ExperienceMatch, ...] = ()
    source_revisions: dict[str, int] = Field(default_factory=dict)
    exploration_level: float = Field(default=0.75, ge=0.0, le=1.0)


class HydroContext(FrozenModel):
    """Decision-relevant hydrologic context beyond ids/hashes."""

    current_parameters: dict[str, float] = Field(default_factory=dict)
    candidate_parameters: dict[str, float] | None = None
    parameter_delta: dict[str, float] = Field(default_factory=dict)
    latest_forecast_leads: dict[int, float] = Field(default_factory=dict)
    available_skills: tuple[str, ...] = ()
    available_strategies: tuple[str, ...] = ()
    available_param_groups: tuple[str, ...] = ("evap", "runoff", "routing")
    available_objectives: tuple[str, ...] = ("nse", "peak", "composite")
    # Pre-registered objective for the campaign. Diagnosis/expert advice may
    # choose where/how to search but cannot change the scoring ruler mid-run.
    campaign_objective: Literal["nse", "peak", "composite"] = "nse"
    campaign: CampaignSnapshot = Field(default_factory=lambda: CampaignSnapshot(mode="smoke"))
    # Unverified expert priors are opt-in campaign inputs, never implicit
    # runtime defaults. Dataset ids can additionally block indirect leakage.
    allow_unverified_expert_priors: bool = False
    forbidden_evidence_dataset_ids: tuple[str, ...] = ()
    diagnosis: dict[str, object] = Field(default_factory=dict)
    experiment_history: tuple[str, ...] = ()
    skill_cards: tuple[dict[str, object], ...] = ()
    experience: ExperienceContext = Field(default_factory=ExperienceContext)


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


MAX_AGENT_ROUNDS = 20
MAX_OPTIMIZATION_CYCLES = 4
MAX_TECHNICAL_RETRIES = 2
