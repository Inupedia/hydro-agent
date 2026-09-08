# Hydro-Agent Superpowers Execution Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Do not implement by filename order alone; follow the dependency gates below.

**Goal:** Execute the Hydro-Agent plans in an order that always leaves a working, reviewable increment and never connects the Agent/UI before deterministic hydrology capabilities work independently.

**Design spec:** `docs/superpowers/specs/2026-09-08-execution-sandbox-design.md`

---

## 1. Plan Set

| Plan | Purpose | Primary acceptance |
|---|---|---|
| SP1 `2026-09-08-sp1-execution-sandbox-runner.md` | Execution contracts, registry, workspace, subprocess sandbox | fixture runtime success/failure/timeout/contracts |
| SP2 `2026-09-08-sp2-persistence-ledger.md` | Task/Scheme/Snapshot/ActionRun/Artifact/Cost persistence | immutable refs + atomic execution ledger |
| SP3 `2026-09-08-sp3-xaj-runtime-adapter.md` | First real hydrologic adapter: XAJ | real Lowman lead 1/2/3 forecast |
| SP4 `2026-09-08-sp4-data-snapshot-time-boundary.md` | DataSnapshot + F/R time boundary | R snapshot works; illegal F future data rejected |
| SP4A `2026-09-08-sp4a-hydrology-application-services.md` | Missing Tool/application service boundary | independently callable Forecast/Calibration services |
| SP5 `2026-09-08-sp5-candidate-scheme-gate.md` | Bounded calibration, candidate Scheme, Gate/rollback | candidate non-adoption leaves base hash unchanged |
| SP6 `2026-09-08-sp6-agent-runtime-integration.md` | WorldState -> Agent -> Permission -> Tool -> Evidence loop | round 2 sees round-1 evidence |
| SP7 `2026-09-08-sp7-freeze-replay-evaluate-report.md` | freeze/replay/read-only evaluate/report | same frozen Scheme across replay; report traceable |
| SP3B `2026-09-08-sp3b-openhydronet-runtime-adapter.md` | Second model adapter: OpenHydroNet | 3 leads + adaptation-module isolation |
| SP8 `2026-09-08-sp8-workbench-ui.md` | FastAPI + Vue workbench | Task -> Run -> Result browser flow |

SP4A and SP3B are deliberate additions discovered during plan self-review. The original design already requires Hydrology Tools and multiple RuntimeAdapters; these plans make those boundaries executable rather than implicit.

---

## 2. Exact Execution Order

### Gate A — Execution kernel

Execute completely:

```text
SP1
  -> SP2
```

Do not start real model work until:

```bash
uv run pytest tests/execution tests/persistence -v
```

passes.

### Gate B — First real hydrology capability

SP3 and SP4 have a controlled dependency handshake:

```text
SP3 Tasks 1-4       SP4 Tasks 1-5
       \              /
        \            /
         +----------+
              |
        SP4A Tasks 1-4
              |
        SP3 Task 5 real
```

Recommended sequence:

1. SP3 Tasks 1-4: lock XAJ, contracts, runtime, adapter.
2. SP4 Tasks 1-5: data policy, real Lowman R snapshot, F rejection.
3. SP4A Tasks 1-4: Forecast persistence, SnapshotResolver, materializer, ForecastService.
4. Return to SP3 Task 5 and prove the real Lowman forecast through the completed service/snapshot stack.

Gate command:

```bash
uv run pytest tests/models/xaj tests/data tests/services/test_forecast.py tests/services/test_snapshots.py tests/services/test_materialize.py -v
HYDRO_AGENT_LOWMAN_SNAPSHOT=... uv run pytest tests/integration/test_xaj_sandbox_forecast.py -v
```

The real XAJ forecast is the first milestone that proves the architecture is more than documentation.

### Gate C — Optimization + rollback

SP5 and SP4A CalibrationService interleave once:

```text
SP5 Tasks 1-4
      |
SP4A Task 5 CalibrationService
      |
SP5 Tasks 5-7
```

Reason: SP4A Task 5 needs the XAJ `calibrate` runtime created by SP5 Task 4, while SP5 candidate/Gate logic benefits from the application service being available before final integration.

Gate command:

```bash
uv run pytest tests/evaluation tests/optimization tests/models/xaj/test_calibrate_runtime.py tests/services/test_calibration.py -v
HYDRO_AGENT_LOWMAN_SNAPSHOT=... uv run pytest tests/integration/test_xaj_candidate_rollback.py -v
```

Do not connect an LLM before this Gate passes.

### Gate D — Agent loop

Execute SP6 completely.

Required proof:

```text
WorldStateView(t)
 -> AgentDecision
 -> PermissionGate
 -> ToolRouter
 -> ForecastService/Calibration/Gate
 -> EvidencePacket
 -> WorldStateView(t+1)
```

Gate command:

```bash
uv run pytest tests/agent tests/integration/test_agent_evidence_loop.py -v
```

The scripted provider must pass before the optional live LLM provider is used.

### Gate E — Frozen operational replay

Execute SP7 completely.

Gate command:

