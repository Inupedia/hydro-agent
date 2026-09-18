# P2 空间异质性与计算单元推荐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Hydro-Agent 在构建水文方案时读取可审计的气象、地形、土地利用、土壤和河网空间证据，生成多个确定性计算单元候选，并由 Agent 在候选之间做可解释推荐。

**Architecture:** 新增 `BasinSpatialProfile` 作为空间事实层，再新增确定性 `UnitSchemeCandidate` 生成器。Agent 只比较候选，不直接创建 polygon；最终边界继续由现有 DEM/GIS 建模工具生成和复核。本计划不实现完整多区 XAJ 率定，只把“空间异质性 → 单元候选 → 推荐”闭环打通。

**Tech Stack:** Python 3.12、Pydantic、NumPy、Rasterio/Shapely/PyProj/PyFlwDir（沿用现有 xaj-dem 可选依赖）、pytest、Vue 3、TypeScript、现有地图审查组件

**Spec:** `docs/superpowers/specs/2026-09-19-hydrologic-process-diagnosis-and-spatial-units-design.md`

## Global Constraints

- LLM 不允许自由生成 polygon。
- 相同空间输入必须产生相同 spatial profile 和候选方案。
- 缺失空间数据必须显式记为 unknown，不做气候/土壤/土地利用猜测。
- 单个 heterogeneity score 不得直接决定计算单元数量。
- Agent 只能从确定性候选方案中推荐。
- 推荐必须引用具体 spatial evidence。
- 不替换老师 XAJ v6 内核。
- 不在本计划开放完整多区参数率定。
- 所有 GIS 边界仍走现有边界复核和 hash 校验流程。

---

## File Structure

- Create `src/hydro_agent/hydrology/spatial_profile.py`：空间画像契约和统计。
- Create `tests/hydrology/test_spatial_profile.py`。
- Create `src/hydro_agent/modeling/unit_candidates.py`：确定性候选方案。
- Create `tests/modeling/test_unit_candidates.py`。
- Modify `src/hydro_agent/modeling/plans.py`：在 M02/M03 之间保存候选和 spatial evidence。
- Modify `src/hydro_agent/modeling/hydrologist.py`：Agent 推荐候选，不画边界。
- Modify `tests/modeling/test_hydrologist.py`、`tests/modeling/test_plans.py`。
- Modify `web/src/views/PrepareView.vue`：展示空间异质性和候选方案。
- Add `web/src/components/SpatialHeterogeneityPanel.vue`。
- Add `web/src/__tests__/SpatialHeterogeneityPanel.test.ts`。
- Modify `web/src/__tests__/ModelPreparation.test.ts`。

---

### Task 1: BasinSpatialProfile Contracts and Deterministic Statistics

**Files:**
- Create: `src/hydro_agent/hydrology/spatial_profile.py`
- Create: `tests/hydrology/test_spatial_profile.py`

**Interfaces:**
- Consumes already prepared arrays/tables from trusted DEM/GIS/data adapters.
- Produces `BasinSpatialProfile`.
- Does not download data itself.

- [ ] **Step 1: Write failing profile test**

```python
from hydro_agent.hydrology.spatial_profile import derive_basin_spatial_profile


def test_spatial_profile_reports_component_statistics_without_single_decision_score():
    profile = derive_basin_spatial_profile(
        elevation_m=[100, 200, 300, 400],
        slope_deg=[2, 5, 20, 35],
        precipitation_mm=[900, 1000, 1300, 1500],
        land_cover={"forest": 0.6, "cropland": 0.4},
        soil={"clay": 0.25, "loam": 0.75},
        drainage={
            "area_km2": 100.0,
            "stream_length_km": 50.0,
            "main_channel_length_km": 20.0,
        },
    )

    assert profile.elevation.mean_m == 250.0
    assert profile.precipitation.cv > 0
    assert profile.land_cover.fractions["forest"] == 0.6
    assert not hasattr(profile, "recommended_unit_count")
    assert not hasattr(profile, "overall_heterogeneity_score")
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/hydrology/test_spatial_profile.py -v
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Add focused contracts**

Use nested Pydantic models:

```python
class NumericSpatialSummary(FrozenModel):
    status: Literal["available", "unknown"]
    count: int = 0
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    std: float | None = None
    cv: float | None = None
    q25: float | None = None
    q50: float | None = None
    q75: float | None = None


