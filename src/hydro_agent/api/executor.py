from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from hydro_agent.agent.contracts import MAX_AGENT_ROUNDS, MAX_OPTIMIZATION_CYCLES
from hydro_agent.api.deps import AppDependencies
from hydro_agent.api.schemas import RunSummary

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT_RUNS = 5
DEFAULT_MAX_QUEUED_RUNS = 20


def _env_int(name: str, override: int | None, default: int, *, minimum: int) -> int:
    if override is not None:
        value = override
    else:
        raw = os.environ.get(name, "").strip()
        value = int(raw) if raw else default
    return max(minimum, value)


class TaskExecutor:
    """Bounded local workers that drive LangGraph until terminal/paused.

    Concurrent calibration is capped (default 5). Extra starts wait in a small
    in-process FIFO instead of a message broker. Overflow beyond the queue is
    rejected with 409 so later users see a seat-full message instead of hanging.
    """

    def __init__(
        self,
        deps: AppDependencies,
        *,
        max_workers: int | None = None,
        max_queue: int | None = None,
    ):
        self.deps = deps
        self.max_workers = _env_int(
            "HYDRO_MAX_CONCURRENT_RUNS", max_workers, DEFAULT_MAX_CONCURRENT_RUNS, minimum=1
        )
        self.max_queue = _env_int(
            "HYDRO_MAX_QUEUED_RUNS", max_queue, DEFAULT_MAX_QUEUED_RUNS, minimum=0
        )
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="hydro-run")
        self._running: dict[str, Future] = {}
        self._queued: list[str] = []

    def start(self, task_id: str) -> RunSummary:
        self._validate_plan(task_id)
        with self._lock:
            return self._admit_locked(task_id)

    def pause(self, task_id: str) -> RunSummary:
        self.deps.repository.ensure_task_state(task_id)
        self.deps.repository.update_task_state(task_id, paused=True)
        with self._lock:
            if task_id in self._queued:
                self._queued.remove(task_id)
            return self._status_locked(task_id)

    def resume(self, task_id: str) -> RunSummary:
        self._validate_plan(task_id)
        with self._lock:
            return self._admit_locked(task_id)

    def cancel(self, task_id: str) -> RunSummary:
        self.deps.repository.ensure_task_state(task_id)
        self.deps.repository.set_task_terminal_status(task_id, "cancelled")
        self.deps.repository.update_task_state(task_id, paused=False, needs_follow_up=False)
        with self._lock:
            if task_id in self._queued:
                self._queued.remove(task_id)
            return self._status_locked(task_id)

    def status(self, task_id: str) -> RunSummary:
        with self._lock:
            return self._status_locked(task_id)

    def is_occupied(self, task_id: str) -> bool:
        with self._lock:
            self._reap_locked()
            return task_id in self._running or task_id in self._queued

    def slots(self) -> dict[str, int]:
        with self._lock:
            self._reap_locked()
            return {
                "run_slots_used": len(self._running),
                "run_slots_max": self.max_workers,
                "run_queue": len(self._queued),
            }

    def _admit_locked(self, task_id: str) -> RunSummary:
        self._reap_locked()
        state = self.deps.repository.ensure_task_state(task_id)
        task = self.deps.repository.get_task(task_id)
        if task.phase == "E" and not state.needs_follow_up and not state.paused:
            return self._status_locked(task_id)
        if task_id in self._running or task_id in self._queued:
            return self._status_locked(task_id)
        self.deps.clear_llm_error(task_id)
        self.deps.repository.update_task_state(task_id, paused=False, needs_follow_up=True)
        if len(self._running) < self.max_workers:
            self._submit_locked(task_id)
        elif len(self._queued) < self.max_queue:
            self._queued.append(task_id)
        else:
            raise RuntimeError(
                f"计算席位已满（最多同时运行 {self.max_workers} 个任务），请稍后再试"
            )
        return self._status_locked(task_id)

    def _status_locked(self, task_id: str) -> RunSummary:
        self._reap_locked()
        task = self.deps.repository.get_task(task_id)
        state = self.deps.repository.ensure_task_state(task_id)
        evidence = self.deps.repository.list_evidence(task_id)
        decisions = self.deps.repository.list_agent_decisions(task_id)
        last = evidence[-1] if evidence else None
        latest_decision = decisions[-1] if decisions else None
        trace = self.deps.get_llm_trace(task_id)
        running = task_id in self._running
        try:
            queue_position = self._queued.index(task_id) + 1
        except ValueError:
            queue_position = None
        return RunSummary(
            task_id=task_id,
            worker_active=running,
            paused=bool(state.paused),
            phase=task.phase,  # type: ignore[arg-type]
            status=_task_status(task, state, running, queued=queue_position is not None),
            needs_follow_up=bool(state.needs_follow_up),
            agent_rounds_remaining=max(0, MAX_AGENT_ROUNDS - state.agent_rounds_used),
            optimization_cycles_remaining=max(
                0, MAX_OPTIMIZATION_CYCLES - state.optimization_cycles_used
            ),
            current_scheme_id=state.current_scheme_id,
            current_round_number=(
                trace.round_number
                if running and trace.round_number > 0
                else state.agent_rounds_used + 1
                if running
                else (latest_decision.round_number if latest_decision else None)
            ),
            current_decision_id=(
                latest_decision.decision_id
                if latest_decision
                else None
            ),
            last_action=last.action if last else None,
            last_hypothesis=None,
            llm_streaming=bool(trace.streaming),
            llm_text=trace.text,
            llm_error=trace.error,
            llm_decision_action=trace.decision_action,
            queue_position=queue_position,
            worker_slots_used=len(self._running),
            worker_slots_max=self.max_workers,
        )

    def _submit_locked(self, task_id: str) -> None:
        self._running[task_id] = self._pool.submit(self._run, task_id)

    def _run(self, task_id: str) -> None:
        try:
            self._validate_plan(task_id)
            runtime = (
                self.deps.runtime_for_task(task_id)
                if self.deps.runtime_for_task
                else self.deps.runtime_factory()
            )
            runtime.run_until_terminal(task_id)
            evolution = self.deps.experience_evolution
            if evolution is not None and _agent_evolution_enabled(self.deps, task_id):
                try:
                    evolution.process_completed_task(task_id)
                except Exception:
                    # Learning must never invalidate an already completed
                    # hydrologic experiment. Keep the failure visible in logs.
                    logger.exception(
                        "experience evolution failed for completed task %s",
                        task_id,
                    )
        except Exception as exc:
            logger.exception("workbench worker failed for task %s", task_id)
            self.deps.finish_llm_trace(task_id, error=str(exc))
        finally:
            with self._lock:
                self._running.pop(task_id, None)
                self._promote_locked()

    def _promote_locked(self) -> None:
        self._reap_locked()
        while self._queued and len(self._running) < self.max_workers:
            next_id = self._queued.pop(0)
            try:
                state = self.deps.repository.ensure_task_state(next_id)
            except KeyError:
                continue
            if state.paused:
                continue
            self._submit_locked(next_id)

    def _reap_locked(self) -> None:
        done = [task_id for task_id, future in self._running.items() if future.done()]
        for task_id in done:
            self._running.pop(task_id, None)

    def _validate_plan(self, task_id: str):
        from hydro_agent.workflow.definition import CURRENT_VERSION

        task = self.deps.repository.get_task(task_id)
        if task.workflow_version and task.workflow_version != CURRENT_VERSION:
            raise RuntimeError(
                f"旧任务绑定流程 v{task.workflow_version}，当前运行器使用 v{CURRENT_VERSION}。"
                "请新建任务使用连续的 Action 编号；历史证据保留原编号。"
            )
        state = self.deps.repository.ensure_task_state(task_id)
        config = (
            self.deps.repository.get_scheme(state.current_scheme_id).config_json
            if state.current_scheme_id
            else {}
        )
        plan_id = config.get("model_plan_id")
        if not plan_id:
            if self.deps.mode == "real":
                raise RuntimeError("旧任务缺少完整模型方案，请新建任务并选择已复核方案")
            return
        if self.deps.model_plans is None:
            raise RuntimeError("建模服务不可用")
        try:
            plan = self.deps.model_plans.require_ready(plan_id)
            if plan["content_hash"] != config.get("model_plan_hash"):
                raise ValueError("模型方案版本变化，需重新创建任务")
        except (ValueError, KeyError) as exc:
            raise RuntimeError(str(exc)) from exc

    def shutdown(self) -> None:
        with self._lock:
            self._queued.clear()
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._running.clear()


def _task_status(task, state, active: bool, *, queued: bool) -> str:
    if task.terminal_status:
        return str(task.terminal_status)
    if queued:
        return "queued"
    if state.paused:
        return "paused"
    if task.phase == "E" and not state.needs_follow_up:
        return "completed"
    if active:
        return "running"
    if state.agent_rounds_used == 0:
        return "created"
    return "idle"



def _agent_evolution_enabled(deps, task_id: str) -> bool:
    config = dict(deps.task_configs.get(task_id) or {})
    if "agent_evolution_enabled" in config:
        return bool(config["agent_evolution_enabled"])
    try:
        state = deps.repository.get_task_state(task_id)
        if not state.current_scheme_id:
            return False
        scheme = deps.repository.get_scheme(state.current_scheme_id)
        workbench = dict((scheme.config_json or {}).get("workbench") or {})
        raw = workbench.get("agent_evolution_enabled")
        if raw is not None:
            return bool(raw)
        return state.experience_state_snapshot_json is not None
    except KeyError:
        return False
