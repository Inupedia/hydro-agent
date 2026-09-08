# SP3B OpenHydroNet RuntimeAdapter and Local Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenHydroNet as the second model behind the same `RuntimeAdapter`/Sandbox contracts, prove lead-1/2/3 inference on `camels_13235000`, and support only the frozen local adaptation strategies `KEEP`, `HEAD`, `STATIC`, and `STATIC_HEAD` with trainable-parameter verification.

**Architecture:** Pin `google-research/flood-forecasting` to commit `828dfc5a66f4e6f2c86b09d500e4547c4d92ed25`. A Hydro-Agent wrapper generates an upstream-compatible run/config directory from immutable Scheme + DataSnapshot inputs, then invokes the upstream `googlehydrology.run` entrypoint in `infer` or `finetune` mode inside the Sandbox. Inference/adaptation outputs are normalized into Hydro-Agent `result.json`; the wrapper never downloads data or weights during execution. Adaptation creates a candidate checkpoint artifact only; SP5-style candidate registration/Gate remains outside the runtime.

**Tech Stack:** Python 3.12, PyTorch, xarray/dask dependencies required by pinned flood-forecasting, Pydantic 2, pytest 8, SP1 SandboxRunner, SP2 persistence, SP4 snapshot rules, SP4A application services.

**Spec:** `docs/superpowers/specs/2026-09-08-execution-sandbox-design.md`

## Global Constraints

- Upstream source is pinned to commit `828dfc5a66f4e6f2c86b09d500e4547c4d92ed25`; never install moving `main` for accepted runs.
- Record upstream Apache-2.0 license and pinned commit in `THIRD_PARTY.md`.
- The first live device is CPU; MPS is allowed only after a dedicated reproducibility smoke test passes.
- Runtime has no network access and receives all weights/config/data through materialized inputs.
- `run infer --run-dir <dir> --period test --gpu -1` is the CPU inference entrypoint.
- `run finetune --config-file <config> --gpu -1` is the CPU fine-tuning entrypoint.
- Allowed adaptation strategies are frozen: `KEEP`, `HEAD`, `STATIC`, `STATIC_HEAD`.
- `HEAD` trains only parameters whose names start with `head.`.
- `STATIC` trains only parameters whose names start with `static_embedding_fc.`.
- `STATIC_HEAD` trains the union of those two prefixes.
- Agent does not invent learning rate, epoch count, module names, or arbitrary checkpoint paths.
- Public pretrained weights with training coverage overlapping evaluation dates cannot be used to claim independent temporal generalization; post-training-period or explicitly non-independent evaluation must be labeled accordingly.

---

## File Structure

```text
pyproject.toml
THIRD_PARTY.md
src/hydro_agent/models/openhydronet/__init__.py
src/hydro_agent/models/openhydronet/contracts.py
src/hydro_agent/models/openhydronet/adapter.py
src/hydro_agent/models/openhydronet/config.py
src/hydro_agent/models/openhydronet/infer_runtime.py
src/hydro_agent/models/openhydronet/adapt_runtime.py
src/hydro_agent/models/openhydronet/weights.py
src/hydro_agent/optimization/ohn_strategies.py
src/hydro_agent/data/openhydronet.py
tests/models/openhydronet/test_contracts.py
tests/models/openhydronet/test_config.py
tests/models/openhydronet/test_infer_runtime.py
tests/models/openhydronet/test_adapt_runtime.py
tests/optimization/test_ohn_strategies.py
tests/data/test_openhydronet_snapshot.py
tests/integration/test_openhydronet_sandbox_forecast.py
tests/integration/test_openhydronet_adaptation_isolation.py
```

### Task 1: Pin upstream OpenHydroNet implementation and define Scheme/strategy contracts

**Files:**
- Modify: `pyproject.toml`
- Modify: `THIRD_PARTY.md`
- Create: `src/hydro_agent/models/openhydronet/__init__.py`
- Create: `src/hydro_agent/models/openhydronet/contracts.py`
- Create: `src/hydro_agent/optimization/ohn_strategies.py`
- Test: `tests/models/openhydronet/test_contracts.py`
- Test: `tests/optimization/test_ohn_strategies.py`

**Interfaces:**
- Produces: `OpenHydroNetScheme`, `OpenHydroNetAdaptationStrategy`, `OpenHydroNetStrategyRegistry`.

- [ ] **Step 1: Write failing strategy tests**