class CategoricalSpatialSummary(FrozenModel):
    status: Literal["available", "unknown"]
    fractions: dict[str, float] = Field(default_factory=dict)
    dominant_class: str | None = None


class DrainageSpatialSummary(FrozenModel):
    status: Literal["available", "unknown"]
    area_km2: float | None = None
    stream_density_km_per_km2: float | None = None
    main_channel_length_km: float | None = None


class BasinSpatialProfile(FrozenModel):
    elevation: NumericSpatialSummary
    slope: NumericSpatialSummary
    precipitation: NumericSpatialSummary
    land_cover: CategoricalSpatialSummary
    soil: CategoricalSpatialSummary
    drainage: DrainageSpatialSummary
    evidence_quality: tuple[str, ...] = ()
```

- [ ] **Step 4: Implement deterministic summaries**

Rules:

- ignore only explicit missing/non-finite samples;
- reject negative precipitation;
- categorical fractions must sum to approximately 1.0 or be normalized with an evidence-quality note;
- `cv = std / mean` only when mean > 0;
- do not synthesize missing categories.

- [ ] **Step 5: Add missing-data tests**

```python
def test_missing_land_cover_and_soil_remain_unknown():
    profile = derive_basin_spatial_profile(...)
    assert profile.land_cover.status == "unknown"
    assert profile.soil.status == "unknown"
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/hydrology/test_spatial_profile.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hydro_agent/hydrology/spatial_profile.py tests/hydrology/test_spatial_profile.py
git commit -m "feat: derive basin spatial heterogeneity profile"
```

---

### Task 2: Deterministic Unit Scheme Candidates

**Files:**
- Create: `src/hydro_agent/modeling/unit_candidates.py`
- Create: `tests/modeling/test_unit_candidates.py`

**Interfaces:**
- Consumes:
  - `BasinSpatialProfile`;
  - existing topology/sub-basin metadata from delineation;
  - existing unit polygons/IDs generated by deterministic GIS tools.
- Produces up to three `UnitSchemeCandidate` records.

- [ ] **Step 1: Write failing candidate test**

```python
def test_candidate_builder_returns_lumped_topology_and_heterogeneity_options():
    result = build_unit_scheme_candidates(
        spatial_profile=profile,
        topology_units=topology_units,
        max_units=8,
    )

    assert [item.kind for item in result] == [
        "lumped",
        "topology_subbasin",
        "heterogeneity_aware",
    ]
    assert all(item.unit_count >= 1 for item in result)
    assert all(item.evidence_refs for item in result)
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/modeling/test_unit_candidates.py -v
```

- [ ] **Step 3: Add candidate contract**

```python
class UnitSchemeCandidate(FrozenModel):
    candidate_id: str
    kind: Literal["lumped", "topology_subbasin", "heterogeneity_aware"]
    unit_ids: tuple[str, ...]
    unit_count: int
    area_distribution_km2: tuple[float, ...]
    evidence_refs: tuple[str, ...]
    preserved_contrasts: tuple[str, ...] = ()
    lost_contrasts: tuple[str, ...] = ()
    complexity_notes: tuple[str, ...] = ()
```

- [ ] **Step 4: Implement candidate rules**

`lumped`:

- one unit covering full basin;
- preserve no spatial contrasts;
- complexity note = simplest.

`topology_subbasin`:

- use existing deterministic topology units;
- never invent new polygon boundaries.

`heterogeneity_aware`:

- start from topology units;
- only split/merge using deterministic rules based on already computed spatial contrasts;
- V1 allowed contrasts: elevation, precipitation, land cover;
- no split when required source is unknown;
- enforce `1 <= unit_count <= max_units`.

- [ ] **Step 5: Add deterministic/reproducibility test**

Same inputs in different dictionary iteration order must produce identical candidate IDs and unit ordering.

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/modeling/test_unit_candidates.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hydro_agent/modeling/unit_candidates.py tests/modeling/test_unit_candidates.py
git commit -m "feat: build deterministic unit scheme candidates"
```

