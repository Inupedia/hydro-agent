# Hydro-Agent Skills refactor: evidence and delivery boundary

The expert proposal is directionally sound, but this repository already has a
file-backed Skill Registry, built-in and user packages, CRUD, stage activation,
governed expert claims, and prompt injection. The implementation now keeps that
runtime and consolidates the former twelve built-ins into the proposal's six
task-oriented packages under the top-level `skills/` source of truth.

## Current contracts

- `AgentDecision` and `CalibrationPlan` select legal parameter groups,
  objectives, strategies, and budgets. Neither contract carries a continuous
  XAJ parameter vector.
- XAJ, evaluation metrics, optimizer search, standards, Campaign policy, and
  Gate decisions remain deterministic code.
- Skills are advisory. External and learned claims pass through applicability,
  source, and trust-state governance before they influence planning.
- A user Skill must be saved **and** bound to an activation stage before it is
  included in a prompt.

## Delivered foundation

The Registry now reads only frontmatter during discovery. It loads the full
`SKILL.md` when a Skill is activated or opened for editing. The prompt path
records the effective source, SHA-256 of each activated `SKILL.md`, and the
paths and SHA-256 values of References actually included. These manifests are
persisted with Agent decisions and returned in Agent round logs. Existing
decision rows have a nullable audit field, so historical rows are left intact.
New user Skills store stage and model bindings in `.bindings/*.json` outside
the portable package. The Workbench can edit that binding; legacy
`activation_stages` metadata remains a read-only fallback for older packages.
At Workbench task creation, the effective Skill packages (including assets)
and bindings are frozen as verified bytes in `TaskState.skill_snapshot_json`.
SQLite prevents direct SQL from replacing a Snapshot after its first write,
while allowing ordinary TaskState updates.
Prompt activation and deterministic Expert Prior retrieval use that snapshot
after edits or process restarts. The task Snapshot summary is available at
`GET /api/tasks/{task_id}/skill-snapshot`; raw package bytes are not returned
by the API. Invocation records include Snapshot/Binding hashes, loaded
Reference hashes, input Evidence IDs, and the `AgentDecision` output contract.
The editor now offers a read-only draft check for YAML/package naming and
Hydro-Agent Reference paths and Workflow Binding. This is a local compatibility
check. All six built-ins also pass the official `skills-ref` 0.1.1 validator,
and CI repeats that validation whenever `skills/**` changes.

The six built-ins are `hydrology-data-review`, `hydrologic-evidence-review`,
`xaj-calibration-diagnosis`, `calibration-experiment-design`,
`calibration-result-review`, and `hydrology-reporting`. This is a task-scoped
Skill Snapshot for the current Campaign loop. It does
not by itself reproduce model, data, objective, optimizer seed, or final-test
results. Governed claim retrieval outside the Expert Prior path still uses
live Skill assets and is not yet task-replayed. For
`xaj-calibration-diagnosis`, Prompt
References are selected from the
current diagnosis and Resolve evidence: workflow first, parameter semantics
when groups are proposed, parameter relations for multiple groups, and
escalation after Resolve or boundary hits. Other Skills still use their
declared `prompt_references` when activated. The
frontmatter parser now uses YAML syntax and validates the required naming,
length, and string-metadata rules used by Hydro-Agent.

## Next implementation batches

1. ~~Provide an explicit migration/alias tool for existing user overrides that
   still use one of the former twelve IDs~~ — done via
   `skills.aliases` + `POST /api/skills/migrate-legacy` (complete-package rename;
   conflicts reported when both legacy and canonical overlays exist).
2. ~~Extend evidence-based Reference selection to the other hydrology Skills~~ —
   `reference_policy` now covers all six built-ins; OpenHydroNet references load
   only when `model_id == openhydronet`.
3. Add explicit user revision history and pinned-revision resolution; the
   current complete override is hash-addressed, but there is no editable
   revision browser or separate Campaign revision identifier yet.
   Campaign Usage is available now: `GET /api/tasks/{id}/skill-usage`
   merges frozen Snapshot inventory with recorded Skill invocations; the
   Workbench 「案例 Usage」 panel shows it.
4. ~~Extract evidence interpretation, XAJ diagnosis, experiment design, and
   result review into typed, source-addressable outputs~~ — done as
   `EvidenceInterpretation` → `DiagnosisHypothesis` → `CalibrationPlan` →
   `ExperimentReview`, orchestrated via `skills/orchestration.py`.
   Agent-facing `HydrologicEvidence` (`agent/hydrologic_evidence.py`) now
   normalizes diagnosis dicts before Skill handlers run.
5. Compare the archived old policy and current six-Skill policy under the same model,
   datasets, objective, development/final split, numerical evaluation budget,
   and seeds.
6. ~~Surface CI/`skills-ref` validation provenance in the Skill Workbench UI~~ —
   Workbench now shows Effective source, core-skill badges, draft validation
   chips, and a legacy-ID migrate action. Official CI `skills-ref` provenance
   can still be linked more explicitly later.
7. Compare the archived old policy and current six-Skill policy under the same model,
   datasets, objective, development/final split, numerical evaluation budget,
   and seeds.

Completion requires current-route and real-data runs for Yaogu and Leaf River,
not just unit tests or a Skill editor screen. Final-test evidence must stay
outside planning and remain sealed until development selection is frozen.
