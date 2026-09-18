from __future__ import annotations

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.experience.regression import (
    ExperienceRegressionSelector,
    ExperienceRegressionService,
    RegressionComparison,
)


class PromotionDecision(FrozenModel):
    accepted: bool
    reasons: tuple[str, ...]


class PromotionGate:
    def __init__(self, *, quality_tolerance: float = 0.01):
        if quality_tolerance < 0:
            raise ValueError("quality_tolerance must be >= 0")
        self.quality_tolerance = quality_tolerance

    def evaluate(self, comparison: RegressionComparison) -> PromotionDecision:
        if not comparison.cases:
            return PromotionDecision(
                accepted=False,
                reasons=("INSUFFICIENT_REGRESSION_CASES",),
            )

        failures: list[str] = []
        repeated_failure_reduction = False

        for row in comparison.cases:
            if (
                row.case.hard_case
                and _succeeded(row.current.terminal_status)
                and not _succeeded(row.candidate.terminal_status)
            ):
                failures.append(f"HARD_CASE_REGRESSION:{row.case.task_id}")

            new_violations = set(row.candidate.guardrail_violations) - set(
                row.current.guardrail_violations
            )
            if new_violations:
                failures.append(
                    "NEW_GUARDRAIL_VIOLATION:"
                    f"{row.case.task_id}:{','.join(sorted(new_violations))}"
                )

            quality_delta = row.quality_delta
            if (
                quality_delta is not None
                and quality_delta < -self.quality_tolerance
            ):
                failures.append(
                    f"QUALITY_REGRESSION:{row.case.task_id}:{quality_delta:.6f}"
                )

            if row.repeated_failure_delta < 0:
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
        else:
            reason = ";".join(decision.reasons)
            self.version_store.reject(
                candidate_version,
                reason,
                regression=regression_payload,
            )
            self.repository.append_experience_evolution_event(
                event_type="REJECT",
                reason=f"Experience Skill v{candidate_version} rejected: {reason}",
                version_before=current.version,
                version_after=candidate_version,
            )
        return decision


def _succeeded(status: str) -> bool:
    return status.strip().lower() in {
        "success",
        "succeeded",
        "accept",
        "accepted",
        "qualified",
        "completed",
    }