```python
# tests/optimization/test_ohn_strategies.py

def test_openhydronet_strategy_registry_is_closed():
    registry = OpenHydroNetStrategyRegistry()
    assert registry.get("KEEP").modules == ()
    assert registry.get("HEAD").modules == ("head",)
    assert registry.get("STATIC").modules == ("static_embedding_fc",)
    assert registry.get("STATIC_HEAD").modules == ("static_embedding_fc", "head")
    with pytest.raises(KeyError):
        registry.get("ALL_LAYERS")
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/models/openhydronet/test_contracts.py tests/optimization/test_ohn_strategies.py -v`

Expected: FAIL because OpenHydroNet package is missing.

- [ ] **Step 3: Add dependency lock and frozen contracts**

Add optional dependency:

```toml
openhydronet = [
  "googlehydrology @ git+https://github.com/google-research/flood-forecasting.git@828dfc5a66f4e6f2c86b09d500e4547c4d92ed25"
]
```

`OpenHydroNetScheme` fields:

```text
model_id = openhydronet
upstream_commit
base_run_artifact_id
checkpoint_artifact_id
scaler_artifact_ids
config_patch
lead_days exactly (1,2,3)
```

All artifact ids reference SP2 promoted immutable artifacts; raw local paths are not stored in Scheme config.

Freeze strategy definitions:

```python
KEEP = modules=(), epochs=0
HEAD = modules=("head",), epochs=5
STATIC = modules=("static_embedding_fc",), epochs=5
STATIC_HEAD = modules=("static_embedding_fc", "head"), epochs=5
```

Learning rate is a single repository config constant `1e-4` for this milestone; it is not an Agent field.

- [ ] **Step 4: Run contract tests**

Run: `uv sync --extra dev --extra openhydronet && uv run pytest tests/models/openhydronet/test_contracts.py tests/optimization/test_ohn_strategies.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml THIRD_PARTY.md src/hydro_agent/models/openhydronet src/hydro_agent/optimization/ohn_strategies.py tests/models/openhydronet/test_contracts.py tests/optimization/test_ohn_strategies.py
git commit -m "feat: lock OpenHydroNet model contracts"
```

### Task 2: Materialize the OpenHydroNet DataSnapshot contract from Caravan/MultiMet inputs

**Files:**
- Create: `src/hydro_agent/data/openhydronet.py`
- Create: `tests/data/test_openhydronet_snapshot.py`

**Interfaces:**
- Produces: `OpenHydroNetSnapshotMaterializer.build(context, source_root) -> Path` using SP4 availability policy.

- [ ] **Step 1: Write failing snapshot-role test**

```python
# tests/data/test_openhydronet_snapshot.py

def test_openhydronet_snapshot_declares_required_roles(ohn_snapshot):
    manifest = ohn_snapshot.manifest
    roles = {item.role for item in manifest.files}
    assert {"statics", "targets", "hindcast", "forecast"} <= roles
```

Add F-mode test asserting future `forecast` rows come only from a forecast release with `available_at <= issue_time`; future target streamflow is absent.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/data/test_openhydronet_snapshot.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement exact roles and source mapping**

For `camels_13235000`, materialize only the basin rows required by the pinned upstream configuration:

```text
input/snapshot/openhydronet/statics.*
input/snapshot/openhydronet/targets.*
input/snapshot/openhydronet/hindcast/*
input/snapshot/openhydronet/forecast/*
input/snapshot/openhydronet/snapshot-manifest.json
```

Use the same source semantics already declared in `数据源与实验数据协议.md`: Caravan targets/statics, Caravan MultiMet hindcast, and HRES/GraphCast forecast forcing. Apply SP4 `DataAccessPolicy` before writing files. Do not silently replace an unavailable HRES/GraphCast forecast with future ERA5 reanalysis in F mode.

- [ ] **Step 4: Run snapshot tests**

Run: `uv run pytest tests/data/test_openhydronet_snapshot.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/data/openhydronet.py tests/data/test_openhydronet_snapshot.py
git commit -m "feat: materialize OpenHydroNet snapshots"
```

### Task 3: Generate a pinned upstream run directory and inference config without mutating the base artifacts

**Files:**
- Create: `src/hydro_agent/models/openhydronet/config.py`
- Create: `src/hydro_agent/models/openhydronet/weights.py`
- Test: `tests/models/openhydronet/test_config.py`

