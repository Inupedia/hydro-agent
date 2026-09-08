# Hydro-Agent Execution Sandbox Design

**Status:** design for review before implementation planning  
**Date:** 2026-09-08  
**Scope:** first executable vertical slice for Hydro-Agent  
**Related specs:** `docs/产品规格.md`, `docs/水文世界模型.md`, `docs/数据源与实验数据协议.md`, `docs/课题完整方案.md`

---

## 1. Problem

Hydro-Agent already defines the decision loop, hydrologic domain objects, evidence ledger, XAJ/OpenHydroNet model routes, optimization gates, and historical replay rules. The missing execution boundary is the layer that safely and reproducibly runs numerical hydrologic work.

Without an explicit execution boundary, tools such as `forecast`, `calibrate_model`, `adapt_model`, `rebuild_state`, and `evaluate` can accidentally:

- mutate the active Scheme in place;
- read data outside the task's approved `DataSnapshot`;
- leak future observations into historical replay;
- mix XAJ and OpenHydroNet runtime dependencies;
- leave incomplete artifacts after timeout or failure;
- lose CPU/RAM/MPS cost information;
- make rollback a logical flag instead of a physically isolated experiment.

This design adds an **Execution Sandbox** between Hydrology Tools and model-specific runtimes.

---

## 2. Goal

Build a local, auditable execution boundary in which every model/tool run receives frozen inputs, executes in an isolated workspace with bounded resources, writes immutable outputs, and returns a normalized result that can be converted into `EvidencePacket`, `ActionRun`, `CostLedger`, `Forecast`, or candidate `Scheme` records.

The first implementation must work on a single M1 Pro and must not require Kubernetes, Firecracker, gVisor, or distributed orchestration.

---

## 3. Non-goals

This subsystem does not:

- make Agent decisions;
- calculate NSE/KGE inside the LLM;
- implement XAJ hydrology itself;
- train a global OpenHydroNet model;
- provide arbitrary user code execution;
- provide a general-purpose secure multi-tenant cloud sandbox;
- auto-select models;
- introduce Docker as a mandatory dependency for the first milestone;
- introduce Neo4j/RDF/OWL as part of execution.

---

## 4. Approaches considered

### Approach A — direct in-process Python calls

`Tool -> Python function -> XAJ/OHN`

**Advantages:** smallest amount of code; fastest proof of model invocation.  
**Rejected as the product boundary:** one process can mutate shared memory/files, dependency failures can crash the API process, timeouts are harder to enforce, and historical replay data boundaries are weak.

### Approach B — local subprocess sandbox with isolated workspaces

`Tool -> Sandbox -> model-specific subprocess -> artifacts`

Each ActionRun receives its own working directory and an input manifest. The subprocess receives only declared paths/configuration and writes to a declared output directory. The parent process controls timeout, captures stdout/stderr, records resource use, validates the output contract, and never treats a partially written result as accepted.

**Advantages:** compatible with M1 Pro, low operational burden, strong enough isolation for a research/product prototype, easy to test, and naturally supports XAJ/OHN runtime separation.  
**Chosen.**

### Approach C — container/microVM sandbox

`Tool -> container/microVM -> model runtime`

**Advantages:** stronger operating-system isolation and reproducible packaged runtimes.  
**Deferred:** unnecessary for the single-user local milestone; Docker networking, image build/pull, ARM compatibility, and GPU/MPS handling add work that does not prove the research hypothesis.

The interfaces in this design must allow Approach B to be replaced by a container backend later without changing Agent or Hydrology Tool contracts.

---

## 5. Architectural position

```text
Hydro World State
       |
       v
Agent Runtime
       |
       v
Permission / Governance Gate
       |
       v
Hydrology Tool API
       |
       v
Execution Sandbox
   |           |
   v           v
XAJ Runtime   OpenHydroNet Runtime
   |           |
Optimizer     Trainer / Adapter
   \           /
    v         v
Artifacts + ExecutionResult
       |
       v
Evidence / Forecast / Candidate Scheme / Cost Ledger
       |
       v
Programmatic Gate
       |
       v
World State Update
```

