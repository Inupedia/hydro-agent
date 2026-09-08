import threading

import pytest

from hydro_agent.api.executor import TaskExecutor


@pytest.fixture
def seeded_tasks(repository):
    repository.create_task(task_id="task-1", basin_id="b1", phase="B", forcing_mode="R")
    repository.create_scheme(
        scheme_id="scheme-1",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={"model_id": "xaj", "warmup_days": 2, "parameters": {"K": 0.7}},
        content_hash="h1",
    )
    repository.ensure_task_state("task-1", current_scheme_id="scheme-1")
    repository.create_task(task_id="task-2", basin_id="b1", phase="B", forcing_mode="R")
    repository.create_scheme(
        scheme_id="scheme-2",
        task_id="task-2",
        model_id="xaj",
        status="base",
        config={"model_id": "xaj", "warmup_days": 2, "parameters": {"K": 0.7}},
        content_hash="h2",
    )
    repository.ensure_task_state("task-2", current_scheme_id="scheme-2")
    return repository


def test_executor_rejects_second_concurrent_local_task(app_dependencies, seeded_tasks):
    executor = TaskExecutor(app_dependencies)
    app_dependencies.executor = executor  # type: ignore[attr-defined]
    gate = threading.Event()

    class BlockingRuntime:
        def run_until_terminal(self, task_id):
            gate.wait(timeout=2.0)

    app_dependencies.runtime_factory = lambda: BlockingRuntime()  # type: ignore[method-assign]
    executor.start("task-1")
    with pytest.raises(RuntimeError, match="local worker busy"):
        executor.start("task-2")
    gate.set()
    executor.shutdown()


def test_pause_sets_persisted_state_without_inventing_terminal_status(
    app_dependencies, seeded_tasks, repository
):
    executor = TaskExecutor(app_dependencies)
    executor.pause("task-1")
    state = repository.get_task_state("task-1")
    assert state.paused is True
    assert repository.get_task("task-1").terminal_status is None
