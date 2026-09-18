from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from threading import RLock

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.experience.compiler import ExperienceSkillCompiler
from hydro_agent.experience.contracts import (
    ExperienceEntry,
    ExperienceEvidenceRef,
    ExperienceScope,
)
from hydro_agent.experience.diff import ExperienceDiff
from hydro_agent.experience.reflection import (
    ExperienceDiffApplier,
    ExperienceReflectionEngine,
    ExperienceReflectionInput,
)


class ExperienceEvolutionOutcome(FrozenModel):
    task_id: str
    processed: bool
    structural_change: bool = False
    candidate_version: int | None = None
    promotion_accepted: bool | None = None
    reasons: tuple[str, ...] = ()


class EvidenceExperienceReflectionProvider:
    """Turn persisted hydrologic experiment evidence into candidate Experience Diffs.

    This provider is intentionally pure: it only proposes structured changes.
    Database writes remain owned by ExperienceDiffApplier.
    """

    def reflect(
        self,
        reflection_input: ExperienceReflectionInput,
    ) -> tuple[ExperienceDiff, ...]:
        diagnosis = _latest_action(reflection_input.evidence, "A04_DIAGNOSE")
        resolve = _latest_action(reflection_input.evidence, "A07_RESOLVE")
        optimize = _latest_decision(reflection_input.decisions, "A05_OPTIMIZE")
        optimize_evidence = _latest_action(reflection_input.evidence, "A05_OPTIMIZE")
        if diagnosis is None or resolve is None:
            return ()

        outcome = str(resolve.get("status") or "").upper()
        if outcome == "ACCEPT":
            positive = True
        elif outcome in {"KEEP", "ROLLBACK", "FAILED", "BLOCKED"}:
            positive = False
        else:
            return ()

        gates = dict(diagnosis.get("gates") or {})
        hypothesis = str(gates.get("hypothesis") or "UNKNOWN").strip() or "UNKNOWN"
        optimize_gates = dict((optimize_evidence or {}).get("gates") or {})
        strategy_id = str(
            optimize_gates.get("strategy_id")
            or (optimize or {}).get("strategy_id")
            or gates.get("recommended_strategy_id")
            or ""
        ).strip()
        groups = (
            _groups(optimize_gates.get("param_groups"))
            or _groups(gates.get("recommended_param_groups"))
        )
        objective = str(
            optimize_gates.get("objective")
            or gates.get("recommended_objective")
            or ""
        ).strip()
        if not groups:
            return ()

        evidence_refs = _evidence_refs(
            reflection_input.task_id,
            reflection_input.evidence,
        )
        if not evidence_refs:
            return ()

        same: ExperienceEntry | None = None
        opposite: ExperienceEntry | None = None
        for entry in reflection_input.active_experiences:
            if not _same_rule_shape(
                entry,
                hypothesis=hypothesis,
                strategy_id=strategy_id,
                groups=groups,
            ):
                continue
            if _positive_rule(entry) == positive and same is None:
                same = entry
            elif _positive_rule(entry) != positive and opposite is None:
                opposite = entry

        diffs: list[ExperienceDiff] = []
        if same is not None:
            diffs.append(
                ExperienceDiff(
                    operation="REINFORCE",
                    experience_id=same.experience_id,
                    evidence_refs=evidence_refs,
                    reason=_reflection_reason(
                        positive=positive,
                        outcome=outcome,
                        strategy_id=strategy_id,
                        groups=groups,
                        change="reinforce",
                    ),
                )
            )
        else:
            decision = (
                {
                    "prefer_strategy_id": strategy_id,
                    "prefer_param_groups": list(groups),
                    "objective": objective,
                }
                if positive
                else {
                    "failed_strategy_id": strategy_id,
                    "failed_param_groups": list(groups),
                    "avoid_param_groups": list(groups),
                    "objective": objective,
                }
            )
            decision = {
                key: value
                for key, value in decision.items()
                if value not in ("", [], ())
            }
            proposal = ExperienceEntry(
                experience_id=_experience_id(
                    reflection_input,
                    positive=positive,
                    hypothesis=hypothesis,
                    strategy_id=strategy_id,
                    groups=groups,
                ),
                revision=1,
                category="basin" if reflection_input.basin_id else "model",
                scope=ExperienceScope(
                    model_ids=(reflection_input.model_id,)
                    if reflection_input.model_id
                    else (),
                    basin_ids=(reflection_input.basin_id,)
                    if reflection_input.basin_id
                    else (),
                ),
                pattern={"hypothesis": hypothesis},
                decision=decision,
                supporting_evidence=evidence_refs,
                contradicting_evidence=(),
                confidence=0.65 if positive else 0.60,
                status="active",
            )
            diffs.append(
                ExperienceDiff(
                    operation="CREATE",
                    proposals=(proposal,),
                    evidence_refs=evidence_refs,
                    reason=_reflection_reason(
                        positive=positive,
                        outcome=outcome,
                        strategy_id=strategy_id,
                        groups=groups,
                        change="create",
                    ),
                )
            )

        if opposite is not None:
            diffs.append(
                ExperienceDiff(
                    operation="WEAKEN",
                    experience_id=opposite.experience_id,
                    evidence_refs=evidence_refs,
                    reason=_reflection_reason(
                        positive=positive,
                        outcome=outcome,
                        strategy_id=strategy_id,
                        groups=groups,
                        change="counterexample",
                    ),
                )
            )
        return tuple(diffs)