---

### Task 3: Integrate Spatial Evidence Into Model Plan Build

**Files:**
- Modify: `src/hydro_agent/modeling/plans.py`
- Modify: `tests/modeling/test_plans.py`
- Modify: `src/hydro_agent/modeling/review_map.py`
- Modify: `tests/modeling/test_review_map.py`

**Interfaces:**
- Consumes Task 1 profile + Task 2 candidates.
- Persists:
  - `spatial-profile.json`
  - `unit-candidates.json`
- Does not change the existing boundary confirmation hash rules.

- [ ] **Step 1: Add failing plan artifact test**

```python
def test_model_plan_persists_spatial_profile_and_unit_candidates_before_review(...):
    ...
    assert (plan_dir / "spatial-profile.json").is_file()
    assert (plan_dir / "unit-candidates.json").is_file()
    plan = service.get(plan_id)
    assert plan["unit_candidates"]
    assert plan["spatial_profile_status"] in {"available", "partial"}
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/modeling/test_plans.py -k spatial -v
```

- [ ] **Step 3: Insert spatial analysis after deterministic delineation**

Keep stage names backward compatible. Within `M02_DELINEATE`:

```text
delineate topology
→ derive spatial profile
→ build unit candidates
→ persist artifacts
→ proceed to M03_REVIEW_BOUNDARY
```

Do not automatically choose the Agent recommendation as accepted boundary yet.

- [ ] **Step 4: Include candidates in review map payload**

Each candidate must reference existing geospatial unit IDs/polygons. The map layer may switch candidate visibility, but must not mutate the underlying reviewed source files.

- [ ] **Step 5: Run modeling regression**

```bash
uv run pytest tests/modeling/test_plans.py tests/modeling/test_review_map.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hydro_agent/modeling/plans.py src/hydro_agent/modeling/review_map.py tests/modeling/test_plans.py tests/modeling/test_review_map.py
git commit -m "feat: persist spatial evidence during model planning"
```

---

### Task 4: Agent Recommendation Among Existing Unit Candidates

**Files:**
- Modify: `src/hydro_agent/modeling/hydrologist.py`
- Modify: `tests/modeling/test_hydrologist.py`

**Interfaces:**
- Consumes:
  - `BasinSpatialProfile`;
  - tuple of `UnitSchemeCandidate`.
- Produces `UnitSchemeRecommendation`.
- Cannot return arbitrary polygon geometry.

- [ ] **Step 1: Write failing recommendation contract test**

```python
def test_hydrologist_recommends_only_registered_candidate():
    recommendation = recommend_unit_scheme(
        spatial_profile=profile,
        candidates=candidates,
        llm_payload={
            "candidate_id": "units-topology-004",
            "rationale": "降雨和高程差异明显，拓扑四分区保留主要差异且复杂度适中",
            "evidence_refs": ["precipitation.cv", "elevation.std"],
            "confidence": 0.78,
        },
    )

    assert recommendation.candidate_id == "units-topology-004"
    assert recommendation.candidate_id in {item.candidate_id for item in candidates}
    assert not hasattr(recommendation, "polygon")
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/modeling/test_hydrologist.py -k unit_scheme -v
```

- [ ] **Step 3: Add recommendation contract**

```python
class UnitSchemeRecommendation(FrozenModel):
    candidate_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    evidence_refs: tuple[str, ...]
    uncertainties: tuple[str, ...] = ()
```

- [ ] **Step 4: Validate LLM output against candidates**

Reject when:

- candidate ID does not exist;
- evidence ref is not present in spatial profile/candidate evidence;
- rationale is empty;
- response tries to inject geometry or unknown unit IDs.

Fallback must be deterministic and conservative: choose `topology_subbasin` when available, otherwise `lumped`, and label the recommendation as fallback.

- [ ] **Step 5: Add missing-data behavior test**

