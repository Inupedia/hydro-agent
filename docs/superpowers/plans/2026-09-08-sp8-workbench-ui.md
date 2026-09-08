# SP8 Workbench API and Vue UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first usable Hydro-Agent workbench with task creation, run/pause/resume controls, an evidence-driven runtime timeline, forecast/gate/scheme inspection, and final report viewing without exposing A01-A12 as user-operated checkboxes.

**Architecture:** A small FastAPI application exposes stable application APIs backed by SP2/SP6/SP7 services. A single-process `TaskExecutor` owns at most one local worker on the M1 Pro and calls `AgentRuntime.run_until_terminal()`; process restart does not fake progress because TaskState is persisted. The Vue 3 frontend polls read APIs instead of introducing WebSockets. The UI has exactly three primary routes: Tasks, Run, Results.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, pytest 8; Vue 3, TypeScript, Vite, Pinia, Vue Router, ECharts, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-08-execution-sandbox-design.md`

## Global Constraints

- The first UI has exactly three primary pages: Task, Run, Result.
- Do not render A01-A12 as checkboxes, wizard steps, or manual action selectors.
- Business timeline wording is primary; action/evidence IDs are secondary expandable detail.
- API values come from the same persisted records used by Agent/Gate/Report; no duplicated metric calculations in the browser.
- Local execution is single-task/single-worker for milestone 1.
- Pause/resume changes TaskState; it does not kill a currently executing numerical subprocess mid-call unless SandboxRunner timeout/failure does so.
- UI polls read APIs; no WebSocket/SSE requirement for milestone 1.
- Result charts display persisted forecasts/observations and never alter them.
- Frontend never receives filesystem paths to sandbox workspaces.
- API never accepts arbitrary ActionCode execution from the browser.

---

## File Structure

```text
pyproject.toml
src/hydro_agent/api/__init__.py
src/hydro_agent/api/app.py
src/hydro_agent/api/deps.py
src/hydro_agent/api/schemas.py
src/hydro_agent/api/routes/tasks.py
src/hydro_agent/api/routes/runs.py
src/hydro_agent/api/routes/results.py
src/hydro_agent/api/executor.py
tests/api/test_tasks.py
tests/api/test_runs.py
tests/api/test_results.py
tests/api/test_executor.py
web/package.json
web/tsconfig.json
web/vite.config.ts
web/src/main.ts
web/src/App.vue
web/src/router.ts
web/src/api/client.ts
web/src/stores/tasks.ts
web/src/stores/run.ts
web/src/stores/results.ts
web/src/views/TaskView.vue
web/src/views/RunView.vue
web/src/views/ResultView.vue
web/src/components/BusinessTimeline.vue
web/src/components/ForecastChart.vue
web/src/components/GateSummary.vue
web/src/components/SchemeSummary.vue
web/src/components/ReportLinks.vue
web/src/types/api.ts
web/src/__tests__/TaskView.test.ts
web/src/__tests__/RunView.test.ts
web/src/__tests__/ResultView.test.ts
web/e2e/workbench.spec.ts
```

### Task 1: Bootstrap FastAPI and exact workbench response contracts

**Files:**
- Modify: `pyproject.toml`
- Create: `src/hydro_agent/api/__init__.py`
- Create: `src/hydro_agent/api/app.py`
- Create: `src/hydro_agent/api/deps.py`
- Create: `src/hydro_agent/api/schemas.py`
- Test: `tests/api/test_tasks.py`

**Interfaces:**
- Produces: `create_app()`, `TaskSummary`, `RunSummary`, `TimelineItem`, `ResultSummary`.

- [ ] **Step 1: Write failing app/health contract test**

```python
# tests/api/test_tasks.py
from fastapi.testclient import TestClient
from hydro_agent.api.app import create_app


