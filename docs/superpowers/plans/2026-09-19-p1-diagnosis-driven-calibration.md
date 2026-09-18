# P1 诊断驱动率定闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 P0 完整过程证据基础上，让 Agent 形成可证伪的过程假设和调整方向，由确定性敏感性实验验证方向，再交给 DDS/SCE-UA 精调，并通过 Top-K 行为候选和独立 development evidence 决定采用/保留/回退。

**Architecture:** 继续坚持“Agent 决定 WHAT/WHY，数值工具决定具体参数值”。新增方向假设和 directional probe，扩展候选管理为 behavioral candidate set；Research Adoption Gate 与 GB/T 标准评价分离。Experience 只记录实验事实与假设结果，不把一次成功自动晋升为通用规则。

**Tech Stack:** Python 3.12、Pydantic、NumPy、pytest、现有 Morris/DDS/SCE-UA、SQLite persistence、现有 Experience 子系统

**Spec:** `docs/superpowers/specs/2026-09-19-hydrologic-process-diagnosis-and-spatial-units-design.md`

## Global Constraints

- LLM 不得直接输出并执行连续参数值。
- LLM 只能选择过程层、参数组、方向、优化策略与预算。
- 参数方向必须经过确定性扰动/Morris 证据验证后才能作为局部精调依据。
- DDS/SCE-UA 保留；本计划不新增多目标优化器。
- 不把多个指标硬编码成一个新的“超级综合分”作为唯一采用依据。
- calibration 产生候选；development 只比较/选优，不新增参数搜索。
- final-test 继续完全隔离，不能进入假设形成、方向验证、候选排序。
- 标准评价与科研采用分离；缺失 GB/T 评价不能抹除 research evidence。
- 单次实验成功只产生 case evidence，不能自动升级为 validated rule。

---

## File Structure

- Modify `src/hydro_agent/optimization/calibration_scientist.py`：方向假设契约与计划。
- Create `src/hydro_agent/optimization/directional_probe.py`：确定性方向验证。
- Modify `src/hydro_agent/optimization/morris.py`：仅补方向证据适配，不改核心算法语义。
- Modify `src/hydro_agent/optimization/candidates.py`：Behavioral Candidate Set。
- Modify `src/hydro_agent/models/shared_calibrate_runtime.py`：保留 Top-K 及完整证据。
- Modify `src/hydro_agent/optimization/gate.py`：Research Adoption Gate。
- Create `src/hydro_agent/evaluation/standard_profile.py`：标准评价 profile 契约。
- Modify `src/hydro_agent/evaluation/gbt22482.py`：作为 StandardEvaluator 输出，不再决定 research gate。
- Modify `src/hydro_agent/experience/` 中现有 case/feedback 落点：记录 hypothesis outcome。
- Tests 使用现有 `tests/optimization`、`tests/evaluation`、`tests/agent` 与 `tests/experience`。

---

### Task 1: Directional Diagnosis Hypothesis Contracts

**Files:**
- Modify: `src/hydro_agent/optimization/calibration_scientist.py`
- Modify: `tests/optimization/test_calibration_scientist.py`
- Modify: `tests/agent/test_calibration_scientist_provider.py`

**Interfaces:**
- Consumes: P0 `HydrographDiagnosisPacket`.
- Produces enriched `DiagnosisHypothesis` with direction semantics.

- [ ] **Step 1: Add failing contract test**

```python
def test_diagnosis_hypothesis_carries_direction_without_raw_parameter_values():
    hypothesis = DiagnosisHypothesis(
        hypothesis_id="routing-too-slow",
        confidence=0.82,
        phenomenon="多场洪水峰现偏晚且洪量接近无偏",
        process_layer="routing",
        parameter_groups=("routing",),
        direction="accelerate_routing",
        direction_confidence=0.78,
        direction_evidence_ids=("event-001", "event-004"),
        verification_required=True,
    )

    dumped = hypothesis.model_dump()
    assert dumped["direction"] == "accelerate_routing"
    assert "parameter_values" not in dumped
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/optimization/test_calibration_scientist.py -k direction -v
```

Expected: FAIL because direction fields do not exist.

- [ ] **Step 3: Add direction types**

Use:

```python
AdjustmentDirection = Literal[
    "increase_water_loss",
    "decrease_water_loss",
    "increase_runoff_response",
    "decrease_runoff_response",
    "accelerate_routing",
    "delay_routing",
    "increase_fast_component",
    "increase_slow_component",
    "unknown",
]
```

Extend `DiagnosisHypothesis` with:

