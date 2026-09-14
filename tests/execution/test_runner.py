import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import psutil
import pytest

from hydro_agent.execution.registry import RuntimeRegistry
from hydro_agent.execution.runner import SandboxRunner, _kill_group
from hydro_agent.execution.workspace import WorkspaceManager


class FixtureAdapter:
    model_id = "fixture"
    capabilities = frozenset({"forecast"})

    def __init__(self, mode):
        self.mode = mode

    def command(self, request, workspace):
        return [
            sys.executable,
            str(Path(__file__).parents[1] / "fixtures/fake_runtime.py"),
            str(workspace),
            self.mode,
        ]


def test_kill_group_allows_exit_reaping_race(monkeypatch):
    monkeypatch.setattr("os.killpg", Mock(side_effect=PermissionError("EPERM")))
    process = Mock(pid=123, poll=Mock(return_value=None))
    process.wait.return_value = 0
    _kill_group(process)
    assert process.wait.call_args_list[0].kwargs == {"timeout": 0.1}


def test_kill_group_does_not_hide_live_process_permission_error(monkeypatch):
    monkeypatch.setattr("os.killpg", Mock(side_effect=PermissionError("EPERM")))
    process = Mock(pid=123)
    process.wait.side_effect = subprocess.TimeoutExpired("fixture", 0.1)
    with pytest.raises(PermissionError, match="live runtime"):
        _kill_group(process)


@pytest.mark.parametrize(
    "mode,status,error",
    [
        ("success", "succeeded", None),
        ("fail", "failed", "runtime_exit_7"),
        ("sleep", "timed_out", "timeout"),
        ("child", "timed_out", "timeout"),
        ("missing", "contract_error", "missing_result"),
        ("large", "contract_error", "output_too_large"),
        ("log", "contract_error", "output_too_large"),
        ("invalid", "contract_error", "invalid_result_json"),
        ("array", "contract_error", "invalid_result_json"),
        ("nan", "contract_error", "invalid_result_json"),
        ("symlink", "contract_error", "unsafe_output"),
    ],
)
def test_runner(tmp_path, execution_request, mode, status, error):
    registry = RuntimeRegistry()
    registry.register(FixtureAdapter(mode))
    runner = SandboxRunner(registry, WorkspaceManager(tmp_path))
    result = runner.run(execution_request)
    assert (result.status, result.error_code) == (status, error)
    assert result.wall_time_seconds > 0
    workspace = tmp_path / "task-1/run-1"
    assert json.loads((workspace / "execution-result.json").read_text())["status"] == status
    if status == "succeeded":
        assert result.result_payload == {"value": 42}
        assert result.output_artifacts == ("output/result.json",)
    else:
        assert not result.output_artifacts
    if mode == "child":
        pid = int((workspace / "work/child.pid").read_text())
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


def test_runner_resume_reuses_work_state_and_discards_stale_output(tmp_path, execution_request):
    registry = RuntimeRegistry()
    registry.register(FixtureAdapter("resume"))
    runner = SandboxRunner(registry, WorkspaceManager(tmp_path))

    first = runner.run(execution_request)
    assert first.status == "timed_out"
    workspace = tmp_path / "task-1/run-1"
    assert (workspace / "work/resume.marker").read_text(encoding="utf-8") == "durable-state"
    assert json.loads((workspace / "output/result.json").read_text(encoding="utf-8")) == {
        "stale": True
    }

    second = runner.run(execution_request, resume=True)
    assert second.status == "succeeded"
    assert second.result_payload == {"resumed": True, "state_preserved": True}
    assert json.loads((workspace / "output/result.json").read_text(encoding="utf-8")) == {
        "resumed": True,
        "state_preserved": True,
    }
    logs = (workspace / "logs/stdout.log").read_text(encoding="utf-8")
    assert "fixture-runtime-first-attempt" in logs
    assert logs.count("fixture-runtime-finished") == 1


def test_secret_not_inherited(tmp_path, execution_request, monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-secret")
    registry = RuntimeRegistry()
    registry.register(FixtureAdapter("env"))
    result = SandboxRunner(registry, WorkspaceManager(tmp_path)).run(execution_request)
    assert result.result_payload == {"secret_present": False}


def test_unknown_runtime_is_persisted(tmp_path, execution_request):
    result = SandboxRunner(RuntimeRegistry(), WorkspaceManager(tmp_path)).run(execution_request)
    assert result.status == "failed"
    assert (tmp_path / "task-1/run-1/execution-result.json").exists()
