from __future__ import annotations

from typing import Any

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel, Identifier
from hydro_agent.execution.hashing import sha256_file
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry
from hydro_agent.services.snapshots import new_action_run_id


class CalibrationOutcome(FrozenModel):
    action_run_id: Identifier
    strategy_id: str
    base_scheme_id: Identifier
    candidate_parameters: dict[str, float]
    objective_value: float
    artifact_ids: tuple[str, ...] = Field(default_factory=tuple)
    result_payload: dict[str, Any] = Field(default_factory=dict)


class CalibrationExecutionFailed(RuntimeError):
    def __init__(self, action_run_id: str, status: str, error_code: str | None):
        super().__init__(f"calibration failed: {status}/{error_code}")
        self.action_run_id = action_run_id
        self.status = status
        self.error_code = error_code


class CalibrationService:
    def __init__(self, repository, *, runner: SandboxRunner, model_id: str = "xaj"):
        self.repository = repository
        self.runner = runner
        self.model_id = model_id
        self.strategies = CalibrationStrategyRegistry()

    def calibrate(
        self,
        *,
        task_id: str,
        base_scheme_id: str,
        calibration_snapshot_id: str,
        validation_snapshot_id: str,
        strategy_id: str,
        policy,
    ) -> CalibrationOutcome:
        task = self.repository.get_task(task_id)
        if task.phase in ("F", "E"):
            raise ValueError("optimization forbidden in F/E")
        strategy = self.strategies.get(strategy_id)
        base = self.repository.get_scheme(base_scheme_id)
        cal_snap = self.repository.get_snapshot(calibration_snapshot_id)
        val_snap = self.repository.get_snapshot(validation_snapshot_id)
        if base.task_id != task_id or cal_snap.task_id != task_id or val_snap.task_id != task_id:
            raise ValueError("cross-task references are forbidden")
        if base.model_id != self.model_id:
            raise ValueError("scheme model mismatch")
        action_run_id = new_action_run_id()
        self.repository.create_action_run(
            task_id=task_id,
            action_run_id=action_run_id,
            model_id=self.model_id,
            capability="calibrate",
            data_snapshot_id=calibration_snapshot_id,
            scheme_id=base_scheme_id,
            issue_time=None,
        )
        request = self.repository.build_execution_request(
            action_run_id,
            {"strategy_id": strategy.strategy_id, "validation_snapshot_id": validation_snapshot_id},
            policy,
        )
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
            raise CalibrationExecutionFailed(action_run_id, result.status, result.error_code)
        payload = result.result_payload
        parameters = payload.get("candidate_parameters")
        if not isinstance(parameters, dict) or payload.get("strategy_id") != strategy.strategy_id:
            raise CalibrationExecutionFailed(
                action_run_id, "contract_error", "invalid_calibration_payload"
            )
        return CalibrationOutcome(
            action_run_id=action_run_id,
            strategy_id=strategy.strategy_id,
            base_scheme_id=base_scheme_id,
            candidate_parameters={str(k): float(v) for k, v in parameters.items()},
            objective_value=float(payload["objective_value"]),
            artifact_ids=tuple(a["artifact_id"] for a in artifacts if a["promoted"]),
            result_payload=dict(payload),
        )
