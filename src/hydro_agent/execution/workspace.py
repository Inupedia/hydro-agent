import json
import os
from pathlib import Path

from .contracts import ExecutionRequest
from .hashing import sha256_file


class WorkspaceManager:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def create(self, request: ExecutionRequest) -> Path:
        task = self.root / request.task_id
        task.mkdir(parents=True, exist_ok=True)
        if task.is_symlink() or not task.resolve().is_relative_to(self.root):
            raise ValueError("workspace escapes root")
        workspace = task / request.action_run_id
        workspace.mkdir(exist_ok=False)
        for name in ("input", "work", "output", "logs"):
            (workspace / name).mkdir()
        (workspace / "execution-manifest.json").write_text(
            json.dumps(request.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8"
        )
        return workspace

    def materialize_file(self, source: Path, destination: Path) -> dict[str, object]:
        destination = destination.absolute()
        if not destination.resolve().is_relative_to(self.root):
            raise ValueError("destination escapes workspace root")
        relative = destination.relative_to(self.root)
        if len(relative.parts) < 4 or relative.parts[2] != "input":
            raise ValueError("destination must be inside an input directory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as src, destination.open("xb") as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)
        os.chmod(destination, 0o444)
        return {
            "path": str(destination),
            "sha256": sha256_file(destination),
            "bytes": destination.stat().st_size,
        }