```python
diagnostic_signature: tuple[str, ...] = ()
direction: AdjustmentDirection = "unknown"
direction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
direction_evidence_ids: tuple[str, ...] = ()
verification_required: bool = True
```

- [ ] **Step 4: Make `form_diagnosis_hypothesis()` packet-aware**

Rules:

1. Prefer repeated event evidence over one isolated event.
2. Water-balance near neutral + repeated late peaks should allow `routing/accelerate_routing`.
3. Water-balance bias dominates while timing is acceptable should prefer evap/runoff process hypotheses.
4. Conflicting events must populate contradictions and lower confidence.
5. No matching signature returns `direction="unknown"`, not a guessed direction.

- [ ] **Step 5: Run focused tests**

```bash
uv run pytest tests/optimization/test_calibration_scientist.py tests/agent/test_calibration_scientist_provider.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hydro_agent/optimization/calibration_scientist.py tests/optimization/test_calibration_scientist.py tests/agent/test_calibration_scientist_provider.py
git commit -m "feat: add directional calibration hypotheses"
```

---

### Task 2: Deterministic Directional Probe Before Numerical Refinement

**Files:**
- Create: `src/hydro_agent/optimization/directional_probe.py`
- Create: `tests/optimization/test_directional_probe.py`
- Modify: `src/hydro_agent/optimization/contracts.py`

**Interfaces:**
- Consumes:
  - baseline parameters;
  - active parameter names;
  - absolute/search bounds;
  - scalar score function;
  - process-evidence function;
  - requested `AdjustmentDirection`.
- Produces `DirectionalProbeResult`.

- [ ] **Step 1: Write failing synthetic probe test**

```python
def test_probe_supports_direction_when_positive_perturbation_improves_expected_signature():
    result = run_directional_probe(
        baseline={"L": 3.0},
        bounds={"L": (0.0, 10.0)},
        parameters=("L",),
        relative_step=0.10,
        evaluate=synthetic_routing_evaluator,
        requested_direction="accelerate_routing",
    )

    assert result.status == "supported"
    assert result.parameter_effects
    assert result.supporting_parameters
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/optimization/test_directional_probe.py -v
```

- [ ] **Step 3: Implement result contract**

```python
class ParameterDirectionalEffect(FrozenModel):
    parameter: str
    negative_delta: float | None = None
    positive_delta: float | None = None
    expected_signature_change: dict[str, float] = Field(default_factory=dict)


class DirectionalProbeResult(FrozenModel):
    requested_direction: str
    status: Literal["supported", "refuted", "inconclusive"]
    parameter_effects: tuple[ParameterDirectionalEffect, ...]
    supporting_parameters: tuple[str, ...] = ()
    contradictory_parameters: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
```

- [ ] **Step 4: Implement bounded symmetric perturbation**

For each active parameter:

```text
step = relative_step * (upper - lower)
negative = max(lower, baseline - step)
positive = min(upper, baseline + step)
```

Evaluate both sides with the same deterministic model/evidence path. Never probe outside absolute bounds.

- [ ] **Step 5: Define support semantics**

Support must be based on expected process signature, not only objective score. Example for `accelerate_routing`:

- peak timing absolute lag decreases;
- volume error does not materially worsen beyond configured guardrail;
- high-flow error does not materially worsen beyond configured guardrail.

