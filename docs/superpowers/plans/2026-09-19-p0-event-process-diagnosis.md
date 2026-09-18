# P0 次洪与水文过程诊断 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有连续过程评价升级为可重复的次洪分割、洪峰/峰现/洪量/涨退水诊断，并把完整结构化过程证据传入 Agent 与工作台展示。

**Architecture:** 先新增确定性 event segmentation，再由 `HydrologicEvidenceBuilder` 计算 event signatures；随后扩展 Agent-facing 契约，确保 LLM 只解释程序生成的证据而不自行计算指标。前端只消费后端结构化数据，不通过截图反推科研结论。

**Tech Stack:** Python 3.12、NumPy、Pydantic、pytest、Vue 3、TypeScript、Vitest、ECharts

**Spec:** `docs/superpowers/specs/2026-09-19-hydrologic-process-diagnosis-and-spatial-units-design.md`

## Global Constraints

- 不允许 LLM 自己切分洪水事件。
- 不允许 LLM 从图片自行计算 NSE、洪峰、洪量或峰现误差。
- 事件边界和 signatures 必须由确定性代码产生。
- final-test 的 event evidence 不得回流当前 calibration campaign。
- 缺少降雨资料时允许 `flow_only` 降级，但必须显式标记。
- 保持现有 `HydrologicEvidenceBuilder` 的质量掩码和 window isolation 语义。
- 不修改老师 XAJ v6 内核。
- 本计划完成后，P1 才能依赖完整 event/process evidence 做诊断驱动率定。

---

## File Structure

- Create `src/hydro_agent/evaluation/events.py`：次洪事件边界与 event contracts。
- Modify `src/hydro_agent/evaluation/evidence.py`：把 event segmentation 接入证据构建并增加涨退水 signatures。
- Modify `src/hydro_agent/agent/hydrologic_evidence.py`：新增完整 `HydrographDiagnosisPacket`。
- Create `src/hydro_agent/evaluation/diagnosis_packet.py`：从 deterministic bundle 生成 Agent-facing packet。
- Modify `src/hydro_agent/services/continuous_simulation.py`：暴露 packet/event evidence。
- Modify `web/src/components/AgentCalibrationPanel.vue`：展示 Agent 观察与过程诊断。
- Create `web/src/components/FloodEventMatrix.vue`：次洪矩阵。
- Tests 对应放在现有 `tests/evaluation`、`tests/agent` 和 `web/src/__tests__`。

---

### Task 1: Deterministic Flood Event Segmentation

**Files:**
- Create: `src/hydro_agent/evaluation/events.py`
- Create: `tests/evaluation/test_events.py`

**Interfaces:**
- Consumes: `dates: Sequence[date]`、`observed: Sequence[float]`、可选 `precipitation: Sequence[float | None]`。
- Produces:
  - `FloodEventBoundary`
  - `EventSegmentationConfig`
  - `segment_flood_events(...) -> tuple[FloodEventBoundary, ...]`

- [ ] **Step 1: Write failing tests for deterministic flow-only segmentation**

```python
from datetime import date, timedelta

from hydro_agent.evaluation.events import EventSegmentationConfig, segment_flood_events


def test_flow_only_segmentation_is_deterministic_and_marks_basis():
    start = date(2020, 7, 1)
    dates = [start + timedelta(days=i) for i in range(12)]
    observed = [10, 11, 12, 20, 50, 90, 45, 18, 12, 13, 14, 12]

    events = segment_flood_events(
        dates=dates,
        observed=observed,
        precipitation=None,
        config=EventSegmentationConfig(
            high_flow_quantile=0.75,
            min_event_steps=3,
            min_separation_steps=2,
        ),
    )

    assert len(events) == 1
    assert events[0].event_id == "event-001"
    assert events[0].basis == "flow_only"
    assert events[0].start <= dates[4]
    assert events[0].peak_time == dates[5]
    assert events[0].end >= dates[6]
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
uv run pytest tests/evaluation/test_events.py -v
```

Expected: FAIL because `hydro_agent.evaluation.events` does not exist.

