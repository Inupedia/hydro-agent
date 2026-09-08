# SP1 Execution Contracts and Local SandboxRunner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runtime-agnostic local execution sandbox that launches only registered runtimes in per-action workspaces, enforces timeout/output contracts, captures logs/resource cost, and returns a normalized `ExecutionResult`.

**Architecture:** Python application code owns contracts, registry, workspace lifecycle, and subprocess supervision. Model-specific code implements a `RuntimeAdapter` protocol that returns an argv list; the LLM never supplies shell text. Every run writes a manifest before launch and a result document after launch.

**Tech Stack:** Python 3.12, uv, Pydantic 2, psutil, pytest 8.

**Spec:** `docs/superpowers/specs/2026-09-08-execution-sandbox-design.md`

## Global Constraints

- First milestone must work on one M1 Pro.
- No Kubernetes, Firecracker, gVisor, Docker requirement, or distributed orchestration.
- No arbitrary shell command supplied by the LLM.
- Executable/runtime is selected from a static registry.
- Capability is selected from a static enum.
- Each `action_run_id` receives a unique workspace.
- `input/` is read-only by contract; runtime writes only to `work/`, `output/`, and `logs/`.
- Every execution terminates as `succeeded`, `failed`, `timed_out`, or `contract_error`.
- Partial or malformed outputs are never promoted as successful results.
- Numerical runtime network policy is `false` for milestone 1; portable OS-level network blocking is not required on macOS.

---

## File Structure

```text
pyproject.toml
src/hydro_agent/__init__.py
src/hydro_agent/execution/__init__.py
src/hydro_agent/execution/contracts.py
src/hydro_agent/execution/adapter.py
src/hydro_agent/execution/registry.py
src/hydro_agent/execution/workspace.py
src/hydro_agent/execution/runner.py
src/hydro_agent/execution/hashing.py
tests/execution/test_contracts.py
tests/execution/test_registry.py
tests/execution/test_workspace.py
tests/execution/test_runner.py
tests/fixtures/fake_runtime.py
```

### Task 1: Bootstrap the Python package and frozen execution contracts

**Files:**
- Create: `pyproject.toml`
- Create: `src/hydro_agent/__init__.py`
- Create: `src/hydro_agent/execution/__init__.py`
- Create: `src/hydro_agent/execution/contracts.py`
- Test: `tests/execution/test_contracts.py`

**Interfaces:**
- Consumes: none.
- Produces: `ExecutionCapability`, `ExecutionStatus`, `ExecutionPolicy`, `ExecutionRequest`, `ExecutionResult`.

- [ ] **Step 1: Write the failing contract test**

```python
# tests/execution/test_contracts.py
from pydantic import ValidationError
import pytest

from hydro_agent.execution.contracts import ExecutionPolicy, ExecutionRequest


def test_execution_request_is_frozen_and_rejects_unknown_capability():
    request = ExecutionRequest(
        task_id="task-1",
        action_run_id="run-1",
        model_id="fixture",
        capability="forecast",
        data_snapshot_id="snapshot-1",
        scheme_id="scheme-1",
        issue_time="2026-01-01T00:00:00Z",
        parameters={},
        policy=ExecutionPolicy(
            timeout_seconds=10,
            network_access=False,
            max_output_bytes=1024,
            device="cpu",
        ),
    )
    with pytest.raises(ValidationError):
        request.capability = "shell"  # type: ignore[misc]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/execution/test_contracts.py -v`

Expected: FAIL because `hydro_agent.execution.contracts` does not exist.

- [ ] **Step 3: Add package metadata and the exact contracts**

```toml
# pyproject.toml
[project]
name = "hydro-agent"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "pydantic>=2.11,<3",
  "psutil>=6.1,<8",
]

[project.optional-dependencies]
dev = ["pytest>=8.3,<9"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```python
# src/hydro_agent/execution/contracts.py
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

ExecutionCapability = Literal[
    "validate", "rebuild_state", "forecast", "calibrate", "adapt", "evaluate"
]
ExecutionStatus = Literal["succeeded", "failed", "timed_out", "contract_error"]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExecutionPolicy(FrozenModel):
    timeout_seconds: int = Field(gt=0)
    network_access: bool
    max_output_bytes: int = Field(gt=0)
    device: Literal["cpu", "mps"]


