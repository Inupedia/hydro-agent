from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel


class RegressionCase(FrozenModel):
    task_id: str
    tags: tuple[str, ...]
    hard_case: bool = False
    baseline_version: int | None = Field(default=None, ge=1)


class ExperienceRegressionSet(FrozenModel):
    cases: tuple[RegressionCase, ...] = ()


class ExperienceRegressionSelector:
    """Pick a compact representative task set from persisted historical evidence."""

    def select(
        self,
        repository,
        *,
        limit_per_tag: int = 2,
    ) -> ExperienceRegressionSet:
        if limit_per_tag < 1:
            raise ValueError("limit_per_tag must be >= 1")

        discovered = [
            case
            for task in repository.list_tasks()
            if (case := self._case(repository, task)) is not None
            and case.tags
        ]
        discovered.sort(key=lambda case: (not case.hard_case, case.task_id))

        selected: dict[str, RegressionCase] = {}
        tag_counts: dict[str, int] = defaultdict(int)

        # Hard cases are always included first, even if that exceeds ordinary
        # per-tag quotas.
        for case in discovered:
            if not case.hard_case:
                continue
            selected[case.task_id] = case
            for tag in case.tags:
                tag_counts[tag] += 1

        for case in discovered:
            if case.task_id in selected:
                continue
            useful_tags = [
                tag for tag in case.tags
                if tag_counts[tag] < limit_per_tag
            ]
            if not useful_tags:
                continue
            selected[case.task_id] = case
            for tag in case.tags:
                tag_counts[tag] += 1

        return ExperienceRegressionSet(
            cases=tuple(
                sorted(
                    selected.values(),
                    key=lambda case: (not case.hard_case, case.task_id),
                )
            )
        )

    def _case(self, repository, task) -> RegressionCase | None:
        try:
            state = repository.get_task_state(task.task_id)
            schemes = repository.list_schemes(task_id=task.task_id)
        except KeyError:
            return None
        if not schemes:
            return None
        if (
            str(getattr(task, "phase", "")) != "E"
            or bool(state.paused)
            or bool(state.needs_follow_up)
            or str(getattr(task, "terminal_status", "") or "").lower()
            in {"cancelled", "failed", "error"}
        ):
            return None

        evidence = repository.list_evidence(task.task_id)
        if not evidence or not any(
            str(getattr(row, "action", "")) == "A10_EVALUATE_REPORT"
            and _successful_status(getattr(row, "status", ""))
            for row in evidence
        ):
            return None

        tags = {f"basin:{task.basin_id}"}
        hard_case = False

        for row in evidence:
            metrics = dict(row.metrics_json or {})
            gates = dict(row.gates_json or {})
            observations = " ".join(str(item) for item in (row.observations_json or ())).lower()

            peak_ratio = _number(metrics.get("peak_ratio"))
            if peak_ratio is not None:
                if peak_ratio < 0.95:
                    tags.add("peak-under")
                elif peak_ratio > 1.05:
                    tags.add("peak-over")

            timing = _number(
                metrics.get("peak_timing_lag_days")
                if "peak_timing_lag_days" in metrics
                else metrics.get("peak_timing_lag_leads")
            )
            if timing is not None:
                if timing < 0:
                    tags.add("timing-early")
                elif timing > 0:
                    tags.add("timing-late")

            pbias = _number(metrics.get("pbias_percent"))
            if pbias is not None and abs(pbias) >= 5.0:
                tags.add("volume-bias")

            if any("low_flow" in str(key).lower() for key in metrics) or "low-flow" in observations:
                tags.add("low-flow")
            if any("high_flow" in str(key).lower() for key in metrics) or "high-flow" in observations:
                tags.add("high-flow")

            gate_status = str(gates.get("status") or gates.get("gate_status") or row.status).upper()
            if (
                str(gates.get("hard_case") or "").lower() == "true"
                or row.status == "failed"
                or gate_status == "ROLLBACK"
            ):
                hard_case = True

        baseline_version = None
        for decision in repository.list_agent_decisions(task.task_id):
            audit = decision.experience_audit_json or {}
            raw = audit.get("skill_version")
            if isinstance(raw, int) and raw >= 1:
                baseline_version = raw

        return RegressionCase(
            task_id=task.task_id,
            tags=tuple(sorted(tags)),
            hard_case=hard_case,
            baseline_version=baseline_version,
        )


class ExperienceReplayOutcome(FrozenModel):
    task_id: str
    experience_skill_version: int = Field(ge=1)
    terminal_status: str
    optimization_cycles: int = Field(ge=0)
    repeated_failed_experiments: int = Field(ge=0)
    quality_score: float | None = None
    guardrail_violations: tuple[str, ...] = ()


class ExperienceReplayRunner(Protocol):
    def run(
        self,
        *,
        task_id: str,
        experience_skill_version: int,
    ) -> ExperienceReplayOutcome: ...


class RegressionCaseComparison(FrozenModel):
    case: RegressionCase
    current: ExperienceReplayOutcome
    candidate: ExperienceReplayOutcome

    @property
    def repeated_failure_delta(self) -> int:
        return (
            self.candidate.repeated_failed_experiments
            - self.current.repeated_failed_experiments
        )

    @property
    def quality_delta(self) -> float | None:
        if self.current.quality_score is None or self.candidate.quality_score is None:
            return None
        return round(self.candidate.quality_score - self.current.quality_score, 12)


class RegressionComparison(FrozenModel):
    current_version: int = Field(ge=1)
    candidate_version: int = Field(ge=1)
    cases: tuple[RegressionCaseComparison, ...]


class ExperienceRegressionService:
    def __init__(self, runner: ExperienceReplayRunner):
        self.runner = runner

    def compare(
        self,
        *,
        current_version: int,
        candidate_version: int,
        cases: ExperienceRegressionSet | tuple[RegressionCase, ...],
    ) -> RegressionComparison:
        selected = cases.cases if isinstance(cases, ExperienceRegressionSet) else tuple(cases)
        comparisons = []
        for case in selected:
            current = self.runner.run(
                task_id=case.task_id,
                experience_skill_version=current_version,
            )
            candidate = self.runner.run(
                task_id=case.task_id,
                experience_skill_version=candidate_version,
            )
            comparisons.append(
                RegressionCaseComparison(
                    case=case,
                    current=current,
                    candidate=candidate,
                )
            )
        return RegressionComparison(
            current_version=current_version,
            candidate_version=candidate_version,
            cases=tuple(comparisons),
        )


def _number(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None



def _successful_status(value: object) -> bool:
    return str(value or "").strip().lower() in {
        "success",
        "succeeded",
        "completed",
        "accept",
        "accepted",
        "qualified",
    }