- [ ] **Step 3: Implement event contracts and flow-only segmentation**

Use these public contracts:

```python
@dataclass(frozen=True)
class EventSegmentationConfig:
    high_flow_quantile: float = 0.90
    min_event_steps: int = 3
    min_separation_steps: int = 2
    rise_search_steps: int = 3
    recession_search_steps: int = 5


@dataclass(frozen=True)
class FloodEventBoundary:
    event_id: str
    start: date
    peak_time: date
    end: date
    basis: Literal["flow_only", "rainfall_runoff"]
    rain_start: date | None = None
    rain_end: date | None = None
```

Implementation rules:

1. Validate equal lengths and strictly increasing dates.
2. Compute threshold from observed valid values only.
3. Find local maxima at or above threshold.
4. Expand each peak backward/forward using configured rise/recession windows.
5. Merge windows whose separation is below `min_separation_steps`.
6. Drop windows shorter than `min_event_steps`.
7. Re-number events after merging as `event-001`, `event-002`, ...

- [ ] **Step 4: Add rainfall-assisted segmentation test**

```python
def test_rainfall_assisted_segmentation_marks_rainfall_runoff_basis():
    ...
    events = segment_flood_events(..., precipitation=rain)
    assert events[0].basis == "rainfall_runoff"
    assert events[0].rain_start is not None
```

Rainfall-assisted logic must only expand/anchor a deterministic flow event; rainfall alone must not create an event when no runoff response exists.

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/evaluation/test_events.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hydro_agent/evaluation/events.py tests/evaluation/test_events.py
git commit -m "feat: add deterministic flood event segmentation"
```

---

### Task 2: Event Signatures and Hydrograph Process Metrics

**Files:**
- Modify: `src/hydro_agent/evaluation/evidence.py`
- Modify: `tests/evaluation/test_evidence.py`

**Interfaces:**
- Consumes: `FloodEventBoundary` from Task 1.
- Produces enriched `FloodEventEvidence.metrics` containing:
  - `peak_relative_error`
  - `peak_timing_lag_steps`
  - `volume_ratio`
  - `volume_relative_error`
  - `rising_limb_mae`
  - `recession_mae`
  - `duration_steps`
  - `response_lag_steps` when rainfall is available.

- [ ] **Step 1: Add failing event signature test**

```python
def test_event_evidence_contains_peak_volume_rise_and_recession_signatures():
    bundle = HydrologicEvidenceBuilder(...).build(
        window="calibration",
        dates=dates,
        observed=observed,
        simulated=simulated,
        precipitation=precipitation,
    )
    event = bundle.flood_events[0]
    assert event.status == "available"
    assert "peak_relative_error" in event.metrics
    assert "volume_relative_error" in event.metrics
    assert "rising_limb_mae" in event.metrics
    assert "recession_mae" in event.metrics
