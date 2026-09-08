# SP6 Agent Runtime, Permission Gate, and Evidence Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first real Hydro-Agent control loop: build a bounded `WorldStateView`, ask a decision provider for exactly one business Action, enforce permissions/budget programmatically, execute an existing Tool through the sandbox/service layer, persist Evidence, update state, and let the next round see that new evidence.

**Architecture:** Agent reasoning is isolated behind a `DecisionProvider` protocol; the runtime accepts only structured `AgentDecision`. `PermissionGate` computes legal actions independently from the model. `ToolRouter` maps a legal business action to deterministic application services built in SP3-SP5. The LLM never receives model-process handles or filesystem paths and never invokes `SandboxRunner` directly.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy 2, pytest 8; optional OpenAI Python SDK using Responses structured parsing for the first live provider.

**Spec:** `docs/superpowers/specs/2026-09-08-execution-sandbox-design.md`

## Global Constraints

- Agent selects one main Action per decision round.
- Agent never directly executes XAJ/OpenHydroNet processes.
- Agent never calculates NSE/KGE or continuous model parameters.
- Permission, phase, model capability, retry, and budget rules are deterministic code.
- Default safety budgets from the product spec: max decision rounds 20, max optimization cycles 4, same technical failure retry <= 2.
- Optimization budget persists across rounds and process restarts.
- `ACCEPT`, `KEEP`, `ROLLBACK`, and `BLOCK` are valid outcomes.
- Repeated identical `hypothesis + action + strategy + base_scheme` without new evidence is rejected as a no-progress loop.
- Store concise decision rationale summaries, not hidden chain-of-thought.

---

## File Structure

```text
pyproject.toml
src/hydro_agent/agent/__init__.py
src/hydro_agent/agent/contracts.py
src/hydro_agent/agent/world_state.py
src/hydro_agent/agent/permissions.py
src/hydro_agent/agent/tools.py
src/hydro_agent/agent/runtime.py
src/hydro_agent/agent/providers/__init__.py
src/hydro_agent/agent/providers/scripted.py
src/hydro_agent/agent/providers/openai_responses.py
src/hydro_agent/persistence/models.py
src/hydro_agent/persistence/repository.py
tests/agent/test_world_state.py
tests/agent/test_permissions.py
tests/agent/test_tools.py
tests/agent/test_runtime.py
tests/agent/test_openai_provider.py
tests/integration/test_agent_evidence_loop.py
```

### Task 1: Define Action, Evidence, AgentDecision, and WorldStateView contracts

**Files:**
- Create: `src/hydro_agent/agent/__init__.py`
- Create: `src/hydro_agent/agent/contracts.py`
- Create: `src/hydro_agent/agent/world_state.py`
- Test: `tests/agent/test_world_state.py`

**Interfaces:**
- Produces: `ActionCode`, `ProblemHypothesis`, `EvidencePacket`, `AgentDecision`, `WorldStateView`, `WorldStateBuilder.build(task_id)`.

- [ ] **Step 1: Write failing world-state test**

```python
# tests/agent/test_world_state.py
from hydro_agent.agent.world_state import WorldStateBuilder


def test_world_state_contains_only_decision_relevant_projection(seeded_repository):
    view = WorldStateBuilder(seeded_repository).build("task-1")
    assert view.task.task_id == "task-1"
    assert view.model.model_id == "xaj"
    assert view.scheme.scheme_id == "scheme-base"
    assert view.permissions.safe_actions
    assert not hasattr(view, "database_url")
    assert not hasattr(view, "filesystem_root")
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/agent/test_world_state.py -v`

Expected: FAIL because agent package is missing.

- [ ] **Step 3: Implement exact structured types**

`ActionCode` enum values:

```text
A01_CHECK_DATA
A02_REPAIR_DATA
A03_VALIDATE_SCHEME
A04_REBUILD_STATE
A05_FORECAST
A06_DIAGNOSE
A07_OPTIMIZE
A08_GATE
A09_RESOLVE
A10_FREEZE
A11_REPLAY
A12_EVALUATE_REPORT
```

