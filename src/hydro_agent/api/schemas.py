from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FrozenApiModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TaskCreateRequest(FrozenApiModel):
    basin_id: str = Field(min_length=1)
    model_id: Literal["xaj", "openhydronet"]
    start_date: date
    end_date: date
    forcing_mode: Literal["R", "F"]
    base_scheme_id: str = Field(min_length=1)
    allow_optimization: bool
    max_agent_decision_rounds: int = Field(default=20, ge=1, le=20)
    max_optimization_cycles: int = Field(default=4, ge=0, le=4)


class TaskSummary(FrozenApiModel):
    task_id: str
    basin_id: str
    model_id: str
    phase: Literal["B", "F", "E"]
    status: str
    paused: bool
    current_scheme_id: str | None
    agent_rounds_used: int
    optimization_cycles_used: int


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


class ForecastResult(FrozenApiModel):
    forecast_id: str
    scheme_id: str
    issue_time: datetime
    lead_values: dict[int, float]
    unit: str


class ResultSummary(FrozenApiModel):
    task_id: str
    phase: Literal["B", "F", "E"]
    scheme: SchemeResult | None
    forecasts: tuple[ForecastResult, ...]
    metrics: dict[str, float | None]
    gate: dict[str, object] | None
    report_artifacts: tuple[str, ...]
    costs: dict[str, float]
    story_zh: str = ""
    phase_zh: str = ""
    status_zh: str = ""


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
    tool_status: str | None = None
    tool_status_zh: str = ""
    tool_observations: tuple[str, ...] = ()
    tool_metrics: dict[str, float] = Field(default_factory=dict)
    error: str | None = None


class AgentLogSummary(FrozenApiModel):
    task_id: str
    rounds: tuple[AgentRoundLogItem, ...]