The Agent never invokes model binaries or Python modules directly. The Agent selects an allowed business Action. A Hydrology Tool converts that Action into a typed sandbox request.

---

## 6. Component boundaries

### 6.1 `SandboxRunner`

Owns execution lifecycle only.

Responsibilities:

- create a unique workspace for one `action_run_id`;
- materialize declared input references into the workspace;
- write an immutable `execution-manifest.json`;
- launch the declared runtime adapter;
- enforce timeout;
- capture stdout/stderr and exit status;
- collect wall-clock and process resource metrics;
- validate required output files;
- return a normalized `ExecutionResult`;
- mark an incomplete run failed rather than promoting partial artifacts.

It does not know hydrologic model mathematics.

### 6.2 `RuntimeAdapter`

A model/runtime-specific boundary.

First adapters:

- `XajRuntimeAdapter`
- `OpenHydroNetRuntimeAdapter`

Common capabilities are declared in the model registry. Expected initial capability mapping:

| Runtime | Capabilities |
|---|---|
| XAJ | `validate`, `rebuild_state`, `forecast`, `calibrate` |
| OpenHydroNet | `validate`, `rebuild_state`, `forecast`, `adapt` |

Adapters translate a typed execution request into the concrete CLI/module invocation and normalize the result. They may use different Python environments.

### 6.3 `WorkspaceManager`

Defines layout and file lifecycle.

```text
.runs/{task_id}/{action_run_id}/
  execution-manifest.json
  input/
    snapshot/
    scheme/
  work/
  output/
  logs/
    stdout.log
    stderr.log
  execution-result.json
```

`input/` is read-only by contract. Runtime code may write only to `work/`, `output/`, and `logs/`.

### 6.4 `ArtifactStore`

Promotes successful output files from a sandbox run to immutable artifact references. A failed run may keep diagnostic logs but may not register a candidate Scheme or Forecast as valid.

First milestone storage can remain local filesystem + SQLite metadata.

### 6.5 `ExecutionPolicy`

Contains deterministic limits supplied by Task/Governance rather than LLM text.

Minimum fields:

- `timeout_seconds`
- `network_access: false` for numerical execution in milestone 1
- `max_output_bytes`
- `allowed_input_roots`
- `allowed_output_root`
- `device: cpu | mps`

Memory monitoring is recorded in milestone 1. Hard OS-level RAM enforcement is optional until a portable implementation is proven on macOS.

---

## 7. Core contracts

The following names are the design contract for implementation planning.

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

ExecutionCapability = Literal[
    "validate",
    "rebuild_state",
    "forecast",
    "calibrate",
    "adapt",
    "evaluate",
]

ExecutionStatus = Literal[
    "succeeded",
    "failed",
    "timed_out",
    "contract_error",
]

@dataclass(frozen=True)
class ExecutionPolicy:
    timeout_seconds: int
    network_access: bool
    max_output_bytes: int
    device: Literal["cpu", "mps"]

@dataclass(frozen=True)
class ExecutionRequest:
    task_id: str
    action_run_id: str
    model_id: str
    capability: ExecutionCapability
    data_snapshot_id: str
    scheme_id: str
    issue_time: str | None
    parameters: Mapping[str, object]
    policy: ExecutionPolicy

@dataclass(frozen=True)
class ExecutionResult:
    action_run_id: str
    status: ExecutionStatus
    exit_code: int | None
    wall_time_seconds: float
    peak_memory_bytes: int | None
    stdout_artifact: str
    stderr_artifact: str
    output_artifacts: tuple[str, ...]
    result_payload: Mapping[str, object]
    error_code: str | None
