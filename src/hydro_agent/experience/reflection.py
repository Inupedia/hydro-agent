from __future__ import annotations

from typing import Protocol

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.experience.contracts import ExperienceEntry, ExperienceEvidenceRef
from hydro_agent.experience.diff import ExperienceDiff, is_structural_change


class ExperienceReflectionInput(FrozenModel):
    task_id: str
    basin_id: str
    model_id: str | None
    active_experiences: tuple[ExperienceEntry, ...] = ()
    decisions: tuple[dict[str, object], ...] = ()
    evidence: tuple[dict[str, object], ...] = ()
    experiment_history: tuple[dict[str, object], ...] = ()


class ExperienceReflectionProvider(Protocol):
    def reflect(
        self,
        reflection_input: ExperienceReflectionInput,
    ) -> tuple[ExperienceDiff, ...]: ...


class ReflectionResult(FrozenModel):
    reflection_input: ExperienceReflectionInput
    diffs: tuple[ExperienceDiff, ...]


class ApplyResult(FrozenModel):
    accepted: tuple[ExperienceDiff, ...] = ()
    rejected: tuple[str, ...] = ()
    structural_change: bool = False


class ExperienceReflectionEngine:
    def __init__(self, repository, *, provider: ExperienceReflectionProvider):
        self.repository = repository
        self.provider = provider

    def reflect(self, task_id: str) -> ReflectionResult:
        reflection_input = self._build_input(task_id)
        diffs = tuple(self.provider.reflect(reflection_input))
        return ReflectionResult(
            reflection_input=reflection_input,
            diffs=diffs,
        )

    def _build_input(self, task_id: str) -> ExperienceReflectionInput:
        task = self.repository.get_task(task_id)
        model_id = self._resolve_model_id(task_id)
        experiences = tuple(
            self.repository.list_active_experiences(
                model_id=model_id,
                basin_id=task.basin_id,
            )
        )
        decisions = tuple(
            {
                "decision_id": row.decision_id,
                "round_number": row.round_number,
                "action": row.action,
                "hypothesis": row.hypothesis,
                "strategy_id": row.strategy_id,
                "rationale_summary": row.rationale_summary,
            }
            for row in self.repository.list_agent_decisions(task_id)
        )
        evidence_rows = self.repository.list_evidence(task_id)
        evidence = tuple(
            {
                "evidence_id": row.evidence_id,
                "action": row.action,
                "status": row.status,
                "observations": tuple(row.observations_json or ()),
                "metrics": dict(row.metrics_json or {}),
                "gates": dict(row.gates_json or {}),
                "new_information_hash": row.new_information_hash,
            }
            for row in evidence_rows
        )
        experiment_history = tuple(
            item
            for item in evidence
            if item["action"] in {"A05_OPTIMIZE", "A06_GATE", "A07_RESOLVE"}
        )
        return ExperienceReflectionInput(
            task_id=task_id,
            basin_id=task.basin_id,
            model_id=model_id,
            active_experiences=experiences,
            decisions=decisions,
            evidence=evidence,
            experiment_history=experiment_history,
        )

    def _resolve_model_id(self, task_id: str) -> str | None:
        try:
            state = self.repository.get_task_state(task_id)
            return str(self.repository.get_scheme(state.current_scheme_id).model_id)
        except KeyError:
            schemes = self.repository.list_schemes(task_id=task_id)
            if not schemes:
                return None
            preferred = next(
                (
                    scheme
                    for scheme in schemes
                    if scheme.status in {"accepted", "frozen", "base"}
                ),
                schemes[0],
            )
            return str(preferred.model_id)