`ProblemHypothesis`: `DATA`, `TIMING`, `STATE`, `FORCING`, `MODEL`, `RESOURCE`, `UNKNOWN`.

`AgentDecision` fields:

```python
action: ActionCode
hypothesis: ProblemHypothesis
strategy_id: str | None
rationale_summary: str = Field(min_length=1, max_length=600)
```

`EvidencePacket` fields:

```python
evidence_id, task_id, action_run_id, action, status,
observations: tuple[str, ...], metrics: dict[str, float],
gates: dict[str, str], artifact_ids: tuple[str, ...],
new_information_hash: str
```

`WorldStateView` contains only Task/Basin/HydroState summary, model capabilities, current Scheme, latest forecast/evidence summaries, `safe_actions`, and remaining budgets.

- [ ] **Step 4: Run world-state tests**

Run: `uv run pytest tests/agent/test_world_state.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/agent tests/agent/test_world_state.py
git commit -m "feat: define agent decision world state"
```

### Task 2: Persist TaskState, Evidence, and AgentDecisionRun

**Files:**
- Modify: `src/hydro_agent/persistence/models.py`
- Modify: `src/hydro_agent/persistence/repository.py`
- Modify: `tests/agent/test_world_state.py`

**Interfaces:**
- Adds tables: `task_state`, `evidence`, `agent_decisions`.
- Produces repository methods: `get_task_state`, `update_task_state`, `add_evidence`, `list_evidence`, `record_agent_decision`.

- [ ] **Step 1: Write failing persistence-backed state test**

```python

def test_agent_budget_survives_repository_reopen(database, seeded_repository):
    seeded_repository.update_task_state(
        "task-1",
        current_scheme_id="scheme-base",
        agent_rounds_used=3,
        optimization_cycles_used=1,
        paused=False,
        needs_follow_up=True,
    )
    reopened = HydroRepository(database)
    state = reopened.get_task_state("task-1")
    assert state.agent_rounds_used == 3
    assert state.optimization_cycles_used == 1
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/agent/test_world_state.py::test_agent_budget_survives_repository_reopen -v`

Expected: FAIL.

- [ ] **Step 3: Add exact state/evidence rows**

`task_state` columns:

```text
task_id PK/FK
current_scheme_id FK
agent_rounds_used integer
optimization_cycles_used integer
paused boolean
needs_follow_up boolean
last_information_hash nullable
updated_at
```

`evidence` stores the complete serialized `EvidencePacket` plus `created_at`.

`agent_decisions` columns:

```text
decision_id PK, task_id FK, round_number, provider,
model, world_state_hash, action, hypothesis, strategy_id nullable,
rationale_summary, input_tokens nullable, output_tokens nullable, created_at
```

No raw chain-of-thought field exists.

- [ ] **Step 4: Run state tests**

Run: `uv run pytest tests/agent/test_world_state.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/persistence tests/agent/test_world_state.py
git commit -m "feat: persist agent task state and evidence"
```

### Task 3: Implement PermissionGate and no-progress/budget rules

**Files:**
- Create: `src/hydro_agent/agent/permissions.py`
- Test: `tests/agent/test_permissions.py`

**Interfaces:**
- Produces: `PermissionGate.safe_actions(view)`, `PermissionGate.authorize(view, decision)`.

- [ ] **Step 1: Write failing permission tests**