def test_health_and_openapi_boot(app_dependencies):
    client = TestClient(create_app(app_dependencies))
    assert client.get("/api/health").json() == {"status": "ok"}
    schema = client.get("/openapi.json").json()
    assert "/api/tasks" in schema["paths"]
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/api/test_tasks.py::test_health_and_openapi_boot -v`

Expected: FAIL because API package does not exist.

- [ ] **Step 3: Add dependencies and exact schemas**

Add:

```toml
"fastapi>=0.116,<1",
"uvicorn>=0.35,<1",
"httpx>=0.28,<1",
```

Define frozen Pydantic schemas:

```python
class TaskCreateRequest(BaseModel):
    basin_id: str
    model_id: Literal["xaj", "openhydronet"]
    start_date: date
    end_date: date
    forcing_mode: Literal["R", "F"]
    base_scheme_id: str
    allow_optimization: bool
    max_agent_decision_rounds: int = Field(ge=1, le=20)
    max_optimization_cycles: int = Field(ge=0, le=4)

class TaskSummary(BaseModel):
    task_id: str
    basin_id: str
    model_id: str
    phase: Literal["B", "F", "E"]
    status: str
    paused: bool
    current_scheme_id: str | None
    agent_rounds_used: int
    optimization_cycles_used: int

class TimelineItem(BaseModel):
    id: str
    occurred_at: datetime
    label: str
    status: str
    action: str | None
    evidence_id: str | None
    details: dict[str, object]
```

`create_app()` takes an injected dependency container for repository/runtime services so tests do not use global state.

- [ ] **Step 4: Run API bootstrap test**

Run: `uv sync --extra dev && uv run pytest tests/api/test_tasks.py::test_health_and_openapi_boot -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/hydro_agent/api tests/api/test_tasks.py
git commit -m "feat: bootstrap workbench API"
```

### Task 2: Implement task create/list/detail APIs without manual action execution

**Files:**
- Create: `src/hydro_agent/api/routes/tasks.py`
- Modify: `src/hydro_agent/api/app.py`
- Modify: `tests/api/test_tasks.py`

**Interfaces:**
- `POST /api/tasks`
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`

- [ ] **Step 1: Write failing create/list tests**

```python

def test_create_task_returns_persisted_task(client):
    response = client.post("/api/tasks", json={
        "basin_id": "camels_13235000",
        "model_id": "xaj",
        "start_date": "2025-05-01",
        "end_date": "2025-05-10",
        "forcing_mode": "R",
        "base_scheme_id": "scheme-base",
        "allow_optimization": True,
        "max_agent_decision_rounds": 20,
        "max_optimization_cycles": 4
    })
    assert response.status_code == 201
    task = response.json()
    assert task["basin_id"] == "camels_13235000"
    assert task["status"] == "created"
    assert client.get("/api/tasks").json()[0]["task_id"] == task["task_id"]


def test_no_browser_endpoint_executes_arbitrary_action(client):
    assert client.post("/api/tasks/task-1/actions/A07_OPTIMIZE").status_code == 404
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/api/test_tasks.py -k 'create_task or arbitrary_action' -v`

Expected: FAIL.

- [ ] **Step 3: Implement route behavior**

`POST /api/tasks`:

1. validate dates and configured model;
2. verify base Scheme exists and belongs to the selected model;
3. verify the requested forcing mode is allowed by current data contract;
4. create Task + initial TaskState in one application service call;
5. return HTTP 201 `TaskSummary`.

No endpoint accepts `ActionCode`, `strategy_id`, parameter vector, model command, or filesystem path from the browser.

- [ ] **Step 4: Run task route tests**

Run: `uv run pytest tests/api/test_tasks.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/api/routes/tasks.py src/hydro_agent/api/app.py tests/api/test_tasks.py
git commit -m "feat: expose task workbench APIs"
```

### Task 3: Add one-worker executor plus run/pause/resume APIs

**Files:**
- Create: `src/hydro_agent/api/executor.py`
- Create: `src/hydro_agent/api/routes/runs.py`
- Modify: `src/hydro_agent/api/app.py`
- Test: `tests/api/test_executor.py`
- Test: `tests/api/test_runs.py`

**Interfaces:**
- `TaskExecutor.start(task_id)`, `TaskExecutor.pause(task_id)`, `TaskExecutor.resume(task_id)`.
- `POST /api/tasks/{task_id}/run`
- `POST /api/tasks/{task_id}/pause`
- `POST /api/tasks/{task_id}/resume`
- `GET /api/tasks/{task_id}/run`