```

- [ ] **Step 2: Run target test**

```bash
uv run pytest tests/evaluation/test_evidence.py -k event -v
```

Expected: FAIL because current builder neither accepts precipitation nor exposes limb metrics.

- [ ] **Step 3: Replace internal Q90 contiguous grouping with Task 1 segmenter**

Keep `HydrologicEvidenceBuilder.build(...)` backward compatible by adding:

```python
precipitation: Sequence[float | None] | None = None
```

When `precipitation is None`, use flow-only segmentation.

- [ ] **Step 4: Compute signatures with transparent definitions**

Definitions:

```text
peak_relative_error = (sim_peak - obs_peak) / obs_peak
volume_relative_error = (sum(sim) - sum(obs)) / sum(obs)
rising_limb_mae = MAE from event start through observed peak
recession_mae = MAE from observed peak through event end
duration_steps = number of evaluated event points
response_lag_steps = observed flow peak index - rainfall peak index
```

Do not normalize limb error with an undocumented scale. If a normalized metric is later needed, add it as a separate named metric.

- [ ] **Step 5: Add quality/edge tests**

Cover:

- insufficient event samples;
- zero observed peak/volume;
- missing precipitation;
- multiple merged peaks;
- event dates with quality-mask exclusions.

- [ ] **Step 6: Run evaluation regression**

```bash
uv run pytest tests/evaluation -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hydro_agent/evaluation/evidence.py tests/evaluation/test_evidence.py
git commit -m "feat: add flood event process signatures"
```

---

### Task 3: Build Full Agent-Facing HydrographDiagnosisPacket

**Files:**
- Create: `src/hydro_agent/evaluation/diagnosis_packet.py`
- Modify: `src/hydro_agent/agent/hydrologic_evidence.py`
- Modify: `tests/agent/test_hydrologic_evidence.py`
- Create: `tests/evaluation/test_diagnosis_packet.py`

**Interfaces:**
- Consumes: `HydrologicEvidenceBundle`.
- Produces:
  - `HydrographDiagnosisPacket`
  - `build_diagnosis_packet(bundle, *, basin_attributes=None) -> HydrographDiagnosisPacket`

- [ ] **Step 1: Write failing packet test**

```python
def test_packet_preserves_multiple_events_flow_regimes_and_fdc():
    packet = build_diagnosis_packet(bundle)
    assert len(packet.flood_events) == 2
    assert packet.flow_regimes["high"].metrics
    assert packet.fdc.metrics
    assert packet.overall.metrics["nse"] == bundle.overall.metrics["nse"]
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/evaluation/test_diagnosis_packet.py -v
```

Expected: FAIL because packet builder does not exist.

- [ ] **Step 3: Add stable Pydantic packet contracts**

Use explicit nested views:

```python
class EvidenceSliceView(FrozenModel):
    status: str
    sample_count: int
    metrics: dict[str, float] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()


class FloodEventDiagnosticView(EvidenceSliceView):
    event_id: str
    start: str
    end: str
    basis: str


class HydrographDiagnosisPacket(FrozenModel):
    window: str
    overall: EvidenceSliceView
    water_balance: EvidenceSliceView
    flow_regimes: dict[str, EvidenceSliceView]
    fdc: EvidenceSliceView
    seasons: dict[str, EvidenceSliceView]
    years: dict[str, EvidenceSliceView]
    flood_events: tuple[FloodEventDiagnosticView, ...]
    data_quality: DataQualityView
    basin_attributes: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Keep backward compatibility**

`HydrologicEvidence.from_diagnosis()` must continue accepting legacy dicts. Add optional:

```python
diagnosis_packet: HydrographDiagnosisPacket | None = None
```

Do not delete current `overall` / `flood_events` fields yet; derive legacy views from the packet during migration.

- [ ] **Step 5: Run agent/evaluation tests**

```bash
uv run pytest tests/agent/test_hydrologic_evidence.py tests/evaluation/test_diagnosis_packet.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hydro_agent/evaluation/diagnosis_packet.py src/hydro_agent/agent/hydrologic_evidence.py tests/agent/test_hydrologic_evidence.py tests/evaluation/test_diagnosis_packet.py
git commit -m "feat: expose full hydrograph diagnosis packet"
```

---

### Task 4: Feed Diagnosis Packet Through Continuous Evidence Service

**Files:**
- Modify: `src/hydro_agent/services/continuous_simulation.py`
- Modify: `tests/evaluation/test_service.py`
- Modify: `src/hydro_agent/evaluation/hydrograph.py`
- Modify: `tests/evaluation/test_hydrograph.py`

**Interfaces:**
- Consumes: continuous obs/sim/forcing already isolated to one legal window.
- Produces `diagnosis_packet` alongside existing scalar metrics without breaking old callers.

- [ ] **Step 1: Write failing service test**

```python
def test_continuous_service_returns_diagnosis_packet_without_changing_scalar_metrics():
    evidence = service.evaluate(...)
    assert evidence.nse == expected_nse
    assert evidence.diagnosis_packet.window == "calibration"
    assert evidence.diagnosis_packet.flood_events
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/evaluation/test_service.py -k diagnosis -v
```