```python
# tests/agent/test_permissions.py
import pytest
from hydro_agent.agent.permissions import PermissionGate, PermissionDenied


def test_agent_cannot_optimize_after_budget_exhausted(world_view):
    exhausted = world_view.model_copy(update={"budget": {"agent_rounds_remaining": 10, "optimization_cycles_remaining": 0}})
    assert "A07_OPTIMIZE" not in PermissionGate().safe_actions(exhausted)


def test_agent_cannot_evaluate_in_build_phase(world_view, evaluate_decision):
    with pytest.raises(PermissionDenied, match="phase"):
        PermissionGate().authorize(world_view, evaluate_decision)


def test_identical_no_progress_decision_is_rejected(no_progress_view, repeated_decision):
    with pytest.raises(PermissionDenied, match="no new evidence"):
        PermissionGate().authorize(no_progress_view, repeated_decision)
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/agent/test_permissions.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement deterministic permission matrix**

Build phase B allows A01-A10 subject to implemented tool/model capabilities. F phase allows A01, A03-A05, A09, A11 and forbids optimization/mutation. E phase allows only A12 plus read-only inspection.

Additional rules:

```text
agent_rounds_remaining <= 0 -> no action except A09_RESOLVE
optimization_cycles_remaining <= 0 -> remove A07_OPTIMIZE
model lacks calibrate/adapt -> remove A07_OPTIMIZE
paused -> no executable action
same technical failure retry > 2 -> block same action
same hypothesis/action/strategy/base + same information hash -> reject
```

- [ ] **Step 4: Run permission tests**

Run: `uv run pytest tests/agent/test_permissions.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/agent/permissions.py tests/agent/test_permissions.py
git commit -m "feat: enforce agent action permissions"
```

### Task 4: Implement ToolRouter that calls application services, never model processes

**Files:**
- Create: `src/hydro_agent/agent/tools.py`
- Test: `tests/agent/test_tools.py`

**Interfaces:**
- Produces: `ToolHandler.execute(task_id, decision) -> EvidencePacket`, `ToolRouter.register(action, handler)`, `ToolRouter.execute(...)`.

- [ ] **Step 1: Write failing routing test**

```python
# tests/agent/test_tools.py

def test_forecast_action_calls_forecast_service_not_sandbox_directly(tool_router, forecast_decision, spy_forecast_service):
    evidence = tool_router.execute("task-1", forecast_decision)
    assert spy_forecast_service.calls == 1
    assert evidence.action == "A05_FORECAST"
    assert evidence.status == "succeeded"
```

Add a test that unknown/unregistered action raises `ToolUnavailable` and does not fall back to shell/function-name reflection.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/agent/test_tools.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement explicit handlers**

Initial handlers wrap existing deterministic services:

```text
A01_CHECK_DATA -> SP4 snapshot/data validation service
A03_VALIDATE_SCHEME -> model registry + scheme contract validation
A05_FORECAST -> SP3 forecast application service -> SandboxRunner
A07_OPTIMIZE -> SP5 calibration application service -> SandboxRunner
A08_GATE -> SP5 GateEvaluator
A09_RESOLVE -> state terminal/keep/rollback resolver
```

A02/A04/A06/A10-A12 remain registered only when their later service exists; an unavailable action must not appear in `safe_actions`.

Normalize every handler result into one `EvidencePacket` and persist it through SP2/SP6 repository methods.

- [ ] **Step 4: Run routing tests**

Run: `uv run pytest tests/agent/test_tools.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/agent/tools.py tests/agent/test_tools.py
git commit -m "feat: route agent actions through hydrology tools"
```

### Task 5: Implement one-round and follow-up AgentRuntime with a scripted provider

**Files:**
- Create: `src/hydro_agent/agent/providers/__init__.py`
- Create: `src/hydro_agent/agent/providers/scripted.py`
- Create: `src/hydro_agent/agent/runtime.py`
- Test: `tests/agent/test_runtime.py`
- Create: `tests/integration/test_agent_evidence_loop.py`

**Interfaces:**
- Produces: `DecisionProvider.decide(view) -> AgentDecision`, `AgentRuntime.run_round(task_id)`, `AgentRuntime.run_until_terminal(task_id)`.

- [ ] **Step 1: Write failing two-round evidence test**

```python
# tests/integration/test_agent_evidence_loop.py