- [ ] **Step 1: Write failing single-worker/pause tests**

```python
# tests/api/test_executor.py

def test_executor_rejects_second_concurrent_local_task(executor):
    executor.start("task-1")
    with pytest.raises(RuntimeError, match="local worker busy"):
        executor.start("task-2")


def test_pause_sets_persisted_state_without_inventing_terminal_status(executor, repository):
    executor.pause("task-1")
    state = repository.get_task_state("task-1")
    assert state.paused is True
    assert repository.get_task("task-1").terminal_status is None
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/api/test_executor.py tests/api/test_runs.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement bounded local executor**

Use `ThreadPoolExecutor(max_workers=1)` only inside the API application service. Worker body:

```python
def _run(task_id: str) -> None:
    try:
        agent_runtime.run_until_terminal(task_id)
    finally:
        release_active_task(task_id)
```

`pause()` sets persisted `paused=True`; `AgentRuntime` stops before the next decision round. It does not forcibly terminate an in-flight SandboxRunner subprocess. `resume()` clears pause and resubmits only when no local worker is active. On process restart, persisted state remains authoritative and user explicitly resumes.

- [ ] **Step 4: Run executor/routes tests**

Run: `uv run pytest tests/api/test_executor.py tests/api/test_runs.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/api/executor.py src/hydro_agent/api/routes/runs.py src/hydro_agent/api/app.py tests/api/test_executor.py tests/api/test_runs.py
git commit -m "feat: control local agent task execution"
```

### Task 4: Build business timeline and results read APIs

**Files:**
- Modify: `src/hydro_agent/api/routes/runs.py`
- Create: `src/hydro_agent/api/routes/results.py`
- Modify: `src/hydro_agent/api/app.py`
- Test: `tests/api/test_runs.py`
- Test: `tests/api/test_results.py`

**Interfaces:**
- `GET /api/tasks/{task_id}/timeline`
- `GET /api/tasks/{task_id}/results`
- `GET /api/tasks/{task_id}/forecasts`
- `GET /api/tasks/{task_id}/report`

- [ ] **Step 1: Write failing timeline wording test**

```python
# tests/api/test_runs.py

def test_timeline_uses_business_language_and_keeps_ids_in_details(client, seeded_evidence):
    items = client.get("/api/tasks/task-1/timeline").json()
    labels = [item["label"] for item in items]
    assert "正在运行水文模型" in labels
    assert "候选方案因 Gate 未通过而撤销" in labels
    assert all(not item["label"].startswith("A0") for item in items)
    assert items[0]["details"]["action_run_id"]
```

- [ ] **Step 2: Write failing result-source test**

```python
# tests/api/test_results.py

def test_results_are_read_from_persisted_scheme_forecast_gate_report(client, completed_task):
    payload = client.get(f"/api/tasks/{completed_task}/results").json()
    assert payload["scheme"]["status"] == "frozen"
    assert payload["forecasts"]
    assert payload["metrics"]["NSE"] is not None
    assert payload["report_artifacts"]
```

- [ ] **Step 3: Implement explicit timeline mapping and result assembly**

Timeline labels map persisted action/outcome combinations, for example:

```text
A01 + running/succeeded -> 正在检查资料 / 资料检查完成
A05 -> 正在运行水文模型 / 预报完成
A07 -> 正在进行有限参数优化
A08 + ROLLBACK -> 候选方案因 Gate 未通过而撤销
A09 + KEEP -> 当前证据不足以支持更改，维持原方案
A10 -> 方案已冻结
A11 -> 正在执行历史起报回放
A12 -> 正在生成只读评价与报告
BLOCK -> 当前任务受阻，需要人工处理
```

Unknown combinations use `"执行记录"` and expose structured details; do not show raw exception text as the main label.

`results` reads SP7 frozen Scheme, Forecast rows, latest evaluation/report metadata and cost summaries. It performs no hydrologic calculations.

- [ ] **Step 4: Run read API tests**

Run: `uv run pytest tests/api/test_runs.py tests/api/test_results.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/api/routes tests/api/test_runs.py tests/api/test_results.py
git commit -m "feat: expose timeline and result read APIs"
```

### Task 5: Bootstrap Vue 3 workbench shell, typed API client, and Task page

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/vite.config.ts`
- Create: `web/src/main.ts`
- Create: `web/src/App.vue`
- Create: `web/src/router.ts`
- Create: `web/src/api/client.ts`
- Create: `web/src/types/api.ts`
- Create: `web/src/stores/tasks.ts`
- Create: `web/src/views/TaskView.vue`
- Create: `web/src/__tests__/TaskView.test.ts`