- [ ] **Step 3: Extend `ContinuousSimulationEvidence`**

Add:

```python
diagnosis_packet: HydrographDiagnosisPacket | None = None
```

Keep `as_metrics()` unchanged so old optimization/report code does not silently change serialized scalar metrics.

- [ ] **Step 4: Add packet to hydrograph comparison JSON**

`build_comparison()` should include optional `baseline_diagnosis` and `candidate_diagnosis` fields while preserving existing keys.

- [ ] **Step 5: Run regression**

```bash
uv run pytest tests/evaluation tests/services -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hydro_agent/services/continuous_simulation.py src/hydro_agent/evaluation/hydrograph.py tests/evaluation/test_service.py tests/evaluation/test_hydrograph.py
git commit -m "feat: propagate process diagnosis evidence"
```

---

### Task 5: Workbench Process Diagnosis and Flood Event Matrix

**Files:**
- Modify: `web/src/components/AgentCalibrationPanel.vue`
- Create: `web/src/components/FloodEventMatrix.vue`
- Create: `web/src/__tests__/FloodEventMatrix.test.ts`
- Modify: `web/src/__tests__/ExecutionJournalCalibration.test.ts`

**Interfaces:**
- Consumes persisted diagnosis packet returned by existing task/result API.
- Produces hydrologist-facing display; no client-side recomputation of hydrologic metrics.

- [ ] **Step 1: Write failing component test**

```ts
it('renders multiple flood events and hydrologic diagnosis evidence', () => {
  const wrapper = mount(FloodEventMatrix, {
    props: {
      events: [
        { event_id: 'event-001', metrics: { peak_relative_error: -0.18, peak_timing_lag_steps: 1, volume_relative_error: 0.03 } },
        { event_id: 'event-002', metrics: { peak_relative_error: -0.11, peak_timing_lag_steps: 1, volume_relative_error: 0.01 } },
      ],
    },
  })

  expect(wrapper.text()).toContain('event-001')
  expect(wrapper.text()).toContain('洪峰')
  expect(wrapper.text()).toContain('峰现')
  expect(wrapper.text()).toContain('洪量')
})
```

- [ ] **Step 2: Run RED**

```bash
cd web
npm test -- --run src/__tests__/FloodEventMatrix.test.ts
```

- [ ] **Step 3: Implement matrix**

Columns:

```text
事件 | 时段 | 洪峰误差 | 峰现偏差 | 洪量误差 | 涨水段 | 退水段 | 证据状态
```

Do not introduce a synthetic “AI 总分”.

- [ ] **Step 4: Extend AgentCalibrationPanel**

Render three blocks when evidence exists:

```text
Agent 观察
水文诊断
下一步实验
```

The panel must show evidence IDs or event IDs supporting the diagnosis.

- [ ] **Step 5: Run frontend tests/build**

```bash
cd web
npm test -- --run src/__tests__/FloodEventMatrix.test.ts src/__tests__/ExecutionJournalCalibration.test.ts
npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/AgentCalibrationPanel.vue web/src/components/FloodEventMatrix.vue web/src/__tests__/FloodEventMatrix.test.ts web/src/__tests__/ExecutionJournalCalibration.test.ts
git commit -m "feat: visualize flood event diagnosis"
```

---

## Acceptance

Run:

```bash
uv run pytest tests/evaluation tests/agent/test_hydrologic_evidence.py -v
cd web
npm test -- --run src/__tests__/FloodEventMatrix.test.ts src/__tests__/ExecutionJournalCalibration.test.ts
npm run build
```

Acceptance requires:

- [ ] Event segmentation is deterministic.
- [ ] Rainfall-assisted and flow-only event basis are distinguishable.
- [ ] Peak/timing/volume/rise/recession evidence is present and traceable.
- [ ] Agent-facing packet preserves multiple events rather than only one peak.
- [ ] Existing scalar metrics remain backward compatible.
- [ ] Frontend displays event/process evidence without recomputing hydrologic metrics.
- [ ] No final-test evidence is introduced into calibration decision paths.
