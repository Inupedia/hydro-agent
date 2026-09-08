from __future__ import annotations

from pathlib import Path

from hydro_agent.execution.contracts import ExecutionRequest
from hydro_agent.execution.workspace import WorkspaceManager
from hydro_agent.services.materialize import ExecutionInputMaterializer


class MaterializingWorkspaceManager(WorkspaceManager):
    """Creates a sandbox workspace and copies trusted Scheme/Snapshot inputs into it."""

    def __init__(self, root: Path, repository, *, snapshot_root: Path):
        super().__init__(root)
        self.materializer = ExecutionInputMaterializer(
            repository, snapshot_root=snapshot_root, workspaces=self
        )

    def create(self, request: ExecutionRequest) -> Path:
        workspace = super().create(request)
        self.materializer.materialize(request, workspace)
        return workspace
