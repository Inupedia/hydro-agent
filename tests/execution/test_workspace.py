import json

import pytest

from hydro_agent.execution.workspace import WorkspaceManager


def test_workspace(tmp_path, execution_request):
    manager = WorkspaceManager(tmp_path / ".runs")
    workspace = manager.create(execution_request)
    assert all((workspace / p).is_dir() for p in ("input", "work", "output", "logs"))
    assert (
        json.loads((workspace / "execution-manifest.json").read_text())["action_run_id"] == "run-1"
    )
    with pytest.raises(FileExistsError):
        manager.create(execution_request)
    source = tmp_path / "data"
    source.write_bytes(b"unchanged")
    dest = workspace / "input" / "data"
    metadata = manager.materialize_file(source, dest)
    assert metadata["bytes"] == 9
    assert dest.stat().st_mode & 0o222 == 0
    with pytest.raises(FileExistsError):
        manager.materialize_file(source, dest)
    with pytest.raises(ValueError):
        manager.materialize_file(source, tmp_path / "outside")


def test_symlink_task_rejected(tmp_path, execution_request):
    root = tmp_path / "runs"
    root.mkdir()
    (root / "task-1").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        WorkspaceManager(root).create(execution_request)