**Interfaces:**
- Produces: `prepare_inference_run(workspace, scheme, snapshot) -> Path`.

- [ ] **Step 1: Write failing immutable-base test**

```python
# tests/models/openhydronet/test_config.py

def test_inference_run_is_workspace_copy_and_keeps_base_hashes(prepared_inputs, tmp_path):
    before = prepared_inputs.base_hashes()
    run_dir = prepare_inference_run(tmp_path, prepared_inputs.scheme, prepared_inputs.snapshot)
    assert (run_dir / "config.yml").is_file()
    assert prepared_inputs.base_hashes() == before
    assert str(tmp_path) in str(run_dir)
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/models/openhydronet/test_config.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement run-directory preparation**

Copy/hardlink only manifest-declared base-run files and checkpoint/scalers into `work/openhydronet/base-run/`. Generate a workspace-local `config.yml` by applying a closed config patch for basin id, snapshot paths, test period, `device: cpu`, and lead horizon. Reject any patch key not in the explicit allowlist.

Base artifact hashes are checked before and after execution.

- [ ] **Step 4: Run config tests**

Run: `uv run pytest tests/models/openhydronet/test_config.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/models/openhydronet/config.py src/hydro_agent/models/openhydronet/weights.py tests/models/openhydronet/test_config.py
git commit -m "feat: prepare OpenHydroNet sandbox runs"
```

### Task 4: Implement OpenHydroNet inference runtime and RuntimeAdapter

**Files:**
- Create: `src/hydro_agent/models/openhydronet/infer_runtime.py`
- Create: `src/hydro_agent/models/openhydronet/adapter.py`
- Test: `tests/models/openhydronet/test_infer_runtime.py`

**Interfaces:**
- Produces: `OpenHydroNetRuntimeAdapter` capabilities `validate`, `rebuild_state`, `forecast`, `adapt`.

- [ ] **Step 1: Write failing argv/normalization test**

```python
# tests/models/openhydronet/test_infer_runtime.py

def test_adapter_routes_forecast_to_hydro_agent_wrapper(request, workspace):
    adapter = OpenHydroNetRuntimeAdapter()
    argv = adapter.command(request.model_copy(update={"model_id": "openhydronet", "capability": "forecast"}), workspace)
    assert argv[:3] == [sys.executable, "-m", "hydro_agent.models.openhydronet.infer_runtime"]
```

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/models/openhydronet/test_infer_runtime.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement wrapper runtime**

The wrapper prepares the upstream run directory, then executes the pinned package entrypoint equivalent to:

```text
run infer --run-dir <workspace>/work/openhydronet/base-run --period test --gpu -1
```

Use `subprocess.run([...], shell=False)` from the wrapper only with static argv generated by Hydro-Agent. Locate the upstream inference xarray result through the generated run/evaluation directory, extract `camels_13235000` discharge simulation for the issue-time forecast horizon, normalize the first three leads into Hydro-Agent `output/result.json`, and reject NaN/Inf or missing lead values.

The outer SandboxRunner still owns timeout/log/resource capture.

- [ ] **Step 4: Run inference tests**

Run: `uv run pytest tests/models/openhydronet/test_infer_runtime.py -v`

Expected: PASS with fixture upstream run artifacts.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/models/openhydronet/infer_runtime.py src/hydro_agent/models/openhydronet/adapter.py tests/models/openhydronet/test_infer_runtime.py
git commit -m "feat: add OpenHydroNet sandbox inference"
```

### Task 5: Implement closed local-adaptation runtime with trainable-parameter audit

**Files:**
- Create: `src/hydro_agent/models/openhydronet/adapt_runtime.py`
- Test: `tests/models/openhydronet/test_adapt_runtime.py`

**Interfaces:**
- Consumes: base Scheme, training/validation snapshots, one registered adaptation strategy.
- Produces: candidate checkpoint artifact, `trainable_parameter_names`, training cost, validation result.

- [ ] **Step 1: Write failing module-isolation tests**

```python
# tests/models/openhydronet/test_adapt_runtime.py

def test_head_strategy_only_updates_head(adaptation_result):
    assert adaptation_result.strategy_id == "HEAD"
    assert adaptation_result.trainable_parameter_names
    assert all(name.startswith("head.") for name in adaptation_result.trainable_parameter_names)
    assert adaptation_result.non_target_changed_parameters == ()
```

Repeat for `STATIC` and `STATIC_HEAD` expected prefixes.