def test_new_evidence_changes_next_decision(agent_runtime, scripted_provider, repository):
    scripted_provider.queue([
        AgentDecision(action="A05_FORECAST", hypothesis="MODEL", strategy_id=None, rationale_summary="Run the base forecast."),
        AgentDecision(action="A07_OPTIMIZE", hypothesis="MODEL", strategy_id="xaj-bounded-v1", rationale_summary="Forecast evidence supports a bounded model test."),
    ])
    first = agent_runtime.run_round("task-1")
    second = agent_runtime.run_round("task-1")
    assert first.evidence_id != second.evidence_id
    assert repository.list_evidence("task-1")[-1].action == "A07_OPTIMIZE"
    assert scripted_provider.seen_views[1].evidence_summary != scripted_provider.seen_views[0].evidence_summary
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/integration/test_agent_evidence_loop.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement runtime order exactly**

```text
LOAD_STATE
-> BUILD_WORLD_STATE_VIEW
-> provider.decide(view)
-> PERMISSION_GATE.authorize
-> TOOL_ROUTER.execute
-> persist Evidence
-> increment agent_rounds_used
-> increment optimization_cycles_used only for A07
-> update last_information_hash
-> compute needs_follow_up
-> return Evidence
```

`run_until_terminal()` loops only while `needs_follow_up`, not paused, not terminal, and round budget remains. It never recursively calls itself.

- [ ] **Step 4: Run runtime and integration tests**

Run: `uv run pytest tests/agent/test_runtime.py tests/integration/test_agent_evidence_loop.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/agent/providers src/hydro_agent/agent/runtime.py tests/agent/test_runtime.py tests/integration/test_agent_evidence_loop.py
git commit -m "feat: add evidence-driven agent runtime"
```

### Task 6: Add an optional live structured decision provider

**Files:**
- Modify: `pyproject.toml`
- Create: `src/hydro_agent/agent/providers/openai_responses.py`
- Create: `tests/agent/test_openai_provider.py`

**Interfaces:**
- Produces: `OpenAIResponsesDecisionProvider(model).decide(view) -> AgentDecision`.

- [ ] **Step 1: Write failing provider test with a fake client**

```python
# tests/agent/test_openai_provider.py

def test_provider_uses_structured_agent_decision(fake_openai_client, world_view):
    provider = OpenAIResponsesDecisionProvider(model="test-model", client=fake_openai_client)
    decision = provider.decide(world_view)
    assert decision.action == "A05_FORECAST"
    call = fake_openai_client.responses.calls[0]
    assert call["text_format"] is AgentDecision
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/agent/test_openai_provider.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement using Responses structured parsing**

Add optional dependency:

```toml
agent-openai = ["openai>=1"]
```

Implementation shape:

```python
response = self.client.responses.parse(
    model=self.model,
    input=[
        {"role": "system", "content": SYSTEM_INSTRUCTIONS},
        {"role": "user", "content": view.model_dump_json()},
    ],
    text_format=AgentDecision,
)
decision = response.output_parsed
```

System instructions say: choose exactly one action from `safe_actions`; never invent parameter vectors; `strategy_id` must be null unless the chosen action requires a listed strategy; return a concise rationale summary only.

Do not hard-code a production model name. Require `HYDRO_AGENT_LLM_MODEL` for live execution and `OPENAI_API_KEY` through the SDK environment path.

- [ ] **Step 4: Run mocked provider tests**

Run: `uv run pytest tests/agent/test_openai_provider.py -v`

Expected: PASS without network access.

Optional live smoke test:

```bash
HYDRO_AGENT_LLM_MODEL=<configured-model> OPENAI_API_KEY=... \
uv run python -m hydro_agent.agent.providers.openai_responses --smoke
```

Expected: one schema-valid `AgentDecision`; no Tool is executed by the smoke command.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/hydro_agent/agent/providers/openai_responses.py tests/agent/test_openai_provider.py
git commit -m "feat: add structured agent decision provider"
```

## SP6 Acceptance

```bash
uv run pytest tests/agent tests/integration/test_agent_evidence_loop.py -v
```

Acceptance requires a two-round trace where round 2 sees round-1 Evidence, permission violations are rejected before tool execution, budgets persist across repository reopen, and there is no Agent-to-model-process call path.