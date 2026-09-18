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