When precipitation/land-cover/soil are unknown, recommendation may still use topology/DEM evidence but must include the missing dimensions in `uncertainties`.

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/modeling/test_hydrologist.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hydro_agent/modeling/hydrologist.py tests/modeling/test_hydrologist.py
git commit -m "feat: recommend deterministic computation unit schemes"
```

---

### Task 5: Workbench Spatial Heterogeneity and Candidate Review

**Files:**
- Create: `web/src/components/SpatialHeterogeneityPanel.vue`
- Modify: `web/src/views/PrepareView.vue`
- Create: `web/src/__tests__/SpatialHeterogeneityPanel.test.ts`
- Modify: `web/src/__tests__/ModelPreparation.test.ts`

**Interfaces:**
- Consumes backend plan payload:
  - spatial profile;
  - candidate metadata;
  - recommendation;
  - map layers already exposed by the model preparation path.
- Produces review UI only; no client-side unit generation.

- [ ] **Step 1: Write failing panel test**

```ts
it('shows spatial facts, candidate units, and recommendation evidence', () => {
  const wrapper = mount(SpatialHeterogeneityPanel, {
    props: {
      profile: {
        elevation: { status: 'available', mean: 420, std: 180 },
        precipitation: { status: 'available', cv: 0.31 },
        land_cover: { status: 'unknown', fractions: {} },
      },
      candidates: [
        { candidate_id: 'lumped-001', kind: 'lumped', unit_count: 1 },
        { candidate_id: 'topology-004', kind: 'topology_subbasin', unit_count: 4 },
      ],
      recommendation: {
        candidate_id: 'topology-004',
        rationale: '降雨和高程差异明显',
        evidence_refs: ['precipitation.cv', 'elevation.std'],
      },
    },
  })

  expect(wrapper.text()).toContain('空间异质性')
  expect(wrapper.text()).toContain('4')
  expect(wrapper.text()).toContain('降雨和高程差异明显')
  expect(wrapper.text()).toContain('资料缺失')
})
```

- [ ] **Step 2: Run RED**

```bash
cd web
npm test -- --run src/__tests__/SpatialHeterogeneityPanel.test.ts
```

- [ ] **Step 3: Implement panel sections**

Sections:

```text
空间画像
  高程
  坡度
  降雨
  土地利用
  土壤
  河网

候选方案
  lumped
  topology_subbasin
  heterogeneity_aware

Agent 推荐
  candidate
  理由
  证据
  不确定性
```

Unknown values must display `资料缺失` rather than zero.

- [ ] **Step 4: Integrate into PrepareView review step**

Show the panel before/alongside existing boundary confirmation. Candidate switching is visualization-only until user confirms the model plan through existing review semantics.

- [ ] **Step 5: Run tests/build**

```bash
cd web
npm test -- --run src/__tests__/SpatialHeterogeneityPanel.test.ts src/__tests__/ModelPreparation.test.ts
npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/SpatialHeterogeneityPanel.vue web/src/views/PrepareView.vue web/src/__tests__/SpatialHeterogeneityPanel.test.ts web/src/__tests__/ModelPreparation.test.ts
git commit -m "feat: visualize spatial unit recommendations"
```

---

## Acceptance

Run:

```bash
uv run pytest tests/hydrology tests/modeling -v
cd web
npm test -- --run src/__tests__/SpatialHeterogeneityPanel.test.ts src/__tests__/ModelPreparation.test.ts
npm run build
```

Acceptance requires:

- [ ] Spatial profile is deterministic and source-aware.
- [ ] Missing spatial dimensions stay unknown.
- [ ] No overall heterogeneity score directly chooses unit count.
- [ ] Candidate builder returns only deterministic unit schemes.
- [ ] Agent recommendation references an existing candidate and valid evidence.
- [ ] No LLM response can inject arbitrary polygon geometry.
- [ ] Existing boundary review/hash verification remains intact.
- [ ] Workbench displays spatial facts, candidates, recommendation and uncertainty.
- [ ] No complete multi-zone XAJ calibration is introduced by this plan.
