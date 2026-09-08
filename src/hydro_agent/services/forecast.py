from __future__ import annotations

from hydro_agent.execution.hashing import sha256_file
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.services.contracts import ForecastRecord
from hydro_agent.services.snapshots import SnapshotResolver, new_action_run_id


class ForecastExecutionFailed(RuntimeError):
    def __init__(self, action_run_id: str, status: str, error_code: str | None):
        super().__init__(f"forecast failed: {status}/{error_code}")
        self.action_run_id = action_run_id
        self.status = status
        self.error_code = error_code


class ForecastService:
    def __init__(
        self,
        repository,
        *,
        resolver: SnapshotResolver,
        runner: SandboxRunner,
        model_id: str = "xaj",
    ):
        self.repository = repository
        self.resolver = resolver
        self.runner = runner
        self.model_id = model_id

    def forecast(self, *, task_id: str, scheme_id: str, issue_time: str, policy) -> ForecastRecord:
        snapshot_id = self.resolver.resolve(task_id, "forecast", issue_time)
        action_run_id = new_action_run_id()
        self.repository.create_action_run(
            task_id=task_id,
            action_run_id=action_run_id,
            model_id=self.model_id,
            capability="forecast",
            data_snapshot_id=snapshot_id,
            scheme_id=scheme_id,
            issue_time=issue_time,
        )
        request = self.repository.build_execution_request(action_run_id, {}, policy)
        result = self.runner.run(request)
        workspace = self.runner.workspaces.root / request.task_id / request.action_run_id
        artifacts = []
        for index, relative in enumerate(
            (result.stdout_artifact, result.stderr_artifact, *result.output_artifacts)
        ):
            path = workspace / relative
            artifacts.append(
                dict(
                    artifact_id=f"{action_run_id}-a{index}",
                    kind="execution",
                    relative_path=relative,
                    sha256=sha256_file(path),
                    bytes=path.stat().st_size,
                    promoted=relative in result.output_artifacts,
                )
            )
        self.repository.record_execution_result(result, artifacts)
        if result.status != "succeeded":
            raise ForecastExecutionFailed(action_run_id, result.status, result.error_code)
        payload = result.result_payload
        forecast_rows = payload.get("forecast") or []
        if (
            payload.get("unit") != "m3/s"
            or payload.get("scheme_id") != scheme_id
            or payload.get("data_snapshot_id") != snapshot_id
            or [row.get("lead") for row in forecast_rows] != [1, 2, 3]
        ):
            raise ForecastExecutionFailed(
                action_run_id, "contract_error", "invalid_forecast_payload"
            )
        lead_values = {int(row["lead"]): float(row["value"]) for row in forecast_rows}
        forecast_id = f"fc-{action_run_id}"
        self.repository.create_forecast(
            forecast_id=forecast_id,
            task_id=task_id,
            action_run_id=action_run_id,
            scheme_id=scheme_id,
            data_snapshot_id=snapshot_id,
            issue_time=issue_time,
            lead_values=lead_values,
            unit="m3/s",
            artifact_ids=tuple(a["artifact_id"] for a in artifacts if a["promoted"]),
        )
        row = self.repository.get_forecast(forecast_id)
        return ForecastRecord(
            forecast_id=row.forecast_id,
            task_id=row.task_id,
            action_run_id=row.action_run_id,
            scheme_id=row.scheme_id,
            data_snapshot_id=row.data_snapshot_id,
            issue_time=row.issue_time,
            lead_values={int(k): float(v) for k, v in row.lead_values_json.items()},
            unit=row.unit,
            artifact_ids=tuple(row.artifact_ids_json),
        )