class ExecutionRequest(FrozenModel):
    task_id: str
    action_run_id: str
    model_id: str
    capability: ExecutionCapability
    data_snapshot_id: str
    scheme_id: str
    issue_time: str | None
    parameters: dict[str, object]
    policy: ExecutionPolicy


class ExecutionResult(FrozenModel):
    action_run_id: str
    status: ExecutionStatus
    exit_code: int | None
    wall_time_seconds: float = Field(ge=0)
    peak_memory_bytes: int | None
    stdout_artifact: str
    stderr_artifact: str
    output_artifacts: tuple[str, ...]
    result_payload: dict[str, object]
    error_code: str | None
```

- [ ] **Step 4: Run the contract tests**

Run: `uv sync --extra dev && uv run pytest tests/execution/test_contracts.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/hydro_agent tests/execution/test_contracts.py
git commit -m "feat: add execution contracts"
```

### Task 2: Add the runtime adapter protocol and static registry

**Files:**
- Create: `src/hydro_agent/execution/adapter.py`
- Create: `src/hydro_agent/execution/registry.py`
- Test: `tests/execution/test_registry.py`

**Interfaces:**
- Consumes: `ExecutionRequest` from Task 1.
- Produces: `RuntimeAdapter.command(request, workspace) -> list[str]`, `RuntimeRegistry.register()`, `RuntimeRegistry.get()`.

- [ ] **Step 1: Write failing registry tests**

```python
# tests/execution/test_registry.py
from pathlib import Path
import pytest

from hydro_agent.execution.adapter import RuntimeAdapter
from hydro_agent.execution.registry import RuntimeRegistry


class FixtureAdapter:
    model_id = "fixture"
    capabilities = frozenset({"forecast"})

    def command(self, request, workspace: Path) -> list[str]:
        return ["python", "fixture.py"]


def test_registry_rejects_duplicate_model_id():
    registry = RuntimeRegistry()
    registry.register(FixtureAdapter())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FixtureAdapter())


def test_registry_rejects_unsupported_capability():
    registry = RuntimeRegistry()
    registry.register(FixtureAdapter())
    with pytest.raises(ValueError, match="does not support"):
        registry.get("fixture", "adapt")
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/execution/test_registry.py -v`

Expected: FAIL because registry modules are missing.

- [ ] **Step 3: Implement adapter protocol and registry**

```python
# src/hydro_agent/execution/adapter.py
from pathlib import Path
from typing import Protocol

from .contracts import ExecutionCapability, ExecutionRequest


class RuntimeAdapter(Protocol):
    model_id: str
    capabilities: frozenset[ExecutionCapability]

    def command(self, request: ExecutionRequest, workspace: Path) -> list[str]: ...
```

```python
# src/hydro_agent/execution/registry.py
from .adapter import RuntimeAdapter
from .contracts import ExecutionCapability


class RuntimeRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, RuntimeAdapter] = {}

    def register(self, adapter: RuntimeAdapter) -> None:
        if adapter.model_id in self._adapters:
            raise ValueError(f"model {adapter.model_id} already registered")
        self._adapters[adapter.model_id] = adapter

    def get(self, model_id: str, capability: ExecutionCapability) -> RuntimeAdapter:
        adapter = self._adapters[model_id]
        if capability not in adapter.capabilities:
            raise ValueError(f"model {model_id} does not support {capability}")
        return adapter
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/execution/test_registry.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/execution/adapter.py src/hydro_agent/execution/registry.py tests/execution/test_registry.py
git commit -m "feat: add runtime adapter registry"
```

### Task 3: Create deterministic workspaces, hashes, and manifests

**Files:**
- Create: `src/hydro_agent/execution/hashing.py`
- Create: `src/hydro_agent/execution/workspace.py`
- Test: `tests/execution/test_workspace.py`

**Interfaces:**
- Consumes: `ExecutionRequest`.
- Produces: `WorkspaceManager.create(request) -> Path`, `WorkspaceManager.materialize_file(...)`, `sha256_file(path)`.

- [ ] **Step 1: Write a failing workspace test**

```python
# tests/execution/test_workspace.py
import json
from pathlib import Path

from hydro_agent.execution.workspace import WorkspaceManager