**Interfaces:**
- Routes: `/tasks`, `/tasks/:taskId/run`, `/tasks/:taskId/results`.

- [ ] **Step 1: Write failing Task page test**

```ts
// web/src/__tests__/TaskView.test.ts
it('creates a task using domain fields without action checkboxes', async () => {
  const wrapper = mountWithApp(TaskView)
  expect(wrapper.text()).toContain('创建预报任务')
  expect(wrapper.text()).toContain('流域')
  expect(wrapper.text()).toContain('模型')
  expect(wrapper.text()).toContain('Forcing 模式')
  expect(wrapper.findAll('input[type="checkbox"][name^="A0"]')).toHaveLength(0)
})
```

- [ ] **Step 2: Verify failure**

Run: `cd web && npm test -- --run src/__tests__/TaskView.test.ts`

Expected: FAIL because frontend does not exist.

- [ ] **Step 3: Add exact frontend dependencies and task form**

`package.json` dependencies:

```json
{
  "vue": "^3.5.0",
  "vue-router": "^4.5.0",
  "pinia": "^3.0.0",
  "echarts": "^6.0.0"
}
```

Dev dependencies include TypeScript, Vite, `@vitejs/plugin-vue`, Vitest, Vue Test Utils, jsdom, Playwright.

Task form fields mirror `TaskCreateRequest`; submit through `POST /api/tasks`, then route to `/tasks/{task_id}/run`. Do not create any advanced workflow builder in SP8.

- [ ] **Step 4: Run Task page test/build**

```bash
cd web
npm install
npm test -- --run src/__tests__/TaskView.test.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web
git commit -m "feat: add workbench task page"
```

### Task 6: Build Run page with polling, timeline, pause/resume, and expandable technical evidence

**Files:**
- Create: `web/src/stores/run.ts`
- Create: `web/src/views/RunView.vue`
- Create: `web/src/components/BusinessTimeline.vue`
- Create: `web/src/__tests__/RunView.test.ts`

**Interfaces:**
- Polls `/api/tasks/{id}/run` and `/api/tasks/{id}/timeline` every 2 seconds while active.

- [ ] **Step 1: Write failing business-timeline test**

```ts
it('shows business timeline first and technical ids only when expanded', async () => {
  const wrapper = mountRunViewWithTimeline([
    { id: 't1', label: '正在运行水文模型', status: 'running', action: 'A05_FORECAST', evidence_id: 'ev-1', details: { action_run_id: 'run-1' } }
  ])
  expect(wrapper.text()).toContain('正在运行水文模型')
  expect(wrapper.text()).not.toContain('run-1')
  await wrapper.get('[data-test="timeline-expand-t1"]').trigger('click')
  expect(wrapper.text()).toContain('run-1')
})
```

- [ ] **Step 2: Verify failure**