If different active parameters disagree, return `inconclusive` unless configured majority/evidence threshold is met.

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/optimization/test_directional_probe.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hydro_agent/optimization/directional_probe.py src/hydro_agent/optimization/contracts.py tests/optimization/test_directional_probe.py
git commit -m "feat: verify calibration directions deterministically"
```

---

### Task 3: Integrate Direction Verification With Morris and Calibration Plan

**Files:**
- Modify: `src/hydro_agent/optimization/calibration_scientist.py`
- Modify: `src/hydro_agent/optimization/morris.py`
- Modify: `tests/optimization/test_morris.py`
- Modify: `tests/optimization/test_calibration_scientist.py`

**Interfaces:**
- Consumes `DirectionalProbeResult` and existing Morris screening.
- Produces a legal `CalibrationPlan` only after verification when `verification_required=True`.

- [ ] **Step 1: Write failing planner test**

```python
def test_refuted_direction_forces_rediagnosis_instead_of_optimizer_search():
    plan_or_review = plan_from_hypothesis(
        hypothesis,
        diagnosis,
        direction_verification=DirectionalProbeResult(
            requested_direction="accelerate_routing",
            status="refuted",
            parameter_effects=(),
        ),
    )

    assert plan_or_review.next_step == "re-diagnose"
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/optimization/test_calibration_scientist.py -k refuted_direction -v
```

- [ ] **Step 3: Add verification state to plan contract**

Extend `CalibrationPlan`:

```python
direction_verification_status: Literal[
    "not_required", "supported", "refuted", "inconclusive"
] = "not_required"
direction_evidence_ids: tuple[str, ...] = ()
```

A `refuted` result must not silently proceed with the same hypothesis.

- [ ] **Step 4: Reuse Morris as parameter-importance evidence**

Do not alter Morris algorithm math. Add an adapter that can map active parameter ranking to the current process hypothesis and record:

```text
parameter
mu_star
sigma
effects_count
direction_probe_status
```

- [ ] **Step 5: Run optimization regression**

```bash
uv run pytest tests/optimization/test_morris.py tests/optimization/test_calibration_scientist.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hydro_agent/optimization/calibration_scientist.py src/hydro_agent/optimization/morris.py tests/optimization/test_morris.py tests/optimization/test_calibration_scientist.py
git commit -m "feat: gate numerical search on verified hypotheses"
```

---

### Task 4: Behavioral Candidate Set Instead of Single Best Parameter Vector

**Files:**
- Modify: `src/hydro_agent/optimization/candidates.py`
- Modify: `src/hydro_agent/models/shared_calibrate_runtime.py`
- Modify: `tests/optimization/test_candidates.py`
- Modify: `tests/models/test_shared_calibrate_runtime.py` if present; otherwise add coverage to the model-specific calibration runtime tests already used by the repository.

**Interfaces:**
- Consumes persisted evaluation cache entries.
- Produces `BehavioralCandidateSet` with default `max_candidates=8`.

- [ ] **Step 1: Write failing candidate diversity test**

```python
def test_behavioral_set_keeps_near_optimal_parameter_distinct_candidates():
    result = select_behavioral_candidates(
        candidates=[
            candidate("a", score=0.86, params={"K": 0.8, "L": 2.0}),
            candidate("b", score=0.85, params={"K": 1.1, "L": 1.0}),
            candidate("c", score=0.70, params={"K": 0.81, "L": 2.01}),
        ],
        max_candidates=8,
        objective_tolerance=0.02,
        min_parameter_distance=0.05,
    )

    assert [item.candidate_id for item in result.items] == ["a", "b"]
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/optimization/test_candidates.py -k behavioral -v
```

- [ ] **Step 3: Add contracts**

```python
class BehavioralCandidate(FrozenModel):
    candidate_id: str
    parameters: dict[str, float]
    objective_value: float
    process_evidence: dict[str, Any]
    parameter_distance_from_best: float


class BehavioralCandidateSet(FrozenModel):
    objective_name: str
    objective_best: float
    objective_tolerance: float
    items: tuple[BehavioralCandidate, ...]
```

- [ ] **Step 4: Select candidates from existing evaluation cache**

Selection rules:

1. include the numerical best;
2. keep candidates within configured objective tolerance;
3. remove near-duplicate parameter vectors using normalized parameter-space distance;
4. cap at `max_candidates`;
5. attach deterministic process evidence for each candidate;
6. do not inspect development/final-test during this selection.

- [ ] **Step 5: Persist candidate set in runtime output**

Add:

```json
{
  "behavioral_candidates": {
    "objective_name": "nse",
    "objective_best": 0.86,
    "objective_tolerance": 0.02,
    "items": []
  }
}
```

Keep existing `candidate_parameters` and `objective_value` for API compatibility.

- [ ] **Step 6: Run regression**

```bash
uv run pytest tests/optimization/test_candidates.py tests/models -k calibrat -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hydro_agent/optimization/candidates.py src/hydro_agent/models/shared_calibrate_runtime.py tests/optimization/test_candidates.py tests/models
git commit -m "feat: retain behavioral calibration candidates"
```

---

### Task 5: Research Adoption Gate Separate From Standard Evaluation

**Files:**
- Modify: `src/hydro_agent/optimization/contracts.py`
- Modify: `src/hydro_agent/optimization/gate.py`
- Modify: `tests/optimization/test_gate.py`
- Create: `src/hydro_agent/evaluation/standard_profile.py`
- Create: `tests/evaluation/test_standard_profile.py`
- Modify: `src/hydro_agent/evaluation/gbt22482.py`
- Modify: `tests/evaluation/test_gbt22482.py`

**Interfaces:**
- Produces independently:
  - `ResearchGateDecision`
  - `StandardEvaluationResult`

- [ ] **Step 1: Write failing gate separation test**

```python
def test_missing_standard_evaluation_does_not_block_research_adoption():
    decision = ResearchGateEvaluator().evaluate(
        base=base,
        candidate=better_candidate,
        policy=policy,
        event_comparison=event_comparison,
    )

    assert decision.adoption_status == "ADOPT"
    assert decision.research_qualification == "QUALIFIED"
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/optimization/test_gate.py -k missing_standard -v
```

- [ ] **Step 3: Split contracts**

Use:

```python
class ResearchGateDecision(FrozenModel):
    status: GateStatus
    adoption_status: AdoptionStatus
    research_qualification: QualificationStatus
    primary_delta: float
    reasons: tuple[str, ...]
    event_guardrail_reasons: tuple[str, ...] = ()