```

The implementation may use Pydantic instead of dataclasses, but field names and semantics must remain stable unless this spec is revised.

---

## 8. Data isolation and historical replay

The sandbox is also the enforcement point for `available_at <= issue_time`.

A run never receives a generic path such as a repository-wide data directory. Before execution, the data layer resolves `data_snapshot_id` to the exact files permitted for that run. `execution-manifest.json` records each file hash and logical role.

For `forcing_mode = F`:

- historical observations exposed to the runtime must be available by `issue_time`;
- future meteorological forcing must come from the forecast release valid at the issue time;
- future observed discharge is unavailable to `forecast`, `calibrate`, `adapt`, and state rebuild actions;
- future observed discharge becomes visible only to the read-only E-phase evaluator.

For `forcing_mode = R`, future reanalysis may be supplied only when the Task is explicitly marked R. The mode is recorded in the manifest and resulting evidence.

This means time leakage is rejected before model execution, not left to prompt instructions.

---

## 9. Scheme mutation and rollback

A registered Scheme is immutable.

Optimization/adaptation follows this flow:

```text
base Scheme
   |
   v
sandbox workspace copy/reference
   |
   v
calibrate/adapt
   |
   v
candidate artifacts
   |
   v
candidate Scheme record (status=candidate)
   |
   v
programmatic Gate
   |-----------------------|
 ACCEPT                   FAIL
   |                        |
   v                        v
