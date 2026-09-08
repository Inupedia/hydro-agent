from pathlib import Path
from typing import Protocol

from .contracts import ExecutionCapability, ExecutionRequest


class RuntimeAdapter(Protocol):
    model_id: str
    capabilities: frozenset[ExecutionCapability]

    def command(self, request: ExecutionRequest, workspace: Path) -> list[str]: ...