def test_workspace_has_expected_layout_and_manifest(tmp_path, execution_request):
    manager = WorkspaceManager(tmp_path / ".runs")
    workspace = manager.create(execution_request)
    assert (workspace / "input").is_dir()
    assert (workspace / "work").is_dir()
    assert (workspace / "output").is_dir()
    assert (workspace / "logs").is_dir()
    manifest = json.loads((workspace / "execution-manifest.json").read_text())
    assert manifest["action_run_id"] == "run-1"
    assert manifest["policy"]["network_access"] is False
```

Add `tests/conftest.py` with a reusable `execution_request` fixture containing the Task 1 request.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/execution/test_workspace.py -v`

Expected: FAIL because `WorkspaceManager` is missing.

- [ ] **Step 3: Implement hashing and workspace creation**

```python
# src/hydro_agent/execution/hashing.py
from hashlib import sha256
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

```python
# src/hydro_agent/execution/workspace.py
import json
import os
import shutil
from pathlib import Path

from .contracts import ExecutionRequest
from .hashing import sha256_file


class WorkspaceManager:
    def __init__(self, root: Path) -> None:
        self.root = root

    def create(self, request: ExecutionRequest) -> Path:
        workspace = self.root / request.task_id / request.action_run_id
        if workspace.exists():
            raise FileExistsError(workspace)
        for name in ("input", "work", "output", "logs"):
            (workspace / name).mkdir(parents=True, exist_ok=False if name == "input" else True)
        (workspace / "execution-manifest.json").write_text(
            json.dumps(request.model_dump(mode="json"), indent=2, sort_keys=True)
        )
        return workspace

    def materialize_file(self, source: Path, destination: Path) -> dict[str, object]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        os.chmod(destination, 0o444)
        return {"path": str(destination), "sha256": sha256_file(destination), "bytes": destination.stat().st_size}
```

- [ ] **Step 4: Run workspace tests**

Run: `uv run pytest tests/execution/test_workspace.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/execution/hashing.py src/hydro_agent/execution/workspace.py tests/conftest.py tests/execution/test_workspace.py
git commit -m "feat: add execution workspaces and manifests"
```

### Task 4: Supervise a registered subprocess and normalize success/failure

**Files:**
- Create: `src/hydro_agent/execution/runner.py`
- Create: `tests/fixtures/fake_runtime.py`
- Test: `tests/execution/test_runner.py`

**Interfaces:**
- Consumes: `ExecutionRequest`, `RuntimeRegistry`, `WorkspaceManager`.
- Produces: `SandboxRunner.run(request) -> ExecutionResult`.

- [ ] **Step 1: Write failing success and non-zero-exit tests**

```python
# tests/execution/test_runner.py
from hydro_agent.execution.runner import SandboxRunner


def test_runner_captures_success_and_logs(runner, execution_request):
    result = runner.run(execution_request)
    assert result.status == "succeeded"
    assert result.exit_code == 0
    assert result.result_payload == {"value": 42}


def test_runner_normalizes_nonzero_exit(runner, failed_execution_request):
    result = runner.run(failed_execution_request)
    assert result.status == "failed"
    assert result.exit_code == 7
    assert result.error_code == "runtime_exit_7"
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/execution/test_runner.py -k 'success or nonzero' -v`

Expected: FAIL because `SandboxRunner` does not exist.

- [ ] **Step 3: Add the fixture runtime**

```python
# tests/fixtures/fake_runtime.py
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", required=True)
parser.add_argument("--mode", choices=["success", "fail", "sleep", "missing"], default="success")
args = parser.parse_args()
workspace = Path(args.workspace)

if args.mode == "fail":
    raise SystemExit(7)
if args.mode == "sleep":
    import time
    time.sleep(5)
if args.mode == "success":
    (workspace / "output" / "result.json").write_text(json.dumps({"value": 42}))
print("fixture-runtime-finished")
```

- [ ] **Step 4: Implement minimal subprocess supervision**

`SandboxRunner.run()` must:

1. get the adapter from `RuntimeRegistry`;
2. create the workspace;
3. call `adapter.command()` and pass the argv list to `subprocess.Popen(..., shell=False)`;
4. redirect stdout/stderr to `logs/stdout.log` and `logs/stderr.log`;
5. wait with `timeout=request.policy.timeout_seconds`;
6. load `output/result.json` only after exit code 0;
7. return `ExecutionResult` with artifact paths relative to the workspace.

Use this signature:

```python
class SandboxRunner:
    def __init__(self, registry: RuntimeRegistry, workspaces: WorkspaceManager) -> None: ...
    def run(self, request: ExecutionRequest) -> ExecutionResult: ...