new adopted/frozen       ROLLBACK
Scheme version           base Scheme unchanged
```

No optimizer writes back into the active Scheme directory. A Gate failure therefore requires no reverse mutation.

---

## 10. Failure semantics

Every execution must terminate in one normalized status.

- `succeeded`: process exited cleanly and output contract validation passed;
- `failed`: runtime intentionally returned a model/tool failure;
- `timed_out`: parent terminated the process after policy timeout;
- `contract_error`: process may have exited successfully but required output fields/files are missing, malformed, contain NaN/Inf where forbidden, or violate declared units/time metadata.

The Agent receives normalized Evidence, not raw exceptions. A repeated technical failure is still counted against the task retry budget defined by Governance.

---

## 11. Security boundary for milestone 1

This is not a hostile multi-tenant sandbox. The threat model is accidental leakage/mutation and runaway research code.

Milestone-1 controls:

- no arbitrary shell command supplied by the LLM;
- executable/runtime selected from a static registry;
- capability selected from a static enum;
- input paths resolved by trusted application code;
- separate action workspace;
- subprocess timeout;
- numerical subprocess launched with network disabled by application policy; if portable OS-level network blocking is not available on macOS, runtime adapters must not contain fetch/download behavior and tests must assert that all needed inputs are materialized before launch;
- output size validation;
- immutable promoted artifacts;
- complete manifest and logs.

A future container backend may harden filesystem/network boundaries without changing the request/result interface.

---

## 12. First vertical slice

The first executable milestone should prove the architecture with **one model first**, following the existing product rule: whichever model reaches a real forecast first becomes the first Adapter.

Recommended starting path: **XAJ first** if a stable implementation and parameter definition can be locked quickly, because it makes Scheme parameters, bounded calibration, rollback, and state reconstruction explicit and easy to audit. If OpenHydroNet's official inference path is materially faster to make real on the M1 Pro, the Adapter order may be swapped without architecture changes.

A milestone is complete only when one real `issue_time` produces lead 1/2/3 output through:

```text
DataSnapshot
-> ExecutionRequest
-> SandboxRunner
-> RuntimeAdapter
-> model execution
-> ExecutionResult
-> Forecast + Evidence + CostLedger
```

and the same frozen inputs reproduce the same result within the model's declared determinism tolerance.

---

## 13. Sub-project decomposition

This design is intentionally split so each implementation plan can yield testable software independently.

### SP1 — Execution contracts and local SandboxRunner

Deliverable: a runtime-agnostic sandbox that executes a controlled fixture command in an isolated workspace, enforces timeout, captures logs, validates artifacts, and returns `ExecutionResult`.

Depends on: none beyond Python application skeleton.  
Unlocks: every model adapter.

### SP2 — Task/Scheme/DataSnapshot/ActionRun persistence

Deliverable: SQLite-backed records sufficient to create an `ExecutionRequest`, trace its input hashes, and persist `ExecutionResult`, artifacts, and cost.

Depends on: stable contracts from SP1.  
Unlocks: auditable model runs and WorldStateView construction.

### SP3 — First real hydrologic RuntimeAdapter

Deliverable: either XAJ or OpenHydroNet performs one real lead-1/2/3 forecast through the SandboxRunner using one real DataSnapshot.

Depends on: SP1 + minimum SP2 identifiers/artifact persistence.  
Unlocks: C0/C3 real forecast acceptance.

### SP4 — Data snapshot materialization and F/R time boundary

Deliverable: approved snapshot files are materialized into the sandbox manifest; illegal future data is rejected before execution; R/F mode behavior has regression tests.

Depends on: SP1 + SP2.  
Can proceed in parallel with most of SP3 once fixture schemas are stable.

### SP5 — Candidate Scheme isolation + programmatic Gate

Deliverable: one bounded calibration/adaptation produces a candidate Scheme; Gate can ACCEPT/KEEP/ROLLBACK; a rejected candidate cannot mutate the base Scheme.

Depends on: SP3 + evaluator metrics + SP2 persistence.

### SP6 — Agent Runtime integration

Deliverable: Agent selects one allowed business Action, Permission Gate converts it into a Tool call, Tool executes via Sandbox, Evidence updates Task/World State, and a follow-up decision sees the new evidence.

Depends on: SP1-SP5 capability APIs being independently callable.  
This must not be implemented before those tools work without an LLM.

### SP7 — Freeze, historical replay, evaluate, report

Deliverable: freeze one accepted Scheme, replay sequential issue times without changing it, evaluate in read-only E phase, and generate traceable metrics/report artifacts.

Depends on: SP3-SP6 and strict data phase rules.

### SP8 — Workbench UI

Deliverable: task creation, runtime timeline, evidence/forecast inspection, pause/resume, final scheme/Gate/report view. No A01-A12 checkbox UI.

Depends on: stable backend state and event/read APIs.  
This is intentionally last among core engineering slices.

---

## 14. Testing strategy

Implementation plans must use TDD and small commits as required by the selected superpowers workflow.

Required test layers:

1. **Contract tests** — request/result validation, registry capabilities, manifest hashes.
2. **Sandbox unit tests** — success, non-zero exit, timeout, missing output, oversized output, logs.
3. **Persistence tests** — immutable Scheme/DataSnapshot references and ActionRun traceability.
4. **Time-leak regression tests** — F-mode future observations/late forcing are rejected.
5. **Runtime adapter tests** — model-specific input/output normalization.
6. **Integration test** — real single-basin lead 1/2/3 forecast end-to-end.
7. **Rollback test** — candidate changes but fails Gate; base Scheme hash remains unchanged.
8. **Agent-loop test** — one run creates Evidence that changes the next allowed/selected action.

Real-model integration tests may be marked separately from fast unit tests, but they must be runnable on the target M1 Pro environment.

---

## 15. Acceptance criteria for this architecture

The design is considered implemented only when all of the following are true:

- the Agent has no direct model-process execution path;
- every numerical run has a unique `action_run_id` and manifest;
- every runtime receives only declared snapshot/scheme inputs;
- base Schemes are immutable;
- failures/timeouts do not promote Forecast or candidate Scheme artifacts as successful;
- one real model completes lead 1/2/3 forecast through the sandbox;
- one optimization/adaptation candidate can fail Gate and roll back without mutating its base Scheme;
- resource and wall-clock cost are persisted;
- F-mode time-leak tests pass;
- model runtimes can be swapped through the Adapter/Registry boundary without changing Agent contracts.

---

## 16. Planning handoff

After this spec is reviewed and approved, create implementation plans under:

`docs/superpowers/plans/`

The first plan should be **SP1 — Execution contracts and local SandboxRunner**, not the entire Hydro-Agent system. Each plan must state exact files, interfaces, failing tests, commands, expected results, minimal implementation steps, and commit points. Subsequent plans proceed in dependency order, with SP3/SP4 parallelizable once SP1/SP2 contracts are stable.
