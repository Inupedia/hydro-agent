from types import SimpleNamespace

from hydro_agent.experience.regression import ExperienceRegressionSelector


class SelectionRepository:
    def __init__(self):
        self.tasks = [
            SimpleNamespace(task_id="task-a", basin_id="basin-a"),
            SimpleNamespace(task_id="task-b", basin_id="basin-b"),
            SimpleNamespace(task_id="task-hard", basin_id="basin-a"),
        ]
        self.evidence = {
            "task-a": [
                SimpleNamespace(
                    metrics_json={"peak_ratio": 0.8, "pbias_percent": 12.0},
                    gates_json={},
                    observations_json=[],
                    status="succeeded",
                )
            ],
            "task-b": [
                SimpleNamespace(
                    metrics_json={"peak_timing_lag_days": 1.0, "high_flow_mae": 2.0},
                    gates_json={},
                    observations_json=[],
                    status="succeeded",
                )
            ],
            "task-hard": [
                SimpleNamespace(
                    metrics_json={"peak_ratio": 1.2},
                    gates_json={"gate_status": "ROLLBACK"},
                    observations_json=[],
                    status="ROLLBACK",
                )
            ],
        }

    def list_tasks(self):
        return self.tasks

    def list_evidence(self, task_id):
        return self.evidence[task_id]

    def list_agent_decisions(self, task_id):
        version = 3 if task_id == "task-hard" else 2
        return [SimpleNamespace(experience_audit_json={"skill_version": version})]


def test_regression_selector_covers_tags_and_prioritizes_hard_cases():
    selected = ExperienceRegressionSelector().select(
        SelectionRepository(),
        limit_per_tag=1,
    )

    assert selected.cases[0].task_id == "task-hard"
    assert selected.cases[0].hard_case is True
    assert selected.cases[0].baseline_version == 3

    by_task = {case.task_id: case for case in selected.cases}
    assert "peak-under" in by_task["task-a"].tags
    assert "volume-bias" in by_task["task-a"].tags
    assert "timing-late" in by_task["task-b"].tags
    assert "high-flow" in by_task["task-b"].tags
    assert "peak-over" in by_task["task-hard"].tags
    assert all(any(tag.startswith("basin:") for tag in case.tags) for case in selected.cases)



def test_regression_service_preserves_per_case_deltas():
    from hydro_agent.experience.regression import (
        ExperienceRegressionService,
        ExperienceReplayOutcome,
        RegressionCase,
    )

    class ScriptedRunner:
        def __init__(self):
            self.outcomes = {
                ("task-a", 3): ExperienceReplayOutcome(
                    task_id="task-a",
                    experience_skill_version=3,
                    terminal_status="succeeded",
                    optimization_cycles=4,
                    repeated_failed_experiments=2,
                    quality_score=0.72,
                ),
                ("task-a", 4): ExperienceReplayOutcome(
                    task_id="task-a",
                    experience_skill_version=4,
                    terminal_status="succeeded",
                    optimization_cycles=3,
                    repeated_failed_experiments=1,
                    quality_score=0.74,
                ),
                ("task-hard", 3): ExperienceReplayOutcome(
                    task_id="task-hard",
                    experience_skill_version=3,
                    terminal_status="succeeded",
                    optimization_cycles=5,
                    repeated_failed_experiments=1,
                    quality_score=0.68,
                ),
                ("task-hard", 4): ExperienceReplayOutcome(
                    task_id="task-hard",
                    experience_skill_version=4,
                    terminal_status="failed",
                    optimization_cycles=5,
                    repeated_failed_experiments=1,
                    quality_score=0.60,
                    guardrail_violations=("illegal_group",),
                ),
            }

        def run(self, *, task_id, experience_skill_version):
            return self.outcomes[(task_id, experience_skill_version)]

    comparison = ExperienceRegressionService(ScriptedRunner()).compare(
        current_version=3,
        candidate_version=4,
        cases=(
            RegressionCase(task_id="task-a", tags=("peak-under",)),
            RegressionCase(task_id="task-hard", tags=("peak-over",), hard_case=True),
        ),
    )

    assert comparison.cases[0].repeated_failure_delta == -1
    assert comparison.cases[0].quality_delta == 0.02
    assert comparison.cases[1].case.hard_case is True
    assert comparison.cases[1].candidate.terminal_status == "failed"



def _comparison(*, hard_failure=False, quality_delta=0.0, new_violation=False, repeated_delta=0):
    from hydro_agent.experience.regression import (
        ExperienceReplayOutcome,
        RegressionCase,
        RegressionCaseComparison,
        RegressionComparison,
    )

    current_failed = 2
    candidate_failed = max(0, current_failed + repeated_delta)
    return RegressionComparison(
        current_version=3,
        candidate_version=4,
        cases=(
            RegressionCaseComparison(
                case=RegressionCase(
                    task_id="hard" if hard_failure else "ordinary",
                    tags=("peak-under",),
                    hard_case=hard_failure,
                ),
                current=ExperienceReplayOutcome(
                    task_id="hard" if hard_failure else "ordinary",
                    experience_skill_version=3,
                    terminal_status="succeeded",
                    optimization_cycles=4,
                    repeated_failed_experiments=current_failed,
                    quality_score=0.70,
                ),
                candidate=ExperienceReplayOutcome(
                    task_id="hard" if hard_failure else "ordinary",
                    experience_skill_version=4,
                    terminal_status="failed" if hard_failure else "succeeded",
                    optimization_cycles=3,
                    repeated_failed_experiments=candidate_failed,
                    quality_score=0.70 + quality_delta,
                    guardrail_violations=(("new_violation",) if new_violation else ()),
                ),
            ),
        ),
    )


def test_promotion_gate_rejects_hard_case_regression():
    from hydro_agent.experience.promotion import PromotionGate

    decision = PromotionGate().evaluate(_comparison(hard_failure=True))
    assert decision.accepted is False
    assert any(reason.startswith("HARD_CASE_REGRESSION") for reason in decision.reasons)


def test_promotion_gate_rejects_quality_and_guardrail_regression():
    from hydro_agent.experience.promotion import PromotionGate

    quality = PromotionGate(quality_tolerance=0.01).evaluate(
        _comparison(quality_delta=-0.03)
    )
    guardrail = PromotionGate().evaluate(_comparison(new_violation=True))

    assert quality.accepted is False
    assert any(reason.startswith("QUALITY_REGRESSION") for reason in quality.reasons)
    assert guardrail.accepted is False
    assert any(reason.startswith("NEW_GUARDRAIL_VIOLATION") for reason in guardrail.reasons)


def test_promotion_gate_accepts_non_degrading_candidate_with_fewer_failures():
    from hydro_agent.experience.promotion import PromotionGate

    decision = PromotionGate().evaluate(
        _comparison(quality_delta=0.01, repeated_delta=-1)
    )

    assert decision.accepted is True
    assert decision.reasons == ("NON_DEGRADING", "REPEATED_FAILURE_REDUCTION")