```

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest tests/execution/test_runner.py -k 'success or nonzero' -v`

Expected: PASS.

```bash
git add src/hydro_agent/execution/runner.py tests/fixtures/fake_runtime.py tests/execution/test_runner.py
git commit -m "feat: execute registered runtimes in sandbox"
```

### Task 5: Enforce timeout, output-size, and output-contract failures

**Files:**
- Modify: `src/hydro_agent/execution/runner.py`
- Modify: `tests/fixtures/fake_runtime.py`
- Modify: `tests/execution/test_runner.py`

**Interfaces:**
- Consumes: Task 4 `SandboxRunner.run()`.
- Produces: deterministic `timed_out` and `contract_error` states.

- [ ] **Step 1: Add failing timeout and missing-result tests**

```python
def test_runner_kills_process_on_timeout(timeout_runner, timeout_request):
    result = timeout_runner.run(timeout_request)
    assert result.status == "timed_out"
    assert result.error_code == "timeout"


def test_runner_rejects_missing_result_json(missing_result_runner, missing_result_request):
    result = missing_result_runner.run(missing_result_request)
    assert result.status == "contract_error"
    assert result.error_code == "missing_result"
```

Also add a fixture mode that writes a file larger than `max_output_bytes` and assert `error_code == "output_too_large"`.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/execution/test_runner.py -k 'timeout or missing or large' -v`

Expected: FAIL.

- [ ] **Step 3: Implement the guards**

In `SandboxRunner.run()`:

```python
try:
    exit_code = process.wait(timeout=request.policy.timeout_seconds)
except subprocess.TimeoutExpired:
    process.kill()
    process.wait()
    return self._result(request, workspace, "timed_out", None, "timeout")
```

After clean exit, calculate the recursive byte size of `output/`. If it exceeds `max_output_bytes`, return `contract_error/output_too_large`. If `output/result.json` is absent or invalid JSON, return `contract_error/missing_result` or `contract_error/invalid_result_json`.

- [ ] **Step 4: Run the full runner test file**

Run: `uv run pytest tests/execution/test_runner.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/execution/runner.py tests/fixtures/fake_runtime.py tests/execution/test_runner.py
git commit -m "feat: enforce sandbox execution limits"
```

### Task 6: Record peak memory, wall time, and durable execution-result.json

**Files:**
- Modify: `src/hydro_agent/execution/runner.py`
- Modify: `tests/execution/test_runner.py`

**Interfaces:**
- Consumes: supervised process from Tasks 4-5.
- Produces: populated `wall_time_seconds`, `peak_memory_bytes`, and `execution-result.json` for every terminal state.

- [ ] **Step 1: Add failing metrics/result-file test**

```python
def test_runner_persists_cost_and_terminal_result(runner, execution_request):
    result = runner.run(execution_request)
    assert result.wall_time_seconds > 0
    assert result.peak_memory_bytes is None or result.peak_memory_bytes > 0
    result_path = runner.workspaces.root / "task-1" / "run-1" / "execution-result.json"
    assert result_path.exists()
    assert '"status": "succeeded"' in result_path.read_text()
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/execution/test_runner.py::test_runner_persists_cost_and_terminal_result -v`

Expected: FAIL because result persistence/metrics are incomplete.

- [ ] **Step 3: Implement resource sampling and final persistence**

Use `time.monotonic()` for wall time. While the child is alive, sample `psutil.Process(pid).memory_info().rss` every 50 ms in a daemon thread and keep the maximum. Serialize the final `ExecutionResult.model_dump(mode="json")` to `execution-result.json` before returning.

- [ ] **Step 4: Run all SP1 tests**

Run: `uv run pytest tests/execution -v`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/execution/runner.py tests/execution/test_runner.py
git commit -m "feat: persist sandbox execution cost"
```

## SP1 Acceptance

Run:

```bash
uv sync --extra dev
uv run pytest tests/execution -v
```

The slice is accepted only if success, non-zero exit, timeout, missing output, invalid output size, registry capability rejection, manifest creation, and cost persistence all pass without any direct shell-text execution path.