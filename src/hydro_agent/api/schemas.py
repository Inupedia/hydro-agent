from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenApiModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TaskCreateRequest(FrozenApiModel):
    basin_id: str = Field(min_length=1)
    # Registry is the SSOT for installed models; API does not hardcode an enum.
    model_id: str = Field(min_length=1, max_length=64)
    start_date: date
    end_date: date
    forcing_mode: Literal["R", "F"]
    base_scheme_id: str = Field(min_length=1)
    model_plan_id: str | None = None
    name: str | None = Field(default=None, max_length=80)
    allow_optimization: bool
    # Day-count controls remain convenient for short/smoke tasks. Formal studies
    # should preregister explicit development/final-test dates so complete years
    # are not silently truncated by UI/API defaults.
    validation_days: int = Field(default=30, ge=3, le=3650)
    final_test_days: int = Field(default=30, ge=3, le=3650)
    development_start_date: date | None = None
    development_end_date: date | None = None
    final_test_start_date: date | None = None
    final_test_end_date: date | None = None
    max_agent_decision_rounds: int = Field(default=20, ge=1, le=100)
    # Legacy cycle count remains a smoke wiring cap only. Formal campaign lifetime
    # is governed by model-evaluation and convergence policy below.
    max_optimization_cycles: int = Field(default=4, ge=0, le=20)
    campaign_mode: Literal["smoke", "target_quality", "convergence"] = "smoke"
    campaign_max_model_evaluations: int | None = Field(default=None, ge=1)
    campaign_min_model_evaluations: int | None = Field(default=None, ge=1)
    campaign_plateau_window: int | None = Field(default=None, ge=2, le=50)
    campaign_plateau_abs_epsilon: float | None = Field(default=None, ge=0.0)
    campaign_restart_distinct_strategies: int = Field(default=2, ge=2, le=8)
    campaign_max_no_gain_gates: int | None = Field(default=None, ge=1, le=50)
    # The scoring ruler is preregistered with the campaign and is immutable
    # across A07 experiments. Diagnosis/expert advice cannot swap it mid-run.
    calibration_objective: Literal["nse", "peak", "composite"] = "nse"
    # External/seed expert priors are disabled unless the campaign explicitly
    # opts in. Dataset ids provide a second guard against indirect same-data leakage.
    allow_unverified_expert_priors: bool = False
    forbidden_evidence_dataset_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def explicit_protocol_is_complete(self):
        values = (
            self.development_start_date,
            self.development_end_date,
            self.final_test_start_date,
            self.final_test_end_date,
        )
        supplied = sum(value is not None for value in values)
        if supplied not in {0, 4}:
            raise ValueError(
                "explicit protocol requires development_start/end and final_test_start/end together"
            )

        if self.campaign_mode == "convergence":
            required = {
                "campaign_max_model_evaluations": self.campaign_max_model_evaluations,
                "campaign_min_model_evaluations": self.campaign_min_model_evaluations,
                "campaign_plateau_window": self.campaign_plateau_window,
                "campaign_plateau_abs_epsilon": self.campaign_plateau_abs_epsilon,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(
                    "convergence campaign requires preregistered policy: " + ", ".join(missing)
                )
        if self.campaign_mode == "target_quality" and self.campaign_max_model_evaluations is None:
            raise ValueError("target_quality campaign requires campaign_max_model_evaluations")
        if (
            self.campaign_min_model_evaluations is not None
            and self.campaign_max_model_evaluations is not None
            and self.campaign_min_model_evaluations > self.campaign_max_model_evaluations
        ):
            raise ValueError(
                "campaign_min_model_evaluations exceeds campaign_max_model_evaluations"
            )
        return self


class TaskSummary(FrozenApiModel):
    task_id: str
    basin_id: str
    model_id: str
    phase: Literal["B", "F", "E"]
    status: str
    paused: bool
    current_scheme_id: str | None
    model_plan_id: str | None = None
    name: str | None = None
    agent_rounds_used: int
    optimization_cycles_used: int
    start_date: str | None = None
    end_date: str | None = None
    validation_days: int | None = None
    final_test_days: int | None = None
    forcing_mode: Literal["R", "F"] | None = None
    created_at: str | None = None
    workflow_id: str | None = None
    workflow_version: str | None = None
    workflow_hash: str | None = None


class RenameTaskBody(FrozenApiModel):
    name: str | None = Field(default=None, max_length=80)


class RunSummary(FrozenApiModel):
    task_id: str
    worker_active: bool
    paused: bool
    phase: Literal["B", "F", "E"]
    status: str
    needs_follow_up: bool
    agent_rounds_remaining: int
    optimization_cycles_remaining: int
    current_scheme_id: str | None
    last_action: str | None = None
    last_hypothesis: str | None = None
    llm_streaming: bool = False
    llm_text: str = ""
    llm_error: str | None = None
    llm_decision_action: str | None = None
    queue_position: int | None = None
    worker_slots_used: int = 0
    worker_slots_max: int = 5


class TimelineItem(FrozenApiModel):
    id: str
    occurred_at: datetime
    label: str
    status: str
    action: str | None
    evidence_id: str | None
    details: dict[str, object]


class SchemeResult(FrozenApiModel):
    scheme_id: str
    status: str
    content_hash: str
    model_id: str
    provenance: dict[str, object] = Field(default_factory=dict)
    parameters: dict[str, float] = Field(default_factory=dict)
    base_parameters: dict[str, float] = Field(default_factory=dict)
    parameter_delta: dict[str, float] = Field(default_factory=dict)
    adopted_parameter_delta: dict[str, float] = Field(default_factory=dict)
    candidate_scheme_id: str | None = None
    candidate_parameters: dict[str, float] = Field(default_factory=dict)
    candidate_parameter_delta: dict[str, float] = Field(default_factory=dict)


class ForecastResult(FrozenApiModel):
    forecast_id: str
    scheme_id: str
    issue_time: datetime
    lead_values: dict[int, float]
    unit: str


class HydrographPoint(FrozenApiModel):
    time: str
    observed_m3s: float | None = None
    baseline_m3s: float | None = None
    candidate_m3s: float | None = None
    frozen_m3s: float | None = None
    change_m3s: float | None = None
    window: str
    is_warmup: bool = False


class HydrographComparisonResult(FrozenApiModel):
    kind: Literal["calibration", "independent_test"]
    title: str
    calibrated: bool = False
    gate_status: str | None = None
    warmup_days: int = 0
    evaluated_days: int = 0
    series: tuple[HydrographPoint, ...] = ()
    baseline_metrics: dict[str, float | int | str | None] | None = None
    candidate_metrics: dict[str, float | int | str | None] | None = None
    frozen_metrics: dict[str, float | int | str | None] | None = None
    change: dict[str, float | None] | None = None
    parameter_delta: dict[str, float] = Field(default_factory=dict)
    windows: dict[str, str] = Field(default_factory=dict)


class ResultSummary(FrozenApiModel):
    task_id: str
    phase: Literal["B", "F", "E"]
    scheme: SchemeResult | None
    forecasts: tuple[ForecastResult, ...]
    metrics: dict[str, float | None]
    gate: dict[str, object] | None
    diagnosis: dict[str, object] | None = None
    optimize: dict[str, object] | None = None
    calibration_hydrograph: HydrographComparisonResult | None = None
    test_hydrograph: HydrographComparisonResult | None = None
    report_artifacts: tuple[str, ...]
    costs: dict[str, float]
    story_zh: str = ""
    phase_zh: str = ""
    status_zh: str = ""


class ToolCallAudit(FrozenApiModel):
    tool_call_id: str | None = None
    action: str
    tool_id: str
    tool_name: str
    tool_name_zh: str
    category: Literal[
        "data",
        "model",
        "diagnosis",
        "optimization",
        "validation",
        "governance",
        "replay",
        "report",
    ]
    description_zh: str = ""
    status: str
    input_summary: dict[str, object] = Field(default_factory=dict)
    output_summary: dict[str, object] = Field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    action_run_id: str | None = None
    evidence_id: str | None = None
    artifact_ids: tuple[str, ...] = ()
    child_calls: tuple[dict[str, object], ...] = ()
    metrics: dict[str, object] = Field(default_factory=dict)


class EvidenceAuditSummary(FrozenApiModel):
    evidence_id: str | None = None
    action: str | None = None
    status: str | None = None
    observations: tuple[str, ...] = ()
    metrics: dict[str, float] = Field(default_factory=dict)
    gates: dict[str, object] = Field(default_factory=dict)


class AgentRoundLogItem(FrozenApiModel):
    round_number: int
    occurred_at: str | None = None
    action: str | None = None
    action_zh: str = ""
    hypothesis: str | None = None
    hypothesis_zh: str = ""
    strategy_id: str | None = None
    rationale_summary: str = ""
    llm_output: str = ""
    input_summary_zh: str = ""
    judgment_zh: str = ""
    input_world_state: dict[str, object] = Field(default_factory=dict)
    activated_skill_ids: tuple[str, ...] = ()
    activated_skills_audit: tuple[dict, ...] = ()
    tool_status: str | None = None
    tool_status_zh: str = ""
    tool_observations: tuple[str, ...] = ()
    tool_metrics: dict[str, float] = Field(default_factory=dict)
    tool_calls: tuple[ToolCallAudit, ...] = ()
    evidence_summary: EvidenceAuditSummary | None = None
    error: str | None = None


class AgentLogSummary(FrozenApiModel):
    task_id: str
    rounds: tuple[AgentRoundLogItem, ...]