- [ ] **Step 2: Verify failure**

Run: `uv run pytest tests/models/openhydronet/test_adapt_runtime.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement adaptation config and weight audit**

Generate finetune config with:

```yaml
base_run_dir: <workspace-local-base-run>
is_finetuning: true
finetune_modules: [head]  # strategy-specific
epochs: 5
learning_rate: 0.0001
device: cpu
```

Invoke equivalent CPU command:

```text
run finetune --config-file <workspace>/work/openhydronet/finetune.yml --gpu -1
```

Before training, hash every named parameter tensor. After training, compare tensors. Fail with `contract_error` if any changed tensor is outside the strategy's allowed prefixes or if no target tensor changed for a non-KEEP strategy. Write candidate checkpoint only under `output/`.

- [ ] **Step 4: Run adaptation tests**

Run: `uv run pytest tests/models/openhydronet/test_adapt_runtime.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hydro_agent/models/openhydronet/adapt_runtime.py tests/models/openhydronet/test_adapt_runtime.py
git commit -m "feat: add bounded OpenHydroNet adaptation"
```

### Task 6: Prove real Lowman inference and one rejected/accepted candidate path through existing Gate semantics

**Files:**
- Create: `tests/integration/test_openhydronet_sandbox_forecast.py`
- Create: `tests/integration/test_openhydronet_adaptation_isolation.py`

**Interfaces:**
- Consumes: real pinned pretrained artifacts and legal Lowman OpenHydroNet snapshot.
- Produces: one lead-1/2/3 Forecast and one audited adaptation candidate.

- [ ] **Step 1: Write real integration tests behind explicit artifact env vars**

```python
REAL_OHN = os.getenv("HYDRO_AGENT_OHN_BASE_RUN")
REAL_SNAPSHOT = os.getenv("HYDRO_AGENT_OHN_LOWMAN_SNAPSHOT")
pytestmark = pytest.mark.skipif(
    not REAL_OHN or not REAL_SNAPSHOT,
    reason="set HYDRO_AGENT_OHN_BASE_RUN and HYDRO_AGENT_OHN_LOWMAN_SNAPSHOT",
)


def test_real_openhydronet_forecast_has_three_leads(real_ohn_service):
    forecast = real_ohn_service.forecast()
    assert set(forecast.lead_values) == {1, 2, 3}
    assert all(np.isfinite(v) for v in forecast.lead_values.values())
```

- [ ] **Step 2: Verify explicit skip before artifacts are configured**

Run: `uv run pytest tests/integration/test_openhydronet_sandbox_forecast.py -v`

Expected: SKIPPED with exact setup reason.

- [ ] **Step 3: Wire SP4A ForecastService and SP5 candidate/Gate reuse**

Register `OpenHydroNetRuntimeAdapter` in the same RuntimeRegistry. Add `AdaptationService` following SP4A `CalibrationService` lifecycle but `capability="adapt"`. Candidate Scheme stores the new checkpoint artifact id and provenance; Gate evaluation uses the same validation snapshot and deterministic metrics. Base checkpoint hashes must remain unchanged on ACCEPT/KEEP/ROLLBACK.

- [ ] **Step 4: Run real integration tests**

```bash
HYDRO_AGENT_OHN_BASE_RUN=... HYDRO_AGENT_OHN_LOWMAN_SNAPSHOT=... \
uv run pytest tests/integration/test_openhydronet_sandbox_forecast.py tests/integration/test_openhydronet_adaptation_isolation.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_openhydronet_sandbox_forecast.py tests/integration/test_openhydronet_adaptation_isolation.py
git commit -m "test: prove OpenHydroNet adapter isolation"
```

## SP3B Acceptance

```bash
uv run pytest tests/models/openhydronet tests/optimization/test_ohn_strategies.py tests/data/test_openhydronet_snapshot.py -v
HYDRO_AGENT_OHN_BASE_RUN=... HYDRO_AGENT_OHN_LOWMAN_SNAPSHOT=... \
uv run pytest tests/integration/test_openhydronet_sandbox_forecast.py tests/integration/test_openhydronet_adaptation_isolation.py -v
```

Acceptance requires OpenHydroNet to use the same Sandbox/Registry/Application Service boundaries as XAJ, produce three finite lead forecasts, restrict adaptation to the declared modules, prove non-target tensors remain unchanged, and never mutate the base run/checkpoint artifacts.