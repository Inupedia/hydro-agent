from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from hydro_agent.agent.contracts import MAX_AGENT_ROUNDS, MAX_OPTIMIZATION_CYCLES
from hydro_agent.api.deps import AppDependencies
from hydro_agent.api.schemas import RunSummary

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Single local worker that drives AgentRuntime until terminal/paused."""

    def __init__(self, deps: AppDependencies):
        self.deps = deps
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._active_task_id: str | None = None
        self._future: Future | None = None

    def start(self, task_id: str) -> RunSummary:
        with self._lock:
            if self._active_task_id is not None and not self._is_idle_locked():
                raise RuntimeError("local worker busy")
            state = self.deps.repository.ensure_task_state(task_id)
            task = self.deps.repository.get_task(task_id)
            # Completed evaluation path: refreshing the Run page must not reset follow-up.
            if task.phase == "E" and not state.needs_follow_up and not state.paused:
                return self.status(task_id)
            self.deps.clear_llm_error(task_id)
            self.deps.repository.update_task_state(task_id, paused=False, needs_follow_up=True)
            self._active_task_id = task_id
            self._future = self._pool.submit(self._run, task_id)
        return self.status(task_id)

    def pause(self, task_id: str) -> RunSummary:
        self.deps.repository.ensure_task_state(task_id)
        self.deps.repository.update_task_state(task_id, paused=True)
        return self.status(task_id)

    def resume(self, task_id: str) -> RunSummary:
        with self._lock:
            self.deps.repository.ensure_task_state(task_id)
            self.deps.clear_llm_error(task_id)
            self.deps.repository.update_task_state(task_id, paused=False, needs_follow_up=True)
            if self._active_task_id == task_id and not self._is_idle_locked():
                # In-flight worker will observe cleared pause on the next round.
                return self.status(task_id)
            if self._active_task_id is not None and not self._is_idle_locked():
                raise RuntimeError("local worker busy")
            self._active_task_id = task_id
            self._future = self._pool.submit(self._run, task_id)
        return self.status(task_id)

    def status(self, task_id: str) -> RunSummary:
        task = self.deps.repository.get_task(task_id)
        state = self.deps.repository.ensure_task_state(task_id)
        evidence = self.deps.repository.list_evidence(task_id)
        last = evidence[-1] if evidence else None
        trace = self.deps.get_llm_trace(task_id)
        with self._lock:
            active = self._active_task_id == task_id and not self._is_idle_locked()
        return RunSummary(
            task_id=task_id,
            worker_active=active,
            paused=bool(state.paused),
            phase=task.phase,  # type: ignore[arg-type]
            status=_task_status(task, state, active),
            needs_follow_up=bool(state.needs_follow_up),
            agent_rounds_remaining=max(0, MAX_AGENT_ROUNDS - state.agent_rounds_used),
            optimization_cycles_remaining=max(
                0, MAX_OPTIMIZATION_CYCLES - state.optimization_cycles_used
            ),
            current_scheme_id=state.current_scheme_id,
            last_action=last.action if last else None,
            last_hypothesis=None,
            llm_streaming=bool(trace.streaming),
            llm_text=trace.text,
            llm_error=trace.error,
            llm_decision_action=trace.decision_action,
        )

    def _run(self, task_id: str) -> None:
        try:
            runtime = self.deps.runtime_factory()
            runtime.run_until_terminal(task_id)
        except Exception as exc:
            logger.exception("workbench worker failed for task %s", task_id)
            self.deps.finish_llm_trace(task_id, error=str(exc))
        finally:
            with self._lock:
                if self._active_task_id == task_id:
                    self._active_task_id = None
                    self._future = None

    def _is_idle_locked(self) -> bool:
        if self._future is None:
            return True
        return self._future.done()

    def shutdown(self) -> None:
        with self._lock:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._active_task_id = None
            self._future = None


def _task_status(task, state, active: bool) -> str:
    if task.terminal_status:
        return str(task.terminal_status)
    if state.paused:
        return "paused"
    if active:
        return "running"
    if task.phase == "E" and not state.needs_follow_up:
        return "completed"
    if state.agent_rounds_used == 0:
        return "created"
    return "idle"
