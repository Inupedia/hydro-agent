from __future__ import annotations

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.experience.regression import (
    ExperienceRegressionSelector,
    ExperienceRegressionService,
    ExperienceRegressionSet,
    RegressionComparison,
)


class PromotionDecision(FrozenModel):
    accepted: bool
    reasons: tuple[str, ...]


class PromotionGate:
    def __init__(
        self,
        *,
        quality_tolerance: float = 0.01,
        max_repeated_failure_increase: int = 0,
    ):
        if quality_tolerance < 0:
            raise ValueError("quality_tolerance must be >= 0")
        if max_repeated_failure_increase < 0:
            raise ValueError("max_repeated_failure_increase must be >= 0")
        self.quality_tolerance = quality_tolerance
        self.max_repeated_failure_increase = max_repeated_failure_increase

    def evaluate(self, comparison: RegressionComparison) -> PromotionDecision:
        if not comparison.cases:
            return PromotionDecision(
                accepted=False,
                reasons=("INSUFFICIENT_REGRESSION_CASES",),
            )

        failures: list[str] = []
        repeated_failure_reduction = False

        for row in comparison.cases:
            current_succeeded = _succeeded(row.current.terminal_status)
            candidate_succeeded = _succeeded(row.candidate.terminal_status)
            if current_succeeded and not candidate_succeeded:
                prefix = (
                    "HARD_CASE_REGRESSION"
                    if row.case.hard_case
                    else "TERMINAL_STATUS_REGRESSION"
                )
                failures.append(f"{prefix}:{row.case.task_id}")

            new_violations = set(row.candidate.guardrail_violations) - set(
                row.current.guardrail_violations
            )
            if new_violations:
                failures.append(
                    "NEW_GUARDRAIL_VIOLATION:"
                    f"{row.case.task_id}:{','.join(sorted(new_violations))}"
                )

            if (
                row.current.quality_score is not None
                and row.candidate.quality_score is None
            ):
                failures.append(f"QUALITY_MISSING:{row.case.task_id}")
            else:
                quality_delta = row.quality_delta
                if (
                    quality_delta is not None
                    and quality_delta < -self.quality_tolerance
                ):
                    failures.append(
                        f"QUALITY_REGRESSION:{row.case.task_id}:{quality_delta:.6f}"
                    )

            if row.repeated_failure_delta > self.max_repeated_failure_increase:
                failures.append(
                    "REPEATED_FAILURE_REGRESSION:"
                    f"{row.case.task_id}:+{row.repeated_failure_delta}"
                )
            elif row.repeated_failure_delta < 0:
                repeated_failure_reduction = True

        if failures:
            return PromotionDecision(
                accepted=False,
                reasons=tuple(dict.fromkeys(failures)),
            )

        reasons = ["NON_DEGRADING"]
        if repeated_failure_reduction:
            reasons.append("REPEATED_FAILURE_REDUCTION")
        return PromotionDecision(accepted=True, reasons=tuple(reasons))


