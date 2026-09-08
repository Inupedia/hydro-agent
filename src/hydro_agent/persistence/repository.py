from datetime import timezone
from pathlib import PurePosixPath

from pydantic import AwareDatetime, TypeAdapter
from sqlalchemy import select, update

from hydro_agent.execution.contracts import ExecutionPolicy, ExecutionRequest, ExecutionResult
from hydro_agent.services.contracts import ForecastCreate, ForecastRecord

from .database import Database
from .models import (
    ActionRun,
    AgentDecisionRun,
    Artifact,
    CostLedger,
    DataSnapshot,
    Evidence,
    Forecast,
    Scheme,
    Task,
    TaskState,
    now,
)
from .schemas import DataSnapshotCreate, SchemeCreate, TaskCreate


def timestamp(value):
    if value is None:
        return None
    return TypeAdapter(AwareDatetime).validate_python(value).astimezone(timezone.utc)


class HydroRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def _create(self, row):
        with self.database.session() as session:
            session.add(row)
            session.flush()
        return row

    def _get(self, model, identifier):
        with self.database.session() as session:
            row = session.get(model, identifier)
            if row is None:
                raise KeyError(identifier)
            return row

    def create_task(self, **kwargs):
        data = TaskCreate(**kwargs)
        return self._create(Task(**data.model_dump()))

    def create_scheme(self, **kwargs):
        data = SchemeCreate(**kwargs).model_dump()
        data["config_json"] = data.pop("config")
        return self._create(Scheme(**data))

    def create_snapshot(self, **kwargs):
        data = DataSnapshotCreate(**kwargs).model_dump()
        data["manifest_json"] = data.pop("manifest")
        return self._create(DataSnapshot(**data))

    def get_task(self, task_id):
        return self._get(Task, task_id)

    def list_snapshots(self, task_id):
        with self.database.session() as session:
            return list(
                session.scalars(select(DataSnapshot).where(DataSnapshot.task_id == task_id))
            )

    def get_scheme(self, scheme_id):
        return self._get(Scheme, scheme_id)

    def get_snapshot(self, snapshot_id):
        return self._get(DataSnapshot, snapshot_id)

    def get_action_run(self, action_run_id):
        return self._get(ActionRun, action_run_id)

    def get_cost(self, action_run_id):
        return self._get(CostLedger, action_run_id)

    def list_artifacts(self, action_run_id):
        with self.database.session() as session:
            return list(
                session.scalars(
                    select(Artifact)
                    .where(Artifact.action_run_id == action_run_id)
                    .order_by(Artifact.artifact_id)
                )
            )

    def list_schemes(self, task_id=None, status=None):
        with self.database.session() as session:
            stmt = select(Scheme).order_by(Scheme.scheme_id)
            if task_id is not None:
                stmt = stmt.where(Scheme.task_id == task_id)
            if status is not None:
                stmt = stmt.where(Scheme.status == status)
            return list(session.scalars(stmt))

    def create_forecast(self, **kwargs):
        data = ForecastCreate(**kwargs)
        record = ForecastRecord(
            forecast_id=data.forecast_id,
            task_id=data.task_id,
            action_run_id=data.action_run_id,
            scheme_id=data.scheme_id,
            data_snapshot_id=data.data_snapshot_id,
            issue_time=timestamp(data.issue_time),
            lead_values=data.lead_values,
            unit=data.unit,
            artifact_ids=data.artifact_ids,
        )
        row = Forecast(
            forecast_id=record.forecast_id,
            task_id=record.task_id,
            action_run_id=record.action_run_id,
            scheme_id=record.scheme_id,
            data_snapshot_id=record.data_snapshot_id,
            issue_time=record.issue_time,
            lead_values_json={str(k): float(v) for k, v in sorted(record.lead_values.items())},
            unit=record.unit,
            artifact_ids_json=list(record.artifact_ids),
        )
        return self._create(row)

    def get_forecast(self, forecast_id):
        return self._get(Forecast, forecast_id)

    def list_forecasts(self, task_id=None):
        with self.database.session() as session:
            stmt = select(Forecast).order_by(Forecast.forecast_id)
            if task_id is not None:
                stmt = stmt.where(Forecast.task_id == task_id)
            return list(session.scalars(stmt))

    def create_action_run(self, **kwargs):
        # Validate identifiers/capability before they can become execution paths.
        request = ExecutionRequest(
            **kwargs,
            parameters={},
            policy=ExecutionPolicy(
                timeout_seconds=1, network_access=False, max_output_bytes=1, device="cpu"
            ),
        )
        with self.database.session() as session:
            scheme = session.get(Scheme, request.scheme_id)
            snapshot = session.get(DataSnapshot, request.data_snapshot_id)
            task = session.get(Task, request.task_id)
            if task is None or scheme is None or snapshot is None:
                raise ValueError("missing task, scheme or snapshot")
            if scheme.task_id != task.task_id or snapshot.task_id != task.task_id:
                raise ValueError("cross-task references are forbidden")
            if scheme.model_id != request.model_id:
                raise ValueError("scheme model mismatch")
            if task.phase in ("F", "E") and request.capability in ("calibrate", "adapt"):
                raise ValueError("optimization forbidden in F/E")
            values = request.model_dump(exclude={"parameters", "policy"})
            values["issue_time"] = timestamp(request.issue_time)
            row = ActionRun(**values)
            session.add(row)
            session.flush()
        return row

    def build_execution_request(self, action_run_id, parameters, policy):
        action = self.get_action_run(action_run_id)
        if action.status != "pending":
            raise ValueError("action is not pending")
        return ExecutionRequest(
            task_id=action.task_id,
            action_run_id=action.action_run_id,
            model_id=action.model_id,
            capability=action.capability,
            data_snapshot_id=action.data_snapshot_id,
            scheme_id=action.scheme_id,
            issue_time=action.issue_time.isoformat() if action.issue_time else None,
            parameters=parameters,
            policy=policy,
        )

    def record_execution_result(self, result: ExecutionResult, artifacts):
        if result.status != "succeeded" and any(a["promoted"] for a in artifacts):
            raise ValueError("failed run cannot promote output artifacts")
        for item in artifacts:
            path = PurePosixPath(item["relative_path"])
            if path.is_absolute() or ".." in path.parts or "\\" in str(path) or not path.parts:
                raise ValueError("invalid artifact path")
            if item["promoted"] and item["relative_path"] not in result.output_artifacts:
                raise ValueError("promoted artifact is not in execution outputs")
        with self.database.session() as session:
            # Conditional UPDATE serializes terminal transitions across concurrent writers.
            changed = session.execute(
                update(ActionRun)
                .where(
                    ActionRun.action_run_id == result.action_run_id,
                    ActionRun.status.in_(("pending", "running")),
                )
                .values(status=result.status, error_code=result.error_code, finished_at=now())
            )
            if changed.rowcount != 1:
                raise ValueError("action missing or already terminal")
            session.add(
                CostLedger(
                    action_run_id=result.action_run_id,
                    wall_time_seconds=result.wall_time_seconds,
                    peak_memory_bytes=result.peak_memory_bytes,
                )
            )
            for item in artifacts:
                session.add(Artifact(action_run_id=result.action_run_id, **item))

    def ensure_task_state(self, task_id: str, *, current_scheme_id: str | None = None):
        with self.database.session() as session:
            state = session.get(TaskState, task_id)
            if state is not None:
                return state
            if current_scheme_id is None:
                schemes = list(
                    session.scalars(
                        select(Scheme).where(Scheme.task_id == task_id).order_by(Scheme.scheme_id)
                    )
                )
                if not schemes:
                    raise KeyError(f"no scheme for task {task_id}")
                current_scheme_id = next(
                    (s.scheme_id for s in schemes if s.status in ("base", "accepted", "frozen")),
                    schemes[0].scheme_id,
                )
            state = TaskState(
                task_id=task_id,
                current_scheme_id=current_scheme_id,
                agent_rounds_used=0,
                optimization_cycles_used=0,
                paused=False,
                needs_follow_up=True,
                last_information_hash=None,
                last_decision_fingerprint=None,
            )
            session.add(state)
            session.flush()
            return state

    def get_task_state(self, task_id: str):
        return self._get(TaskState, task_id)

    def update_task_state(self, task_id: str, **fields):
        allowed = {
            "current_scheme_id",
            "agent_rounds_used",
            "optimization_cycles_used",
            "paused",
            "needs_follow_up",
            "last_information_hash",
            "last_decision_fingerprint",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown task state fields: {sorted(unknown)}")
        with self.database.session() as session:
            state = session.get(TaskState, task_id)
            if state is None:
                raise KeyError(task_id)
            for key, value in fields.items():
                setattr(state, key, value)
            state.updated_at = now()
            session.flush()
            return state

    def add_evidence(self, packet):
        row = Evidence(
            evidence_id=packet.evidence_id,
            task_id=packet.task_id,
            action_run_id=packet.action_run_id,
            action=packet.action.value if hasattr(packet.action, "value") else packet.action,
            status=packet.status,
            observations_json=list(packet.observations),
            metrics_json=dict(packet.metrics),
            gates_json=dict(packet.gates),
            artifact_ids_json=list(packet.artifact_ids),
            new_information_hash=packet.new_information_hash,
            payload_json=packet.model_dump(mode="json"),
        )
        return self._create(row)

    def list_evidence(self, task_id: str):
        with self.database.session() as session:
            return list(
                session.scalars(
                    select(Evidence)
                    .where(Evidence.task_id == task_id)
                    .order_by(Evidence.created_at, Evidence.evidence_id)
                )
            )

    def record_agent_decision(self, **kwargs):
        row = AgentDecisionRun(**kwargs)
        return self._create(row)