class ExperienceEvolutionService:
    """Close the post-task Experience learning -> candidate -> regression loop."""

    def __init__(
        self,
        repository,
        *,
        version_store,
        promotion_service,
        skill_registry=None,
        provider=None,
        compiler: ExperienceSkillCompiler | None = None,
    ):
        self.repository = repository
        self.version_store = version_store
        self.promotion_service = promotion_service
        self.skill_registry = skill_registry
        self.provider = provider or EvidenceExperienceReflectionProvider()
        self.compiler = compiler or ExperienceSkillCompiler()
        self._lock = RLock()

    def ensure_baseline(self) -> int:
        with self._lock:
            return self._ensure_baseline_locked()

    def _ensure_baseline_locked(self) -> int:
        current = self.repository.get_current_experience_skill_version()
        if current is not None:
            self.version_store.ensure_current(current.version)
            if self.skill_registry is not None:
                self.skill_registry.reload()
            return current.version

        versions = self.repository.list_experience_skill_versions()
        if versions:
            raise ValueError(
                "Experience Skill history exists without a promoted baseline"
            )

        compiled = self.compiler.compile(1, ())
        self.version_store.create_candidate(compiled)
        self.version_store.promote(
            1,
            regression={
                "passed": True,
                "bootstrap": True,
                "reason": "EMPTY_EXPERIENCE_BASELINE",
            },
        )
        if self.skill_registry is not None:
            self.skill_registry.reload()
        return 1

    def process_completed_task(self, task_id: str) -> ExperienceEvolutionOutcome:
        with self._lock:
            return self._process_completed_task_locked(task_id)

    def _process_completed_task_locked(self, task_id: str) -> ExperienceEvolutionOutcome:
        task = self.repository.get_task(task_id)
        state = self.repository.get_task_state(task_id)
        if (
            task.phase != "E"
            or state.needs_follow_up
            or state.paused
            or str(task.terminal_status or "").lower() in {"cancelled", "failed"}
        ):
            return ExperienceEvolutionOutcome(
                task_id=task_id,
                processed=False,
                reasons=("TASK_NOT_COMPLETED",),
            )

        self.ensure_baseline()

        # If an earlier structural candidate is still quarantined, this newly
        # completed task is independent of that candidate's source evidence.
        # Validate the pending candidate before reflecting on the new task so
        # the holdout cannot become training evidence first.
        pending = self._candidate_for_active_structure()
        pending_decision = None
        if pending is not None:
            pending_decision = self.promotion_service.validate_and_promote(
                pending.version
            )
            if pending_decision.accepted and self.skill_registry is not None:
                self.skill_registry.reload()

        prior_events = [
            event
            for event in self.repository.list_experience_evolution_events()
            if event.task_id == task_id
        ]
        structural_change = any(
            event.event_type in {"CREATE", "MERGE", "SPLIT", "SUPERSEDE"}
            for event in prior_events
        )
        structural_diffs: tuple[ExperienceDiff, ...] = ()

        if not prior_events:
            reflection = ExperienceReflectionEngine(
                self.repository,
                provider=self.provider,
            ).reflect(task_id)
            applied = ExperienceDiffApplier(self.repository).apply(
                task_id,
                reflection.diffs,
            )
            structural_change = applied.structural_change
            structural_diffs = tuple(
                diff
                for diff in applied.accepted
                if diff.operation in {"CREATE", "MERGE", "SPLIT", "SUPERSEDE"}
            )
            if not applied.accepted and applied.rejected:
                return ExperienceEvolutionOutcome(
                    task_id=task_id,
                    processed=True,
                    structural_change=False,
                    candidate_version=pending.version if pending is not None else None,
                    promotion_accepted=(
                        pending_decision.accepted
                        if pending_decision is not None
                        else None
                    ),
                    reasons=tuple(applied.rejected),
                )

        if not structural_change and not self._structure_differs_from_promoted():
            reasons = ["STATE_OPTIMIZATION_ONLY"]
            if pending_decision is not None:
                reasons = [*pending_decision.reasons, *reasons]
            return ExperienceEvolutionOutcome(
                task_id=task_id,
                processed=True,
                structural_change=False,
                candidate_version=pending.version if pending is not None else None,
                promotion_accepted=(
                    pending_decision.accepted
                    if pending_decision is not None
                    else None
                ),
                reasons=tuple(reasons),
            )

        candidate = self._candidate_for_active_structure()
        if candidate is None:
            self._retire_stale_candidates()
            candidate = self._compile_candidate(structural_diffs=structural_diffs)

        # Do not re-use the same completed task to validate a candidate that
        # was already checked before Reflection. For a brand-new structural
        # candidate, validate now; its source task is excluded by PromotionService.
        if pending is not None and candidate.version == pending.version:
            decision = pending_decision
        else:
            decision = self.promotion_service.validate_and_promote(candidate.version)

        if decision is not None and decision.accepted and self.skill_registry is not None:
            self.skill_registry.reload()
        return ExperienceEvolutionOutcome(
            task_id=task_id,
            processed=True,
            structural_change=True,
            candidate_version=candidate.version,
            promotion_accepted=decision.accepted if decision is not None else None,
            reasons=decision.reasons if decision is not None else (),
        )

    def _compile_candidate(
        self,
        *,
        structural_diffs: tuple[ExperienceDiff, ...] = (),
    ):
        versions = self.repository.list_experience_skill_versions()
        next_version = max((row.version for row in versions), default=0) + 1
        compiled = self.compiler.compile(
            next_version,
            self.repository.list_active_experiences(),
        )
        return self.version_store.create_candidate(
            compiled,
            structural_changes=tuple(
                _structural_change_payload(diff)
                for diff in structural_diffs
            ),
        )

    def _candidate_for_active_structure(self):
        active_ids = {
            entry.experience_id
            for entry in self.repository.list_active_experiences()
        }
        for row in reversed(self.repository.list_experience_skill_versions()):
            if row.status != "candidate":
                continue
            manifest = dict(row.manifest_json or {})
            candidate_ids = set(
                str(item)
                for item in (
                    manifest.get("source_experience_ids")
                    or dict(manifest.get("source_revisions") or {}).keys()
                )
            )
            if candidate_ids == active_ids:
                return row
        return None

    def _retire_stale_candidates(self) -> None:
        active_ids = {
            entry.experience_id
            for entry in self.repository.list_active_experiences()
        }
        for row in self.repository.list_experience_skill_versions():
            if row.status != "candidate":
                continue
            manifest = dict(row.manifest_json or {})
            candidate_ids = set(
                str(item)
                for item in (
                    manifest.get("source_experience_ids")
                    or dict(manifest.get("source_revisions") or {}).keys()
                )
            )
            if candidate_ids == active_ids:
                continue
            self.repository.set_experience_skill_version_status(
                row.version,
                "rejected",
                regression={
                    "passed": False,
                    "reason": "STALE_CANDIDATE_SUPERSEDED_BY_NEW_STRUCTURE",
                },
            )

    def _structure_differs_from_promoted(self) -> bool:
        current = self.repository.get_current_experience_skill_version()
        if current is None:
            return bool(self.repository.list_active_experiences())
        promoted_ids = set(
            str(item)
            for item in (
                dict(current.manifest_json or {}).get("source_experience_ids") or ()
            )
        )
        active_ids = {
            entry.experience_id
            for entry in self.repository.list_active_experiences()
        }
        return promoted_ids != active_ids