class ExperiencePromotionService:
    def __init__(
        self,
        repository,
        *,
        version_store,
        regression_service: ExperienceRegressionService,
        selector: ExperienceRegressionSelector | None = None,
        gate: PromotionGate | None = None,
    ):
        self.repository = repository
        self.version_store = version_store
        self.regression_service = regression_service
        self.selector = selector or ExperienceRegressionSelector()
        self.gate = gate or PromotionGate()

    def validate_and_promote(self, candidate_version: int) -> PromotionDecision:
        candidate = self.repository.get_experience_skill_version(candidate_version)
        if candidate.status != "candidate":
            raise ValueError(
                f"experience skill version {candidate_version} is not candidate"
            )
        current = self.repository.get_current_experience_skill_version()
        if current is None:
            raise ValueError("a promoted baseline Experience Skill is required")

        regression_set = self.selector.select(self.repository)
        source_tasks = _candidate_source_task_ids(candidate.manifest_json)
        if source_tasks:
            regression_set = ExperienceRegressionSet(
                cases=tuple(
                    case
                    for case in regression_set.cases
                    if case.task_id not in source_tasks
                )
            )
        comparison = self.regression_service.compare(
            current_version=current.version,
            candidate_version=candidate_version,
            cases=regression_set,
        )
        decision = self.gate.evaluate(comparison)
        regression_payload = {
            "comparison": comparison.model_dump(mode="json"),
            "promotion_decision": decision.model_dump(mode="json"),
        }

        if decision.accepted:
            self.version_store.promote(
                candidate_version,
                regression=regression_payload,
            )
        elif decision.reasons == ("INSUFFICIENT_REGRESSION_CASES",):
            # Lack of an independent holdout is not evidence that the
            # structural rule is wrong. Keep the candidate quarantined and
            # retry it against a later completed task before learning from that task.
            self.repository.set_experience_skill_version_status(
                candidate_version,
                "candidate",
                regression=regression_payload,
            )
        else:
            reason = ";".join(decision.reasons)
            rejection_payload = {
                **regression_payload,
                "passed": False,
                "reason": reason,
            }
            rollback_entries = self._rejection_rollback_entries(
                current=current,
                candidate=candidate,
            )
            self.repository.reject_experience_skill_candidate_with_rollback(
                version=candidate_version,
                regression=rejection_payload,
                reason=f"Experience Skill v{candidate_version} rejected: {reason}",
                rollback_entries=rollback_entries,
                version_before=current.version,
            )
        return decision

    def _rejection_rollback_entries(self, *, current, candidate):
        current_manifest = dict(current.manifest_json or {})
        candidate_manifest = dict(candidate.manifest_json or {})
        current_ids = set(
            str(item)
            for item in (
                current_manifest.get("source_experience_ids")
                or dict(current_manifest.get("source_revisions") or {}).keys()
            )
        )
        candidate_ids = set(
            str(item)
            for item in (
                candidate_manifest.get("source_experience_ids")
                or dict(candidate_manifest.get("source_revisions") or {}).keys()
            )
        )

        rollback = []

        # Candidate-only rules must stop participating in future Reflection.
        for experience_id in sorted(candidate_ids - current_ids):
            latest = self.repository.get_experience(experience_id)
            if latest.status != "active":
                continue
            rollback.append(
                latest.model_copy(
                    update={
                        "revision": latest.revision + 1,
                        "status": "rejected",
                        "source_hash": None,
                    }
                )
            )

        # Rules removed by SPLIT / MERGE / SUPERSEDE are restored from the
        # latest pre-structural active revision, preserving all state-only
        # REINFORCE / WEAKEN updates that happened since the Skill was promoted.
        for experience_id in sorted(current_ids - candidate_ids):
            revisions = self.repository.list_experience_revisions(experience_id)
            active = [entry for entry in revisions if entry.status == "active"]
            if not active:
                continue
            previous_active = max(active, key=lambda entry: entry.revision)
            latest = max(revisions, key=lambda entry: entry.revision)
            if latest.status == "active":
                continue
            rollback.append(
                previous_active.model_copy(
                    update={
                        "revision": latest.revision + 1,
                        "status": "active",
                        "source_hash": None,
                    }
                )
            )

        return tuple(rollback)


def _succeeded(status: str) -> bool:
    return status.strip().lower() in {
        "success",
        "succeeded",
        "accept",
        "accepted",
        "qualified",
        "completed",
    }



def _candidate_source_task_ids(manifest: dict | None) -> set[str]:
    tasks: set[str] = set()
    for change in dict(manifest or {}).get("structural_changes") or ():
        if not isinstance(change, dict):
            continue
        for ref in change.get("evidence_refs") or ():
            if not isinstance(ref, dict):
                continue
            task_id = str(ref.get("task_id") or "").strip()
            if task_id:
                tasks.add(task_id)
    return tasks
