from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ExecutionCapability = Literal[
    "validate", "rebuild_state", "forecast", "calibrate", "adapt", "evaluate"
]
ExecutionStatus = Literal["succeeded", "failed", "timed_out", "contract_error"]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExecutionPolicy(FrozenModel):
    timeout_seconds: int = Field(gt=0)
    network_access: Literal[False]
    max_output_bytes: int = Field(gt=0)
    device: Literal["cpu", "mps"]


class ExecutionRequest(FrozenModel):
    task_id: Identifier
    action_run_id: Identifier
    model_id: Identifier
    capability: ExecutionCapability
    data_snapshot_id: Identifier
    scheme_id: Identifier
    issue_time: str | None
    parameters: dict[str, object]
    policy: ExecutionPolicy


class ExecutionResult(FrozenModel):
    action_run_id: Identifier
    status: ExecutionStatus
    exit_code: int | None
    wall_time_seconds: float = Field(ge=0, allow_inf_nan=False)
    peak_memory_bytes: int | None = Field(default=None, ge=0)
    stdout_artifact: str
    stderr_artifact: str
    output_artifacts: tuple[str, ...]
    result_payload: dict[str, object]
    error_code: str | None