class ExperienceDiffApplier:
    def __init__(
        self,
        repository,
        *,
        reinforce_step: float = 0.05,
        weaken_step: float = 0.10,
    ):
        if reinforce_step <= 0 or weaken_step <= 0:
            raise ValueError("confidence steps must be positive")
        self.repository = repository
        self.reinforce_step = reinforce_step
        self.weaken_step = weaken_step

    def apply(
        self,
        task_id: str,
        diffs: tuple[ExperienceDiff, ...] | list[ExperienceDiff],
    ) -> ApplyResult:
        accepted: list[ExperienceDiff] = []
        rejected: list[str] = []

        for diff in diffs:
            try:
                entries, from_revision, to_revision = self._prepare_one(diff)
                current_version = self.repository.get_current_experience_skill_version()
                version_before = current_version.version if current_version is not None else None
                version_after = version_before if not is_structural_change(diff) else None
                self.repository.commit_experience_transition(
                    entries=entries,
                    event_type=diff.operation,
                    reason=diff.reason,
                    task_id=task_id,
                    experience_id=self._event_experience_id(diff),
                    from_revision=from_revision,
                    to_revision=to_revision,
                    version_before=version_before,
                    version_after=version_after,
                    evidence_refs=diff.evidence_refs,
                )
            except (KeyError, ValueError) as exc:
                rejected.append(f"{diff.operation}:{exc}")
                continue

            accepted.append(diff)

        return ApplyResult(
            accepted=tuple(accepted),
            rejected=tuple(rejected),
            structural_change=any(is_structural_change(diff) for diff in accepted),
        )

    def _prepare_one(
        self,
        diff: ExperienceDiff,
    ) -> tuple[tuple[ExperienceEntry, ...], int | None, int | None]:
        if diff.operation in {"KEEP", "REJECT"}:
            self._active_target(diff.experience_id)
            return (), None, None

        if diff.operation == "REINFORCE":
            current = self._active_target(diff.experience_id)
            supporting, added = _merge_refs(
                current.supporting_evidence,
                diff.evidence_refs,
            )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "supporting_evidence": supporting,
                    "confidence": min(
                        1.0,
                        current.confidence + self.reinforce_step * added,
                    ),
                    "source_hash": None,
                }
            )
            return (updated,), current.revision, updated.revision

        if diff.operation == "WEAKEN":
            current = self._active_target(diff.experience_id)
            contradicting, added = _merge_refs(
                current.contradicting_evidence,
                diff.evidence_refs,
            )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "contradicting_evidence": contradicting,
                    "confidence": max(
                        0.0,
                        current.confidence - self.weaken_step * added,
                    ),
                    "source_hash": None,
                }
            )
            return (updated,), current.revision, updated.revision

        if diff.operation == "CREATE":
            proposal = diff.proposals[0]
            self._ensure_new(proposal.experience_id)
            return (proposal,), None, proposal.revision

        if diff.operation == "MERGE":
            proposal = diff.proposals[0]
            self._ensure_new(proposal.experience_id)
            sources = tuple(self._active_target(source_id) for source_id in diff.source_ids)
            revisions = tuple(self._superseded(source) for source in sources)
            first = sources[0]
            return (*revisions, proposal), first.revision, first.revision + 1

        if diff.operation == "SPLIT":
            current = self._active_target(diff.experience_id)
            for proposal in diff.proposals:
                self._ensure_new(proposal.experience_id)
            superseded = self._superseded(current)
            return (superseded, *diff.proposals), current.revision, superseded.revision

        if diff.operation == "SUPERSEDE":
            current = self._active_target(diff.experience_id)
            proposal = diff.proposals[0]
            self._ensure_new(proposal.experience_id)
            superseded = self._superseded(current)
            return (superseded, proposal), current.revision, superseded.revision

        raise ValueError(f"unsupported operation {diff.operation}")

    def _active_target(self, experience_id: str | None) -> ExperienceEntry:
        if not experience_id:
            raise ValueError("experience_id required")
        current = self.repository.get_experience(experience_id)
        if current.status != "active":
            raise ValueError(f"experience {experience_id} is not active")
        return current

    def _ensure_new(self, experience_id: str) -> None:
        try:
            self.repository.get_experience(experience_id)
        except KeyError:
            return
        raise ValueError(f"experience {experience_id} already exists")

    @staticmethod
    def _superseded(current: ExperienceEntry) -> ExperienceEntry:
        return current.model_copy(
            update={
                "revision": current.revision + 1,
                "status": "superseded",
                "source_hash": None,
            }
        )

    @staticmethod
    def _event_experience_id(diff: ExperienceDiff) -> str | None:
        if diff.experience_id:
            return diff.experience_id
        if diff.proposals:
            return diff.proposals[0].experience_id
        if diff.source_ids:
            return diff.source_ids[0]
        return None


def _merge_refs(
    existing: tuple[ExperienceEvidenceRef, ...],
    additions: tuple[ExperienceEvidenceRef, ...],
) -> tuple[tuple[ExperienceEvidenceRef, ...], int]:
    values = list(existing)
    seen = {
        (ref.task_id, ref.experiment_id, ref.evidence_id)
        for ref in existing
    }
    added = 0
    for ref in additions:
        key = (ref.task_id, ref.experiment_id, ref.evidence_id)
        if key in seen:
            continue
        seen.add(key)
        values.append(ref)
        added += 1
    return tuple(values), added