```bash
uv run pytest tests/replay tests/evaluation tests/reporting -v
HYDRO_AGENT_LOWMAN_SNAPSHOT=... uv run pytest tests/integration/test_frozen_historical_replay.py -v
```

Required invariants:

```text
frozen Scheme hash stable
same frozen Scheme for every replay issue
no calibrate/adapt after phase F
future truth visible only in phase E
report metrics come from persisted forecasts/truth
```

### Gate F — Second model Adapter

Execute SP3B after the XAJ Agent/replay path is stable. This intentionally prevents PyTorch/OpenHydroNet dependency work from blocking the first research demonstration.

Fast gate:

```bash
uv run pytest tests/models/openhydronet tests/optimization/test_ohn_strategies.py tests/data/test_openhydronet_snapshot.py -v
```

Real gate:

```bash
HYDRO_AGENT_OHN_BASE_RUN=... HYDRO_AGENT_OHN_LOWMAN_SNAPSHOT=... \
uv run pytest tests/integration/test_openhydronet_sandbox_forecast.py tests/integration/test_openhydronet_adaptation_isolation.py -v
```

Only after this Gate should `openhydronet` be advertised as an executable model in the workbench model list.

### Gate G — Workbench

Execute SP8 last.

Before browser work, all backend workflows must already be callable from tests/API services without UI.

Gate command:

```bash
uv run pytest tests/api -v
cd web
npm test -- --run
npm run build
npx playwright test
```

---

## 3. Dependency Graph

```text
SP1 Execution Sandbox
        |
        v
SP2 Persistence
        |
        +---------------------+
        |                     |
        v                     v
SP3 XAJ runtime           SP4 Data/time policy
        |                     |
        +----------+----------+
                   v
            SP4A Services (1-4)
                   |
                   v
            SP3 real forecast
                   |
                   v
             SP5 (Tasks 1-4)
                   |
                   v
          SP4A Calibration (5)
                   |
                   v
             SP5 (Tasks 5-7)
                   |
                   v
              SP6 Agent
                   |
                   v
              SP7 Replay
                   |
                   v
          SP3B OpenHydroNet
                   |
                   v
              SP8 UI
```

SP3B may be developed in parallel after SP5 if resources permit, but it must not change the XAJ-first acceptance path.

---

## 4. Commit and Review Discipline

Each checkbox task in every plan ends with its own commit. Do not squash tasks while executing because the plan expects review gates between self-contained changes.

Before each task:

```bash
git status --short
git log -5 --oneline
```

After each task:

```bash
# run the exact task test first
# then run the plan-local regression suite
git status --short
git diff --check
```

A task is complete only when its stated test passes. A plan is complete only when its Acceptance section passes.

---

## 5. Branch / Worktree Strategy

At implementation time use `superpowers:using-git-worktrees` for isolation. Recommended worktree/branch naming:

```text
feat/sp1-execution-sandbox
feat/sp2-persistence
feat/sp3-xaj
feat/sp4-data-boundary
feat/sp4a-services
feat/sp5-gate
feat/sp6-agent-runtime
feat/sp7-replay
feat/sp3b-openhydronet
feat/sp8-workbench
```

Do not execute all plans in the current design PR branch. PR #9 is the architecture/planning artifact; implementation should proceed as focused development branches/PRs so failures are reviewable and reversible.

---

## 6. Definition of the First Demonstrable Product

The first credible demo is reached after SP7, before SP3B/SP8 is strictly necessary:

```text
One Lowman Task
 -> legal DataSnapshot
 -> XAJ Sandbox forecast
 -> bounded calibration
 -> Gate rollback/keep/accept
 -> evidence-driven Agent follow-up
 -> frozen Scheme
 -> historical replay
 -> read-only NSE/KGE/MAE/Bias evaluation
 -> deterministic report
```

This is the minimum end-to-end proof of the research claim. OpenHydroNet proves the model abstraction is real rather than XAJ-specific; SP8 makes the system usable without the terminal.

---

## 7. Completion Checklist

- [x] SP1 acceptance passes. Local verification: 2026-09-08.
- [x] SP2 acceptance passes. Local verification: 2026-09-08.
- [x] SP3 real XAJ acceptance passes. Local verification: 2026-09-08.
- [x] SP4 F/R leakage regression passes. Local verification: 2026-09-08.
- [x] SP4A forecast/calibration services pass independently without Agent. Local verification: 2026-09-08.
- [x] SP5 real candidate rollback/immutability acceptance passes. Local verification: 2026-09-08.
- [ ] SP6 two-round evidence loop passes with scripted provider.
- [ ] SP7 freeze/replay/E-phase/report acceptance passes.
- [ ] SP3B real OpenHydroNet inference/adaptation isolation passes.
- [ ] SP8 API/unit/build/Playwright acceptance passes.
- [ ] Full fast test suite passes from repository root.
- [ ] All real-model tests record pinned upstream commits, input hashes, wall time, and peak memory.
- [ ] No Agent/UI path directly executes model subprocesses.
- [ ] No accepted historical F replay uses future observations or future reanalysis as forecast forcing.
