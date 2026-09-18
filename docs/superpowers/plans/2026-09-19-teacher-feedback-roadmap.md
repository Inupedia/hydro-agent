# 导师优化意见 Superpowers 执行路线

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Do not implement all three plans on one branch; follow the dependency gates below.

**Goal:** 将导师提出的“避免单指标率定、过程线诊断、空间异质性计算单元、次洪评价”转化为三个可独立验收、可回退的 Hydro-Agent 开发计划。

**Design spec:** `docs/superpowers/specs/2026-09-19-hydrologic-process-diagnosis-and-spatial-units-design.md`

---

## 1. Plan Set

| Phase | Plan | Purpose | Primary acceptance |
|---|---|---|---|
| P0 | `2026-09-19-p0-event-process-diagnosis.md` | 次洪分割、过程 signatures、完整证据进入 Agent 和 UI | Agent 能引用多场洪水的峰/时/量/涨退水证据 |
| P1 | `2026-09-19-p1-diagnosis-driven-calibration.md` | 方向假设、Morris/扰动验证、DDS/SCE-UA 精调、Top-K 候选、Research Gate | Agent 找方向，数值工具验证/精调，采用不再只看单一分数 |
| P2 | `2026-09-19-p2-spatial-heterogeneity-units.md` | BasinSpatialProfile、确定性计算单元候选、Agent 推荐 | Agent 根据空间证据推荐现有候选，不自由画子流域 |

---

## 2. Execution Order

### Gate A — Process evidence first

Execute P0 completely.

Required proof:

```text
continuous obs/sim/forcing
  -> deterministic event segmentation
  -> peak/timing/volume/rise/recession signatures
  -> HydrographDiagnosisPacket
  -> Agent-visible evidence
  -> Workbench flood-event matrix
```

Do not begin P1 until the Agent can consume at least two event records without reducing them to one peak or one overall score.

### Gate B — Diagnosis-driven calibration

Execute P1 after P0.

Required proof:

```text
HydrographDiagnosisPacket
  -> DiagnosisHypothesis
  -> AdjustmentDirection
  -> DirectionalProbe / Morris
  -> supported/refuted/inconclusive
  -> DDS/SCE-UA
  -> BehavioralCandidateSet
  -> independent development comparison
  -> ResearchAdoptionGate
  + StandardEvaluationResult
  -> Experience case
```

P1 must preserve the existing hard rule: Agent does not directly set continuous parameter values.

### Gate C — Spatial scheme construction

P2 may start after P0 because it is largely independent from P1, but the recommended order is P0 -> P1 -> P2 so the main scientific story is stabilized before expanding scheme construction.

Required proof:

```text
trusted GIS/data materials
  -> BasinSpatialProfile
  -> deterministic unit candidates
  -> Agent recommendation
  -> existing boundary review/hash gate
```

P2 does not include full multi-zone XAJ calibration.

---

## 3. Dependency Graph

```text
Existing Hydro-Agent
      |
      v
P0 Event / Process Evidence
      |
      +----------------------+
      |                      |
      v                      v
P1 Diagnosis Calibration   P2 Spatial Units
      |                      |
      v                      v
Experience evolution      Scheme construction
      |
      v
O/P/A research evaluation
```

P2 consumes existing GIS/modeling foundations, not P1 optimizer internals.

---

## 4. Why the Work Is Split This Way

The four teacher comments are related but not one implementation unit.

### P0 groups comments 1, 2 and 4 at the evidence layer

Without deterministic event/process evidence, asking the LLM to “look at the hydrograph” would be hard to audit. P0 establishes the facts first.

### P1 turns that evidence into scientific experiments

This is where Hydro-Agent becomes more than “LLM selects optimizer”:

```text
observe -> diagnose -> hypothesize -> verify -> optimize -> compare -> learn
```

### P2 addresses scheme construction separately

Spatial heterogeneity changes the model-building problem, data requirements and GIS workflow. Combining it into P0/P1 would create a plan that cannot be independently reviewed or rolled back.

---

## 5. Branch / PR Strategy

Use one implementation branch per plan:

```text
feat/p0-event-process-diagnosis
feat/p1-diagnosis-calibration
feat/p2-spatial-unit-recommendation
```

Each branch starts from the latest `main` after its dependencies are merged.

Do not implement P0/P1/P2 inside this documentation PR.

---

## 6. Superpowers Discipline

Before each implementation plan:

```bash
git status --short
git log -5 --oneline
```

At execution time use `superpowers:using-git-worktrees` to create an isolated worktree.

For every task:

1. write the failing test;
2. run it and observe the expected failure;
3. implement the minimum behavior;
4. run the focused test;
5. run the task-local regression;
6. commit;
7. request spec-compliance review;
8. request code-quality review.

Do not combine multiple plan tasks into one large commit.

---

## 7. Scientific Invariants Across All Plans

- [ ] LLM never directly executes arbitrary parameter values.
- [ ] Event boundaries are deterministic.
- [ ] Process metrics are computed by code, not inferred from chart screenshots.
- [ ] Same input produces same evidence.
- [ ] DDS/SCE-UA remain deterministic numerical search tools under fixed seed/protocol.
- [ ] Near-optimal parameter-distinct candidates can survive calibration for later comparison.
- [ ] Development may select but not reopen calibration search.
- [ ] final-test never feeds the same campaign.
- [ ] GB/T evaluation remains available but is not the sole research adoption authority.
- [ ] Spatial unknowns remain unknown.
- [ ] LLM cannot generate arbitrary computation-unit polygons.
- [ ] Teacher XAJ v6 remains unchanged.

---

## 8. Research Comparison After P0/P1

After P1 passes, formal comparison should keep equal data split, model kernel, seed schedule and evaluation budget where possible.

Recommended arms:

```text
O  original/default scheme
P  fixed numerical optimization
A0 Agent diagnosis + optimizer
A1 A0 + process/event evidence
A2 A1 + experience prior
```

The comparison should report:

- overall NSE/KGE/PBIAS;
- event peak/timing/volume errors;
- high-flow behavior;
- number of model evaluations;
- number of supported/refuted hypotheses;
- rollback/keep/adopt counts;
- wall time;
- failure/inconclusive runs.

Do not report only the best successful run.

---

## 9. Completion Definition

The teacher-feedback redesign is complete only when all three statements are true:

1. **率定：** Agent can explain what process error it sees and why it selected a parameter group before numerical optimization.
2. **验证：** The selected parameter direction is supported by deterministic experiments and candidate adoption is justified by multi-dimensional process evidence, not just one score.
3. **建模：** Agent can explain why a lumped or multi-unit scheme is recommended from spatial evidence, while deterministic GIS tools retain authority over actual boundaries.

This documentation PR defines the implementation contract only; it intentionally contains no production-code change.
