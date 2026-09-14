import json
import os
import shutil
from pathlib import Path

from .contracts import ExecutionRequest
from .hashing import sha256_file


class WorkspaceManager:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _workspace_path(self, request: ExecutionRequest) -> Path:
        task = self.root / request.task_id
        workspace = task / request.action_run_id
        if task.is_symlink() or not task.resolve().is_relative_to(self.root):
            raise ValueError("workspace escapes root")
        if workspace.is_symlink() or not workspace.resolve().is_relative_to(self.root):
            raise ValueError("workspace escapes root")
        return workspace

    def create(self, request: ExecutionRequest) -> Path:
        task = self.root / request.task_id
        task.mkdir(parents=True, exist_ok=True)
        workspace = self._workspace_path(request)
        workspace.mkdir(exist_ok=False)
        for name in ("input", "work", "output", "logs"):
            (workspace / name).mkdir()
        (workspace / "execution-manifest.json").write_text(
            json.dumps(request.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8"
        )
        return workspace

    def resume(self, request: ExecutionRequest) -> Path:
        """Reopen the same immutable action workspace after worker interruption.

        Inputs and ``work`` state are preserved. Previous output is discarded so
        a stale partial ``result.json`` cannot be mistaken for the resumed attempt.
        """

        workspace = self._workspace_path(request)
        if not workspace.is_dir():
            raise ValueError("resume workspace missing")
        manifest_path = workspace / "execution-manifest.json"
        if not manifest_path.is_file():
            raise ValueError("resume workspace missing execution manifest")
        stored = ExecutionRequest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if stored != request:
            raise ValueError("resume execution request mismatch")

        output = workspace / "output"
        if not output.is_dir() or output.is_symlink():
            raise ValueError("invalid resume output directory")
        for path in output.iterdir():
            if path.is_symlink():
                raise ValueError("unsafe resume output")
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        result_path = workspace / "execution-result.json"
        temporary_path = workspace / "execution-result.tmp"
        for path in (result_path, temporary_path):
            if path.exists():
                if path.is_symlink() or not path.is_file():
                    raise ValueError("unsafe resume result path")
                path.unlink()
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
