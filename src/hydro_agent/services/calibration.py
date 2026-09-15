from __future__ import annotations

from typing import Any

from pydantic import Field

from hydro_agent.execution.contracts import ExecutionResult, FrozenModel, Identifier
from hydro_agent.execution.hashing import sha256_file
from hydro_agent.execution.runner import SandboxRunner
from hydro_agent.models.xaj.calibration_state import evaluation_count, has_resumable_state
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry
from hydro_agent.services.snapshots import new_action_run_id


class CalibrationOutcome(FrozenModel):
    action_run_id: Identifier
    strategy_id: str
    base_scheme_id: Identifier
    candidate_parameters: dict[str, float]
    objective_value: float
    objective: str = "nse"
    param_groups: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = Field(default_factory=tuple)
    result_payload: dict[str, Any] = Field(default_factory=dict)


class CalibrationExecutionFailed(RuntimeError):
    def __init__(
        self,
        action_run_id: str,
        status: str,
        error_code: str | None,
        *,
        model_evaluations: int = 0,
        evaluation_budget: int = 0,
        execution_attempts: int = 1,
        resume_attempts: int = 0,
    ):
        super().__init__(f"calibration failed: {status}/{error_code}")
        self.action_run_id = action_run_id
        self.status = status
        self.error_code = error_code
        self.model_evaluations = max(0, int(model_evaluations))
        self.evaluation_budget = max(0, int(evaluation_budget))
        self.execution_attempts = max(1, int(execution_attempts))
        self.resume_attempts = max(0, int(resume_attempts))


class CalibrationService:
    def __init__(
        self,
        repository,
        *,
        runner: SandboxRunner,
        model_id: str = "xaj",
        max_resume_attempts: int = 3,
    ):
        if max_resume_attempts < 0:
            raise ValueError("max_resume_attempts must be >= 0")
        self.repository = repository
        self.runner = runner
        self.model_id = model_id
        self.max_resume_attempts = max_resume_attempts
        self.strategies = CalibrationStrategyRegistry()

    def _run_with_resume(self, request, *, strategy) -> ExecutionResult:
        attempts = 0
        total_wall_time = 0.0
        peak_memory = 0
        while True:
            result = self.runner.run(request, resume=attempts > 0)
            total_wall_time += float(result.wall_time_seconds)
            peak_memory = max(peak_memory, int(result.peak_memory_bytes or 0))
            workspace = self.runner.workspaces.root / request.task_id / request.action_run_id

            if result.status == "succeeded":
                break
            if result.status == "contract_error":
                break
            if strategy.optimizer != "dds" or not has_resumable_state(workspace):
                break
            if attempts >= self.max_resume_attempts:
                break
            attempts += 1

        payload = dict(result.result_payload or {})
        payload["execution_attempts"] = attempts + 1
        payload["resume_attempts"] = attempts
        return result.model_copy(
            update={
                "wall_time_seconds": total_wall_time,
                "peak_memory_bytes": peak_memory or None,
                "result_payload": payload,
            }
        )

    def calibrate(
        self,
        *,
        task_id: str,
        base_scheme_id: str,
        calibration_snapshot_id: str,
        strategy_id: str,
        policy,
        param_groups: tuple[str, ...] | None = None,
        objective: str | None = None,
        evaluation_budget_override: int | None = None,
    ) -> CalibrationOutcome:
        """Search parameters using calibration data only.

        Candidate selection belongs exclusively to A08/development. A07 accepts
        only the calibration snapshot, so a development/final-test snapshot
        cannot accidentally cross the optimizer boundary.

        DDS runs may resume the *same* action workspace after a worker failure.
        Resume is attempted only when the runtime has emitted durable calibration
        state; completed model evaluations are restored from the workspace rather
        than charged to the campaign twice. If all attempts fail, the exception
        carries the durable evaluation count so A07 can still enter the Trial
        Ledger and consume the budget it actually spent.
        """

        task = self.repository.get_task(task_id)
        if task.phase in ("F", "E"):
            raise ValueError("optimization forbidden in F/E")
        strategy = self.strategies.get(strategy_id)
        evaluation_budget = strategy.evaluation_budget
        if evaluation_budget_override is not None:
            if evaluation_budget_override < 2:
                raise ValueError("remaining calibration evaluation budget must be >= 2")
            evaluation_budget = min(evaluation_budget, evaluation_budget_override)
        base = self.repository.get_scheme(base_scheme_id)
        cal_snap = self.repository.get_snapshot(calibration_snapshot_id)
        if base.task_id != task_id or cal_snap.task_id != task_id:
            raise ValueError("cross-task references are forbidden")
        if base.model_id != self.model_id:
            raise ValueError("scheme model mismatch")
        resolved_groups = tuple(param_groups) if param_groups else tuple(strategy.param_groups)
        resolved_objective = objective or strategy.objective
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
            {
                "strategy_id": strategy.strategy_id,
                "param_groups": list(resolved_groups),
                "objective": resolved_objective,
                "evaluation_budget": evaluation_budget,
            },
            policy,
        )
        result = self._run_with_resume(request, strategy=strategy)
        workspace = self.runner.workspaces.root / request.task_id / request.action_run_id
        payload = dict(result.result_payload or {})
        parameters = payload.get("candidate_parameters")
        if result.status == "succeeded" and (
            not isinstance(parameters, dict) or payload.get("strategy_id") != strategy.strategy_id
        ):
            result = result.model_copy(
                update={
                    "status": "contract_error",
                    "error_code": "invalid_calibration_payload",
                    "output_artifacts": (),
                }
            )

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
            raise CalibrationExecutionFailed(
                action_run_id,
                result.status,
                result.error_code,
                model_evaluations=evaluation_count(workspace),
                evaluation_budget=evaluation_budget,
                execution_attempts=int(payload.get("execution_attempts") or 1),
                resume_attempts=int(payload.get("resume_attempts") or 0),
            )
        assert isinstance(parameters, dict)
        return CalibrationOutcome(
            action_run_id=action_run_id,
            strategy_id=strategy.strategy_id,
            base_scheme_id=base_scheme_id,
            candidate_parameters={str(k): float(v) for k, v in parameters.items()},
            objective_value=float(payload["objective_value"]),
            objective=str(payload.get("objective") or resolved_objective),
            param_groups=tuple(payload.get("param_groups") or resolved_groups),
            artifact_ids=tuple(a["artifact_id"] for a in artifacts if a["promoted"]),
            result_payload=payload,
        )
