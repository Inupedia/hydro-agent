import threading
import time

import pytest

from hydro_agent.api.executor import (
    TaskExecutor,
    _agent_evolution_enabled,
    _task_status,
)


def seed_task(repository, n: int):
    task_id = f"task-{n}"
    repository.create_task(task_id=task_id, basin_id="b1", phase="B", forcing_mode="R")
    repository.create_scheme(
        scheme_id=f"scheme-{n}",
        task_id=task_id,
        model_id="xaj",
        status="base",
        config={"model_id": "xaj", "warmup_days": 2, "parameters": {"K": 0.7}},
        content_hash=f"h{n}",
    )
    repository.ensure_task_state(task_id, current_scheme_id=f"scheme-{n}")
    return task_id


@pytest.fixture
def seeded_tasks(repository):
    for n in range(1, 7):
        seed_task(repository, n)
    return repository


def blocking_runtime(gates: dict[str, threading.Event]):
    class BlockingRuntime:
        def run_until_terminal(self, task_id):
            gates[task_id].wait(timeout=2.0)

    return BlockingRuntime()


def test_executor_runs_limit_then_queues_and_promotes(app_dependencies, seeded_tasks):
    executor = TaskExecutor(app_dependencies, max_workers=1, max_queue=2)
    app_dependencies.executor = executor  # type: ignore[attr-defined]
    gates = {f"task-{n}": threading.Event() for n in (1, 2)}
    app_dependencies.runtime_factory = lambda: blocking_runtime(gates)  # type: ignore[method-assign]

    first = executor.start("task-1")
    assert first.status == "running"
    assert first.worker_active is True
    second = executor.start("task-2")
    assert second.status == "queued"
    assert second.queue_position == 1
    assert second.worker_active is False
    assert second.worker_slots_used == 1
    assert second.worker_slots_max == 1

    gates["task-1"].set()
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and executor.status("task-2").status != "running":
        time.sleep(0.02)
    assert executor.status("task-2").status == "running"
    gates["task-2"].set()
    executor.shutdown()


def test_executor_rejects_when_queue_is_full(app_dependencies, seeded_tasks):
    executor = TaskExecutor(app_dependencies, max_workers=1, max_queue=1)
    app_dependencies.executor = executor  # type: ignore[attr-defined]
    gate = threading.Event()
    app_dependencies.runtime_factory = lambda: blocking_runtime({"task-1": gate, "task-2": gate, "task-3": gate})  # type: ignore[method-assign]
    executor.start("task-1")
    queued = executor.start("task-2")
    assert queued.status == "queued"
    with pytest.raises(RuntimeError, match="计算席位已满"):
        executor.start("task-3")
    gate.set()
    executor.shutdown()


def test_executor_allows_five_concurrent_then_queues_sixth(app_dependencies, seeded_tasks):
    executor = TaskExecutor(app_dependencies, max_workers=5, max_queue=20)
    app_dependencies.executor = executor  # type: ignore[attr-defined]
    hold = threading.Event()
    app_dependencies.runtime_factory = lambda: blocking_runtime(
        {f"task-{n}": hold for n in range(1, 7)}
    )  # type: ignore[method-assign]
    for n in range(1, 6):
        summary = executor.start(f"task-{n}")
        assert summary.status == "running"
    sixth = executor.start("task-6")
    assert sixth.status == "queued"
    assert sixth.queue_position == 1
    assert executor.slots() == {"run_slots_used": 5, "run_slots_max": 5, "run_queue": 1}
    hold.set()
    executor.shutdown()


def test_pause_sets_persisted_state_without_inventing_terminal_status(
    app_dependencies, seeded_tasks, repository
):
    executor = TaskExecutor(app_dependencies)
    executor.pause("task-1")
    state = repository.get_task_state("task-1")
    assert state.paused is True
    assert repository.get_task("task-1").terminal_status is None
    executor.shutdown()



def test_completed_status_wins_while_experience_regression_finishes(repository):
    task_id = seed_task(repository, 99)
    repository.set_task_phase(task_id, "F")
    repository.set_task_phase(task_id, "E")
    repository.update_task_state(
        task_id,
        paused=False,
        needs_follow_up=False,
    )

    task = repository.get_task(task_id)
    state = repository.get_task_state(task_id)

    assert _task_status(task, state, active=True, queued=False) == "completed"



def test_executor_skips_experience_evolution_for_disabled_task(
    app_dependencies,
    repository,
):
    task_id = seed_task(repository, 77)
    app_dependencies.task_configs[task_id] = {
        "agent_evolution_enabled": False,
    }

    calls = []

    class EvolutionSpy:
        def process_completed_task(self, completed_task_id):
            calls.append(completed_task_id)

    class Runtime:
        def run_until_terminal(self, completed_task_id):
            return []

    app_dependencies.experience_evolution = EvolutionSpy()
    app_dependencies.runtime_factory = lambda: Runtime()
    executor = TaskExecutor(app_dependencies)

    assert _agent_evolution_enabled(app_dependencies, task_id) is False
    executor._run(task_id)
    assert calls == []
    executor.shutdown()


def test_executor_runs_experience_evolution_for_enabled_task(
    app_dependencies,
    repository,
):
    task_id = seed_task(repository, 78)
    app_dependencies.task_configs[task_id] = {
        "agent_evolution_enabled": True,
    }

    calls = []

    class EvolutionSpy:
        def process_completed_task(self, completed_task_id):
            calls.append(completed_task_id)

    class Runtime:
        def run_until_terminal(self, completed_task_id):
            return []

    app_dependencies.experience_evolution = EvolutionSpy()
    app_dependencies.runtime_factory = lambda: Runtime()
    executor = TaskExecutor(app_dependencies)

    assert _agent_evolution_enabled(app_dependencies, task_id) is True
    executor._run(task_id)
    assert calls == [task_id]
    executor.shutdown()
