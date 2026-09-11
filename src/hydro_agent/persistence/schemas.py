from typing import Literal

from pydantic import AwareDatetime, Field

from hydro_agent.execution.contracts import FrozenModel, Identifier


class TaskCreate(FrozenModel):
    task_id: Identifier
    basin_id: str = Field(min_length=1)
    phase: Literal["B", "F", "E"]
    forcing_mode: Literal["R", "F"]
    workflow_id: str | None = None
    workflow_version: str | None = None
    workflow_hash: str | None = None


class SchemeCreate(FrozenModel):
    scheme_id: Identifier
    task_id: Identifier
    model_id: Identifier
    status: Literal["base", "candidate", "accepted", "frozen"]
    config: dict[str, object]
    content_hash: str = Field(min_length=1)


class DataSnapshotCreate(FrozenModel):
    snapshot_id: Identifier
    task_id: Identifier
    source: str = Field(min_length=1)
    available_at: AwareDatetime | None
    manifest: dict[str, object]
    content_hash: str = Field(min_length=1)
