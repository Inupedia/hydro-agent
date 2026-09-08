# SP5 Candidate Scheme Isolation, Bounded Calibration, and Programmatic Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let XAJ perform one deterministic bounded calibration that creates a new immutable candidate Scheme, evaluate it against the base Scheme, and resolve it through a non-LLM Gate as `ACCEPT`, `KEEP`, or `ROLLBACK` without ever mutating the base Scheme.

**Architecture:** A static `CalibrationStrategyRegistry` declares the search budget; the XAJ calibration runtime samples candidate parameter vectors within the pinned upstream XAJ parameter ranges using a fixed seed. The optimizer writes candidate parameters as an output artifact only. Application code registers a new candidate Scheme, evaluates base/candidate on the same validation cases, and runs a pure `GateEvaluator`. Adoption changes a Task pointer later; it never edits an existing Scheme row or directory.

**Tech Stack:** Python 3.12, NumPy, pinned hydromodel XAJ, Pydantic 2, pytest 8, SP1 SandboxRunner, SP2 SQLite repository.

**Spec:** `docs/superpowers/specs/2026-09-08-execution-sandbox-design.md`

## Global Constraints

- Agent does not generate continuous XAJ parameter vectors.
- Optimizer may search only a frozen strategy and upstream-declared parameter bounds.
- Calibration and validation data are separate snapshot references.
- Optimizer success does not imply hydrologic improvement.
- Base Scheme is immutable and its `content_hash` must be byte-for-byte unchanged after ACCEPT, KEEP, or ROLLBACK.
- Gate executes in deterministic program code; LLM cannot bypass it.
- Guardrails are evaluated before primary-metric improvement.
- A valid but insufficient candidate resolves to `KEEP`; a guardrail violation resolves to `ROLLBACK`; only sufficient improvement resolves to `ACCEPT`.

---

## File Structure

```text
src/hydro_agent/optimization/__init__.py
src/hydro_agent/optimization/contracts.py
src/hydro_agent/optimization/strategies.py
src/hydro_agent/optimization/gate.py
src/hydro_agent/optimization/candidates.py
src/hydro_agent/models/xaj/calibrate_runtime.py
src/hydro_agent/evaluation/__init__.py
src/hydro_agent/evaluation/metrics.py
tests/optimization/test_strategies.py
tests/optimization/test_gate.py
tests/optimization/test_candidates.py
tests/models/xaj/test_calibrate_runtime.py
tests/evaluation/test_metrics.py
tests/integration/test_xaj_candidate_rollback.py
```

### Task 1: Define frozen optimization, metric, and Gate contracts

**Files:**
- Create: `src/hydro_agent/optimization/__init__.py`
- Create: `src/hydro_agent/optimization/contracts.py`
- Create: `src/hydro_agent/evaluation/__init__.py`
- Test: `tests/optimization/test_gate.py`

**Interfaces:**
- Produces: `CalibrationStrategy`, `LeadMetrics`, `EvaluationBundle`, `GatePolicy`, `GateDecision`.

- [ ] **Step 1: Write failing contract tests**

```python
# tests/optimization/test_gate.py
from hydro_agent.optimization.contracts import CalibrationStrategy, GatePolicy


def test_calibration_strategy_has_hard_budget_and_seed():
    strategy = CalibrationStrategy(
        strategy_id="xaj-bounded-v1",
        max_candidates=32,
        random_seed=20260908,
        objective="nse",
    )
    assert strategy.max_candidates == 32
    assert strategy.random_seed == 20260908


def test_gate_policy_requires_explicit_thresholds():
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
    )
    assert policy.min_primary_delta == 0.01
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/optimization/test_gate.py -k 'strategy or policy' -v`

Expected: FAIL because contracts are missing.

- [ ] **Step 3: Implement frozen contracts**

```python
GateStatus = Literal["ACCEPT", "KEEP", "ROLLBACK"]

class CalibrationStrategy(FrozenModel):
    strategy_id: str
    max_candidates: int = Field(ge=1, le=500)
    random_seed: int
    objective: Literal["nse"]

class LeadMetrics(FrozenModel):
    lead: Literal[1, 2, 3]
    nse: float
    mae: float
    bias: float
    high_flow_mae: float

class EvaluationBundle(FrozenModel):
    scheme_id: str
    leads: tuple[LeadMetrics, LeadMetrics, LeadMetrics]
    primary_score: float

class GatePolicy(FrozenModel):
    min_primary_delta: float
    max_single_lead_drop: float = Field(ge=0)
    max_high_flow_mae_relative_increase: float = Field(ge=0)

class GateDecision(FrozenModel):
    status: GateStatus
    base_scheme_id: str
    candidate_scheme_id: str
    reasons: tuple[str, ...]
    primary_delta: float
```

