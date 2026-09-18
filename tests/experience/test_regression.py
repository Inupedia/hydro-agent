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
