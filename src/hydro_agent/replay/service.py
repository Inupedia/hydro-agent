from __future__ import annotations

from hydro_agent.replay.contracts import ReplayPlan
from hydro_agent.services.contracts import ForecastRecord
from hydro_agent.services.forecast import ForecastExecutionFailed


class ReplayStopped(RuntimeError):
    def __init__(
        self,
        *,
        completed: tuple[ForecastRecord, ...],
        failed_action_run_id: str | None,
        message: str,
    ):
        super().__init__(message)
        self.completed = completed
        self.failed_action_run_id = failed_action_run_id


class ReplayService:
    def __init__(self, repository, *, forecast_service, policy):
        self.repository = repository
        self.forecast_service = forecast_service
        self.policy = policy

    def execute(self, plan: ReplayPlan) -> tuple[ForecastRecord, ...]:
        task = self.repository.get_task(plan.task_id)
        if task.phase != "F":
            raise ValueError("replay requires F phase")
        scheme = self.repository.get_scheme(plan.scheme_id)
        if scheme.status != "frozen":
            raise ValueError("replay requires frozen scheme")
        completed: list[ForecastRecord] = []
        for case in plan.cases:
            existing = self.repository.get_forecast_for_issue(
                plan.task_id, plan.scheme_id, case.issue_time
            )
            if existing is not None:
                completed.append(
                    ForecastRecord(
                        forecast_id=existing.forecast_id,
                        task_id=existing.task_id,
                        action_run_id=existing.action_run_id,
                        scheme_id=existing.scheme_id,
                        data_snapshot_id=existing.data_snapshot_id,
                        issue_time=existing.issue_time,
                        lead_values={
                            int(k): float(v) for k, v in existing.lead_values_json.items()
                        },
                        unit=existing.unit,
                        artifact_ids=tuple(existing.artifact_ids_json),
                    )
                )
                continue
            issue_iso = case.issue_time.isoformat().replace("+00:00", "Z")
            try:
                record = self.forecast_service.forecast(
                    task_id=plan.task_id,
                    scheme_id=plan.scheme_id,
                    issue_time=issue_iso,
                    policy=self.policy,
                )
            except ForecastExecutionFailed as exc:
                raise ReplayStopped(
                    completed=tuple(completed),
                    failed_action_run_id=exc.action_run_id,
                    message=f"replay stopped at {issue_iso}: {exc}",
                ) from exc
            completed.append(record)
        return tuple(completed)