No threshold defaults: a Task/config must provide the policy explicitly.

- [ ] **Step 4: Run contract tests**

Run: `uv run pytest tests/optimization/test_gate.py -k 'strategy or policy' -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/optimization src/hydro_agent/evaluation tests/optimization/test_gate.py
git commit -m "feat: define optimization and gate contracts"
```

### Task 2: Add deterministic hydrologic metrics and lead-wise evaluation

**Files:**
- Create: `src/hydro_agent/evaluation/metrics.py`
- Test: `tests/evaluation/test_metrics.py`

**Interfaces:**
- Produces: `nse(obs, sim)`, `mae(obs, sim)`, `bias(obs, sim)`, `high_flow_mae(obs, sim, quantile=0.9)`, `build_evaluation_bundle(...)`.

- [ ] **Step 1: Write failing formula tests**

```python
# tests/evaluation/test_metrics.py
import numpy as np
import pytest
from hydro_agent.evaluation.metrics import nse, mae, bias


def test_metrics_match_hand_calculation():
    obs = np.array([1.0, 2.0, 3.0])
    sim = np.array([1.0, 2.0, 2.0])
    assert mae(obs, sim) == pytest.approx(1.0 / 3.0)
    assert bias(obs, sim) == pytest.approx(-1.0 / 6.0)
    expected_nse = 1.0 - 1.0 / 2.0
    assert nse(obs, sim) == pytest.approx(expected_nse)
```

Add tests that NSE rejects fewer than two finite observations and that all metrics reject mismatched shapes/NaN.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/evaluation/test_metrics.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement formulas**

Use:

```python
NSE = 1 - sum((obs - sim)**2) / sum((obs - mean(obs))**2)
MAE = mean(abs(obs - sim))
Bias = sum(sim - obs) / sum(obs)
```

For `high_flow_mae`, compute the 0.9 quantile from observed values and MAE only where `obs >= threshold`. `build_evaluation_bundle()` groups validation records by lead, computes the four metrics, and sets `primary_score` to the equal-weight mean of lead-1/2/3 NSE.

- [ ] **Step 4: Run metrics tests**

Run: `uv run pytest tests/evaluation/test_metrics.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/evaluation/metrics.py tests/evaluation/test_metrics.py
git commit -m "feat: add deterministic forecast metrics"
```

### Task 3: Freeze a static XAJ bounded-search strategy registry

**Files:**
- Create: `src/hydro_agent/optimization/strategies.py`
- Test: `tests/optimization/test_strategies.py`

**Interfaces:**
- Produces: `CalibrationStrategyRegistry.get("xaj-bounded-v1")`.

- [ ] **Step 1: Write failing registry test**

```python
# tests/optimization/test_strategies.py
import pytest
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry


def test_xaj_strategy_is_frozen_and_unknown_strategy_fails():
    registry = CalibrationStrategyRegistry()
    strategy = registry.get("xaj-bounded-v1")
    assert strategy.max_candidates == 32
    assert strategy.random_seed == 20260908
    with pytest.raises(KeyError):
        registry.get("llm-made-up-search")
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/optimization/test_strategies.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement one milestone strategy**

```python
XAJ_BOUNDED_V1 = CalibrationStrategy(
    strategy_id="xaj-bounded-v1",
    max_candidates=32,
    random_seed=20260908,
    objective="nse",
)
```

Registry contains only this strategy in SP5. Bounds are read from the pinned upstream `get_model_param_config("xaj", ...)`; the Agent cannot override them.

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/optimization/test_strategies.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/optimization/strategies.py tests/optimization/test_strategies.py
git commit -m "feat: freeze bounded XAJ calibration strategy"
```

### Task 4: Implement XAJ bounded calibration as a sandbox capability

**Files:**
- Create: `src/hydro_agent/models/xaj/calibrate_runtime.py`
- Modify: `src/hydro_agent/models/xaj/adapter.py`
- Test: `tests/models/xaj/test_calibrate_runtime.py`