class StandardEvaluationResult(FrozenModel):
    profile_id: str
    standard_id: str
    status: Literal["evaluated", "not_evaluated", "not_applicable"]
    grade: str | None = None
    summary: str | None = None
```

Keep a compatibility adapter to existing `GateDecision` during migration.

- [ ] **Step 4: Add event guardrails**

Research gate must consider, when enough events exist:

- median absolute peak error;
- median absolute timing error;
- median absolute volume error;
- number/fraction of materially worsened events.

Do not collapse them to one hidden score. Each failed guardrail gets its own reason code.

- [ ] **Step 5: Wrap GB/T evaluator as standard profile**

`gbt22482.py` continues computing its current report. New adapter returns:

```python
StandardEvaluationResult(
    profile_id="operational_gbt",
    standard_id="GB/T 22482",
    status="evaluated",
    grade=report.scheme_grade,
    summary=report.summary,
)
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/optimization/test_gate.py tests/evaluation/test_standard_profile.py tests/evaluation/test_gbt22482.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hydro_agent/optimization/contracts.py src/hydro_agent/optimization/gate.py src/hydro_agent/evaluation/standard_profile.py src/hydro_agent/evaluation/gbt22482.py tests/optimization/test_gate.py tests/evaluation/test_standard_profile.py tests/evaluation/test_gbt22482.py
git commit -m "feat: separate research adoption from standard evaluation"
```

---

### Task 6: Persist Hypothesis Outcome Into Experience Cases

**Files:**
- Modify: existing case/feedback modules under `src/hydro_agent/experience/` selected after reading current contracts.
- Add/Modify: corresponding tests under `tests/experience/`.

**Interfaces:**
- Consumes:
  - `DiagnosisHypothesis`
  - `DirectionalProbeResult`
  - `ResearchGateDecision`
  - process evidence IDs
- Produces an experience case with hypothesis outcome:
  - `supported`
  - `refuted`
  - `inconclusive`

- [ ] **Step 1: Inspect exact experience case contract before editing**

Run:

```bash
find src/hydro_agent/experience -maxdepth 2 -type f -print
find tests/experience -maxdepth 2 -type f -print
```

Choose the existing case type that already stores experiment evidence; do not create a parallel memory subsystem.

- [ ] **Step 2: Add failing test to the selected existing test file**

The test must assert the persisted case includes:

```python
assert case.hypothesis_id == "routing-too-slow"
assert case.hypothesis_status == "supported"
assert "event-001" in case.evidence_refs
assert case.direction_verification_status == "supported"
```

- [ ] **Step 3: Run RED**

Run the exact selected test file with `uv run pytest ... -v`.

- [ ] **Step 4: Extend existing case contract minimally**

Required new fields:

```text
hypothesis_id
hypothesis_status
diagnostic_signature
direction
direction_verification_status
evidence_refs
```

Do not auto-promote case maturity from a single result.

- [ ] **Step 5: Add negative-case test**

A refuted hypothesis must be persisted rather than discarded.

- [ ] **Step 6: Run experience regression**

```bash
uv run pytest tests/experience -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hydro_agent/experience tests/experience
git commit -m "feat: learn from calibration hypothesis outcomes"
```

---

## Acceptance

Run:

```bash
uv run pytest tests/optimization tests/evaluation tests/agent tests/experience -v
```

Acceptance requires:

- [ ] Agent hypotheses include direction but no raw executable parameter vector.
- [ ] Direction can be supported/refuted/inconclusive by deterministic model experiments.
- [ ] Refuted directions force re-diagnosis rather than silently entering DDS/SCE-UA.
- [ ] DDS/SCE-UA remain the concrete parameter search engines.
- [ ] Calibration retains multiple near-optimal, parameter-distinct behavioral candidates.
- [ ] Development evaluates/selects candidates without opening a new calibration search.
- [ ] Research adoption is not blocked merely because GB/T evaluation is missing.
- [ ] GB/T evaluation is still available as an independent standard profile.
- [ ] Experience stores successful, failed and inconclusive hypotheses.
- [ ] final-test evidence is not consumed by any step above.