Run: `cd web && npm test -- --run src/__tests__/RunView.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement Run page state**

Display:

```text
Task phase/status
current hypothesis summary
current/last business action
remaining agent/optimization budgets
business timeline
Pause / Resume button
```

Polling stops when paused or terminal. Pause/resume uses exact APIs from Task 3. No button can directly invoke A01-A12.

- [ ] **Step 4: Run test**

Run: `cd web && npm test -- --run src/__tests__/RunView.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/stores/run.ts web/src/views/RunView.vue web/src/components/BusinessTimeline.vue web/src/__tests__/RunView.test.ts
git commit -m "feat: add evidence driven run timeline"
```

### Task 7: Build Result page with process lines, Gate/Scheme provenance, and report links

**Files:**
- Create: `web/src/stores/results.ts`
- Create: `web/src/views/ResultView.vue`
- Create: `web/src/components/ForecastChart.vue`
- Create: `web/src/components/GateSummary.vue`
- Create: `web/src/components/SchemeSummary.vue`
- Create: `web/src/components/ReportLinks.vue`
- Create: `web/src/__tests__/ResultView.test.ts`

**Interfaces:**
- Reads `/api/tasks/{id}/results` and `/api/tasks/{id}/forecasts`.

- [ ] **Step 1: Write failing result-view test**

```ts
it('shows frozen scheme, gate outcome, metrics and lead series', async () => {
  const wrapper = mountResultView(completedResultFixture)
  expect(wrapper.text()).toContain('冻结方案')
  expect(wrapper.text()).toContain('NSE')
  expect(wrapper.text()).toContain('KGE')
  expect(wrapper.find('[data-test="forecast-chart"]').exists()).toBe(true)
  expect(wrapper.find('[data-test="report-json"]').exists()).toBe(true)
})
```

- [ ] **Step 2: Verify failure**

Run: `cd web && npm test -- --run src/__tests__/ResultView.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement result composition**

`ForecastChart` renders separate observed/lead-1/lead-2/lead-3 series from API data with ECharts. It never recomputes metrics. `GateSummary` shows `ACCEPT/KEEP/ROLLBACK` and reasons. `SchemeSummary` shows model, scheme version/hash prefix, forcing mode and provenance. `ReportLinks` links to backend artifact endpoints; no local filesystem path is rendered.

- [ ] **Step 4: Run result test/build**

```bash
cd web
npm test -- --run src/__tests__/ResultView.test.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/stores/results.ts web/src/views/ResultView.vue web/src/components web/src/__tests__/ResultView.test.ts
git commit -m "feat: add forecast result workbench"
```

### Task 8: Add one end-to-end workbench flow and final regression commands

**Files:**
- Create: `web/e2e/workbench.spec.ts`
- Modify: `web/package.json`

**Interfaces:**
- Produces a browser-level test covering Task -> Run -> Result against a fixture backend.

- [ ] **Step 1: Write Playwright flow**

```ts
// web/e2e/workbench.spec.ts
import { test, expect } from '@playwright/test'

test('task flows from creation to evidence timeline to results', async ({ page }) => {
  await page.goto('/tasks')
  await page.getByLabel('流域').fill('camels_13235000')
  await page.getByLabel('模型').selectOption('xaj')
  await page.getByRole('button', { name: '创建并运行' }).click()
  await expect(page.getByText('正在运行水文模型')).toBeVisible()
  await expect(page.getByText('方案已冻结')).toBeVisible()
  await page.getByRole('link', { name: '查看结果' }).click()
  await expect(page.getByText('冻结方案')).toBeVisible()
  await expect(page.getByText('NSE')).toBeVisible()
})
```

Use deterministic mocked API routes or a seeded local backend fixture; do not depend on the real XAJ integration test for browser CI.

- [ ] **Step 2: Run E2E test and observe first failure**

Run: `cd web && npx playwright test e2e/workbench.spec.ts`

Expected before fixture wiring: FAIL at the first unavailable seeded endpoint.

- [ ] **Step 3: Add deterministic fixture configuration**

Configure Playwright `webServer` to start Vite and a test FastAPI server seeded with a scripted AgentRuntime trajectory:

```text
A05 forecast -> evidence
A07 optimize -> candidate
A08 gate -> rollback or accept fixture
A09 resolve
A10 freeze
A11 replay
A12 evaluate/report
```

The fixture may use fake numerical services but must use the real API schemas, persisted timeline/result assembly, and frontend client.

- [ ] **Step 4: Run full SP8 acceptance suite**

```bash
uv run pytest tests/api -v
cd web
npm test -- --run
npm run build
npx playwright test
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/e2e web/package.json
git commit -m "test: cover complete workbench flow"
```

## SP8 Acceptance

```bash
uv run pytest tests/api -v
cd web
npm test -- --run
npm run build
npx playwright test
```

Acceptance requires a user to create a Task without selecting A01-A12, start/pause/resume the local automatic run, follow the run in business language, expand technical evidence when needed, inspect the frozen Scheme/Gate/forecast process lines, and open the final report from data that is sourced from the same backend ledger as the Agent.