"""Supervision for trusted, registered runtimes; not an OS security sandbox."""

import json
import os
import signal
import stat
import subprocess
import time
from pathlib import Path

import psutil

from .contracts import ExecutionRequest, ExecutionResult
from .registry import RuntimeRegistry
from .workspace import WorkspaceManager


def _files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError("unsafe_output")
        if stat.S_ISREG(mode):
            files.append(path)
    return files


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


class SandboxRunner:
    def __init__(self, registry: RuntimeRegistry, workspaces: WorkspaceManager) -> None:
        self.registry = registry
        self.workspaces = workspaces

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        workspace = self.workspaces.create(request)
        started = time.monotonic()
        status, error, exit_code = "failed", None, None
        payload, outputs = {}, ()
        peak = 0
        process = None
        stdout, stderr = workspace / "logs/stdout.log", workspace / "logs/stderr.log"
        try:
            with stdout.open("wb") as out, stderr.open("wb") as err:
                adapter = self.registry.get(request.model_id, request.capability)
                command = adapter.command(request, workspace)
                if (
                    not isinstance(command, list)
                    or not command
                    or not all(isinstance(arg, str) and "\x00" not in arg for arg in command)
                ):
                    raise ValueError("invalid_runtime_command")
                # LLM credentials and proxy variables must not reach numerical runtimes.
                env = {
                    key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ
                }
                env.update(
                    {
                        "HOME": str(workspace / "work"),
                        "TMPDIR": str(workspace / "work"),
                        "PYTHONUNBUFFERED": "1",
                        "PYTHONDONTWRITEBYTECODE": "1",
                    }
                )
                process = subprocess.Popen(
                    command,
                    cwd=workspace / "work",
                    env=env,
                    stdout=out,
                    stderr=err,
                    stdin=subprocess.DEVNULL,
                    shell=False,
                    start_new_session=True,
                )
                while True:
                    try:
                        parent = psutil.Process(process.pid)
                        rss = 0
                        for child in [parent, *parent.children(recursive=True)]:
                            try:
                                rss += child.memory_info().rss
                            except psutil.Error:
                                pass
                        peak = max(peak, rss)
                    except psutil.Error:
                        pass
                    try:
                        output_files = _files(workspace / "output")
                        size = sum(p.stat().st_size for p in output_files)
                        size += stdout.stat().st_size + stderr.stat().st_size
                        if size > request.policy.max_output_bytes:
                            status, error = "contract_error", "output_too_large"
                            break
                    except ValueError:
                        status, error = "contract_error", "unsafe_output"
                        break
                    exit_code = process.poll()
                    if exit_code is not None:
                        break
                    if time.monotonic() - started >= request.policy.timeout_seconds:
                        status, error = "timed_out", "timeout"
                        break
                    time.sleep(0.02)
                # Also reap descendants after parent exit to prevent background writers.
                _kill_group(process)
                if error is None:
                    if exit_code != 0:
                        error = f"runtime_exit_{exit_code}"
                    else:
                        result_file = workspace / "output/result.json"
                        if not result_file.is_file():
                            status, error = "contract_error", "missing_result"
                        else:
                            try:

                                def reject_constant(value):
                                    raise ValueError(value)

                                payload = json.loads(
                                    result_file.read_text(encoding="utf-8"),
                                    parse_constant=reject_constant,
                                )
                                if not isinstance(payload, dict):
                                    raise ValueError("result must be a JSON object")
                            except (ValueError, UnicodeError):
                                payload = {}
                                status, error = "contract_error", "invalid_result_json"
                            else:
                                status = "succeeded"
                                outputs = tuple(
                                    str(p.relative_to(workspace))
                                    for p in sorted(_files(workspace / "output"))
                                )
        except (OSError, ValueError):
            status, error, payload, outputs = "failed", "runtime_launch_or_io_error", {}, ()
        finally:
            if process is not None:
                _kill_group(process)
        result = ExecutionResult(
            action_run_id=request.action_run_id,
            status=status,
            exit_code=exit_code,
            wall_time_seconds=time.monotonic() - started,
            peak_memory_bytes=peak or None,
            stdout_artifact="logs/stdout.log",
            stderr_artifact="logs/stderr.log",
            output_artifacts=outputs,
            result_payload=payload,
            error_code=error,
        )
        temporary = workspace / "execution-result.tmp"
        temporary.write_text(json.dumps(result.model_dump(mode="json"), indent=2), encoding="utf-8")
        temporary.replace(workspace / "execution-result.json")
        return result