**Interfaces:**
- Consumes: base `scheme.json`, calibration `forcing.csv` + observed `streamflow.csv`, strategy id.
- Produces: `output/candidate-scheme.json`, `output/calibration-result.json`.

- [ ] **Step 1: Write failing deterministic calibration test**

```python
# tests/models/xaj/test_calibrate_runtime.py

def test_bounded_calibration_is_deterministic(calibration_workspace):
    first = run_calibration_copy(calibration_workspace, "a")
    second = run_calibration_copy(calibration_workspace, "b")
    assert first["strategy_id"] == "xaj-bounded-v1"
    assert first["candidate_parameters"] == second["candidate_parameters"]
    assert first["evaluated_candidates"] == 32
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/models/xaj/test_calibrate_runtime.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement exact bounded search**

Algorithm:

1. load upstream XAJ parameter ranges from `get_model_param_config("xaj", {"source_type": "sources", "source_book": "HF"})`;
2. candidate 0 is the base parameter vector;
3. generate 31 additional vectors with `numpy.random.default_rng(20260908).uniform(low, high)` independently within each upstream range;
4. run XAJ on the calibration period for each vector;
5. convert runoff to m³/s using basin area;
6. score against observed streamflow with `nse()` after warmup;
7. select highest finite NSE; ties choose the base vector, then lexicographically earliest candidate index;
8. write candidate parameters but never edit `input/scheme/scheme.json`.

`XajRuntimeAdapter.command()` routes `capability="calibrate"` to `python -m hydro_agent.models.xaj.calibrate_runtime` and `forecast` to the existing runtime.

- [ ] **Step 4: Run calibration tests**

Run: `uv run pytest tests/models/xaj/test_calibrate_runtime.py -v`

Expected: PASS and base input file SHA-256 unchanged before/after.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/models/xaj/calibrate_runtime.py src/hydro_agent/models/xaj/adapter.py tests/models/xaj/test_calibrate_runtime.py
git commit -m "feat: add bounded XAJ calibration runtime"
```

### Task 5: Register calibration output as a new immutable candidate Scheme

**Files:**
- Create: `src/hydro_agent/optimization/candidates.py`
- Test: `tests/optimization/test_candidates.py`

**Interfaces:**
- Consumes: base Scheme record + successful calibration payload.
- Produces: `CandidateSchemeService.register_candidate(...) -> scheme_id`.

- [ ] **Step 1: Write failing immutability test**

```python
# tests/optimization/test_candidates.py

def test_candidate_registration_never_changes_base_scheme(seeded_repository, candidate_service, calibration_payload):
    before = seeded_repository.get_scheme("scheme-base").content_hash
    candidate_id = candidate_service.register_candidate(
        base_scheme_id="scheme-base",
        action_run_id="cal-run-1",
        calibration_payload=calibration_payload,
    )
    after = seeded_repository.get_scheme("scheme-base").content_hash
    candidate = seeded_repository.get_scheme(candidate_id)
    assert before == after
    assert candidate.status == "candidate"
    assert candidate.scheme_id != "scheme-base"
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/optimization/test_candidates.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement candidate registration**

Candidate id format:

```text
{base_scheme_id}--candidate--{action_run_id}
```

Candidate config is a deep copy of base config with only `parameters` replaced from the calibration payload and provenance fields added:

```json
{"base_scheme_id":"...","created_by_action_run_id":"...","strategy_id":"xaj-bounded-v1"}
```

Compute canonical JSON SHA-256 and call SP2 `create_scheme(status="candidate")`. Never expose an update method.

- [ ] **Step 4: Run candidate tests**

Run: `uv run pytest tests/optimization/test_candidates.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/optimization/candidates.py tests/optimization/test_candidates.py
git commit -m "feat: register immutable candidate schemes"
```

### Task 6: Implement pure Gate precedence and resolution

**Files:**
- Create: `src/hydro_agent/optimization/gate.py`
- Modify: `tests/optimization/test_gate.py`

**Interfaces:**
- Produces: `GateEvaluator.evaluate(base, candidate, policy) -> GateDecision`.

- [ ] **Step 1: Write failing Gate-precedence tests**

```python
from hydro_agent.optimization.gate import GateEvaluator