def _latest_action(
    rows: tuple[dict[str, object], ...],
    action: str,
) -> dict[str, object] | None:
    return next(
        (row for row in reversed(rows) if row.get("action") == action),
        None,
    )


def _latest_decision(
    rows: tuple[dict[str, object], ...],
    action: str,
) -> dict[str, object] | None:
    return next(
        (row for row in reversed(rows) if row.get("action") == action),
        None,
    )


def _groups(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        return tuple(item.strip() for item in raw.split(",") if item.strip())
    if isinstance(raw, (list, tuple)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()


def _positive_rule(entry: ExperienceEntry) -> bool:
    return bool(
        entry.decision.get("prefer_strategy_id")
        or entry.decision.get("prefer_param_groups")
    )


def _same_rule_shape(
    entry: ExperienceEntry,
    *,
    hypothesis: str,
    strategy_id: str,
    groups: tuple[str, ...],
) -> bool:
    if str(entry.pattern.get("hypothesis") or "UNKNOWN") != hypothesis:
        return False
    decision_strategy = str(
        entry.decision.get("prefer_strategy_id")
        or entry.decision.get("failed_strategy_id")
        or ""
    )
    if strategy_id and decision_strategy and strategy_id != decision_strategy:
        return False
    decision_groups = set(
        _groups(
            entry.decision.get("prefer_param_groups")
            or entry.decision.get("failed_param_groups")
            or entry.decision.get("avoid_param_groups")
        )
    )
    return bool(decision_groups) and decision_groups == set(groups)


def _evidence_refs(
    task_id: str,
    rows: Iterable[dict[str, object]],
) -> tuple[ExperienceEvidenceRef, ...]:
    refs: list[ExperienceEvidenceRef] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for row in rows:
        if row.get("action") not in {
            "A04_DIAGNOSE",
            "A05_OPTIMIZE",
            "A06_GATE",
            "A07_RESOLVE",
            "A10_EVALUATE_REPORT",
        }:
            continue
        gates = dict(row.get("gates") or {})
        experiment_id = str(gates.get("experiment_plan_id") or "").strip() or None
        evidence_id = str(row.get("evidence_id") or "").strip() or None
        key = (task_id, experiment_id, evidence_id)
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            ExperienceEvidenceRef(
                task_id=task_id,
                experiment_id=experiment_id,
                evidence_id=evidence_id,
            )
        )
    return tuple(refs)


def _experience_id(
    reflection_input: ExperienceReflectionInput,
    *,
    positive: bool,
    hypothesis: str,
    strategy_id: str,
    groups: tuple[str, ...],
) -> str:
    payload = {
        "task_id": reflection_input.task_id,
        "model_id": reflection_input.model_id,
        "basin_id": reflection_input.basin_id,
        "positive": positive,
        "hypothesis": hypothesis,
        "strategy_id": strategy_id,
        "groups": list(groups),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:10].upper()
    model = (reflection_input.model_id or "GENERAL").upper().replace("-", "")
    return f"EXP-{model}-{digest}"


def _reflection_reason(
    *,
    positive: bool,
    outcome: str,
    strategy_id: str,
    groups: tuple[str, ...],
    change: str,
) -> str:
    direction = "successful" if positive else "unsuccessful"
    strategy = strategy_id or "unspecified"
    return (
        f"{change}: {direction} calibration outcome={outcome}; "
        f"strategy={strategy}; groups={','.join(groups)}"
    )


def _active_revision_map(entries: Iterable[ExperienceEntry]) -> dict[str, int]:
    return {
        entry.experience_id: entry.revision
        for entry in sorted(entries, key=lambda item: item.experience_id)
    }



def _structural_change_payload(diff: ExperienceDiff) -> dict:
    return {
        "operation": diff.operation,
        "experience_id": diff.experience_id,
        "source_ids": list(diff.source_ids),
        "proposal_ids": [
            proposal.experience_id
            for proposal in diff.proposals
        ],
        "reason": diff.reason,
        "evidence_refs": [
            ref.model_dump(mode="json")
            for ref in diff.evidence_refs
        ],
    }
