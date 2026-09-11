from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .database import Base


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timezone required")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


def now():
    return datetime.now(timezone.utc)


class Created:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Task(Created, Base):
    __tablename__ = "tasks"
    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    basin_id: Mapped[str]
    phase: Mapped[str]
    forcing_mode: Mapped[str]
    terminal_status: Mapped[str | None]
    workflow_id: Mapped[str | None] = mapped_column(String, nullable=True)
    workflow_version: Mapped[str | None] = mapped_column(String, nullable=True)
    workflow_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    __table_args__ = (
        CheckConstraint("phase IN ('B','F','E')"),
        CheckConstraint("forcing_mode IN ('R','F')"),
    )


class Scheme(Created, Base):
    __tablename__ = "schemes"
    scheme_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    model_id: Mapped[str]
    status: Mapped[str]
    config_json: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class DataSnapshot(Created, Base):
    __tablename__ = "data_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    source: Mapped[str]
    available_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    manifest_json: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str]


class ActionRun(Created, Base):
    __tablename__ = "action_runs"
    action_run_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    model_id: Mapped[str]
    capability: Mapped[str]
    data_snapshot_id: Mapped[str] = mapped_column(ForeignKey("data_snapshots.snapshot_id"))
    scheme_id: Mapped[str] = mapped_column(ForeignKey("schemes.scheme_id"))
    issue_time: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(default="pending")
    error_code: Mapped[str | None]
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Artifact(Created, Base):
    __tablename__ = "artifacts"
    artifact_id: Mapped[str] = mapped_column(String, primary_key=True)
    action_run_id: Mapped[str] = mapped_column(ForeignKey("action_runs.action_run_id"))
    kind: Mapped[str]
    relative_path: Mapped[str]
    sha256: Mapped[str]
    bytes: Mapped[int] = mapped_column(Integer)
    promoted: Mapped[bool] = mapped_column(Boolean)
    __table_args__ = (CheckConstraint("bytes >= 0"),)


class CostLedger(Base):
    __tablename__ = "cost_ledger"
    action_run_id: Mapped[str] = mapped_column(
        ForeignKey("action_runs.action_run_id"), primary_key=True
    )
    wall_time_seconds: Mapped[float] = mapped_column(Float)
    peak_memory_bytes: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("wall_time_seconds >= 0"),)


class Forecast(Created, Base):
    __tablename__ = "forecasts"
    forecast_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    action_run_id: Mapped[str] = mapped_column(ForeignKey("action_runs.action_run_id"), unique=True)
    scheme_id: Mapped[str] = mapped_column(ForeignKey("schemes.scheme_id"))
    data_snapshot_id: Mapped[str] = mapped_column(ForeignKey("data_snapshots.snapshot_id"))
    issue_time: Mapped[datetime] = mapped_column(UTCDateTime())
    lead_values_json: Mapped[dict] = mapped_column(JSON)
    unit: Mapped[str]
    artifact_ids_json: Mapped[list] = mapped_column(JSON)
    __table_args__ = (CheckConstraint("unit = 'm3/s'"),)


class TaskState(Base):
    __tablename__ = "task_state"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), primary_key=True)
    current_scheme_id: Mapped[str] = mapped_column(ForeignKey("schemes.scheme_id"))
    agent_rounds_used: Mapped[int] = mapped_column(Integer, default=0)
    optimization_cycles_used: Mapped[int] = mapped_column(Integer, default=0)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_follow_up: Mapped[bool] = mapped_column(Boolean, default=True)
    last_information_hash: Mapped[str | None]
    last_decision_fingerprint: Mapped[str | None]
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Evidence(Created, Base):
    __tablename__ = "evidence"
    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    action_run_id: Mapped[str | None] = mapped_column(ForeignKey("action_runs.action_run_id"))
    action: Mapped[str]
    status: Mapped[str]
    observations_json: Mapped[list] = mapped_column(JSON)
    metrics_json: Mapped[dict] = mapped_column(JSON)
    gates_json: Mapped[dict] = mapped_column(JSON)
    artifact_ids_json: Mapped[list] = mapped_column(JSON)
    new_information_hash: Mapped[str]
    payload_json: Mapped[dict] = mapped_column(JSON)


class AgentDecisionRun(Created, Base):
    __tablename__ = "agent_decisions"
    decision_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"))
    round_number: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str]
    model: Mapped[str | None]
    world_state_hash: Mapped[str]
    action: Mapped[str]
    hypothesis: Mapped[str]
    strategy_id: Mapped[str | None]
    rationale_summary: Mapped[str]
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