def test_guardrail_failure_rolls_back_even_when_average_improves(base_eval, candidate_with_bad_lead, gate_policy):
    decision = GateEvaluator().evaluate(base_eval, candidate_with_bad_lead, gate_policy)
    assert decision.status == "ROLLBACK"
    assert "lead_guardrail" in decision.reasons


def test_small_valid_improvement_keeps_base(base_eval, candidate_small_gain, gate_policy):
    decision = GateEvaluator().evaluate(base_eval, candidate_small_gain, gate_policy)
    assert decision.status == "KEEP"


def test_sufficient_safe_improvement_accepts(base_eval, candidate_good, gate_policy):
    decision = GateEvaluator().evaluate(base_eval, candidate_good, gate_policy)
    assert decision.status == "ACCEPT"
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/optimization/test_gate.py -k 'guardrail or improvement' -v`

Expected: FAIL.

- [ ] **Step 3: Implement Gate order**

Evaluation order:

1. For each lead, `candidate.nse - base.nse < -max_single_lead_drop` => `ROLLBACK`.
2. For each lead, if base high-flow MAE > 0 and `(candidate - base) / base > max_high_flow_mae_relative_increase` => `ROLLBACK`.
3. `primary_delta = candidate.primary_score - base.primary_score`.
4. If `primary_delta >= min_primary_delta` => `ACCEPT`.
5. Else => `KEEP`.

Return all triggered reasons; never call an LLM.

- [ ] **Step 4: Run Gate tests**

Run: `uv run pytest tests/optimization/test_gate.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/optimization/gate.py tests/optimization/test_gate.py
git commit -m "feat: add programmatic candidate gate"
```

### Task 7: Prove a real calibration candidate can be rolled back without base mutation

**Files:**
- Create: `tests/integration/test_xaj_candidate_rollback.py`

**Interfaces:**
- Consumes: SP3/4 real Lowman data, SP1/2/5 services.
- Produces: end-to-end calibration run + candidate Scheme + deterministic ROLLBACK + unchanged base hash.

- [ ] **Step 1: Write the integration test**

```python

def test_real_candidate_rollback_preserves_base(real_calibration_flow):
    base_hash = real_calibration_flow.base_scheme.content_hash
    candidate, base_eval, candidate_eval = real_calibration_flow.run()
    strict_policy = GatePolicy(
        min_primary_delta=999.0,
        max_single_lead_drop=0.0,
        max_high_flow_mae_relative_increase=0.0,
    )
    decision = GateEvaluator().evaluate(base_eval, candidate_eval, strict_policy)
    assert decision.status in {"KEEP", "ROLLBACK"}
    assert real_calibration_flow.repository.get_scheme("scheme-base").content_hash == base_hash
    assert candidate.scheme_id != "scheme-base"
```

The policy is intentionally strict to prove non-adoption; the test does not claim calibration quality.

- [ ] **Step 2: Run and inspect failure points**

Run: `HYDRO_AGENT_LOWMAN_SNAPSHOT=... uv run pytest tests/integration/test_xaj_candidate_rollback.py -v`

Expected before wiring: FAIL at the first missing orchestration boundary, not by mutating the base scheme.

- [ ] **Step 3: Wire existing SP1-SP5 services only**

Do not add a new orchestration framework. The fixture creates one calibration ActionRun, runs the XAJ calibration sandbox, registers the candidate, runs predeclared validation cases for both schemes, builds two `EvaluationBundle`s, and invokes the Gate.

- [ ] **Step 4: Run all optimization integration tests**

Run: `HYDRO_AGENT_LOWMAN_SNAPSHOT=... uv run pytest tests/integration/test_xaj_candidate_rollback.py -v`

Expected: PASS and base scheme SHA/content hash unchanged.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_xaj_candidate_rollback.py
git commit -m "test: prove candidate rollback isolation"
```

## SP5 Acceptance

```bash
uv run pytest tests/evaluation tests/optimization tests/models/xaj/test_calibrate_runtime.py -v
HYDRO_AGENT_LOWMAN_SNAPSHOT=... uv run pytest tests/integration/test_xaj_candidate_rollback.py -v
```

Acceptance requires deterministic bounded search, immutable candidate creation, explicit Gate thresholds, and a non-adoption path that leaves the base Scheme unchanged.