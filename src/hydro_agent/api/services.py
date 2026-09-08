from __future__ import annotations

import copy
import json
import uuid

from hydro_agent.api.deps import AppDependencies
from hydro_agent.api.schemas import TaskCreateRequest, TaskSummary
from hydro_agent.execution.hashing import sha256_bytes

DEFAULT_XAJ_PARAMS = {
    "K": 0.75,
    "B": 0.25,
    "IM": 0.06,
    "UM": 20.0,
    "LM": 60.0,
    "DM": 40.0,
    "C": 0.16,
    "SM": 20.0,
    "EX": 1.2,
    "KI": 0.3,
    "KG": 0.4,
    "CS": 0.9,
    "L": 2.0,
    "CI": 0.8,
    "CG": 0.98,
}


def create_workbench_task(deps: AppDependencies, payload: TaskCreateRequest) -> str:
    if payload.end_date < payload.start_date:
        raise ValueError("end_date before start_date")
    if payload.model_id != "xaj":
        raise ValueError("only xaj is enabled in the XAJ-first workbench")
    if payload.forcing_mode not in ("R", "F"):
        raise ValueError("invalid forcing_mode")
    task_id = f"task-{uuid_suffix()}"
    scheme_id = f"{task_id}--{payload.base_scheme_id}"
    deps.repository.create_task(
        task_id=task_id,
        basin_id=payload.basin_id,
        phase="B",
        forcing_mode=payload.forcing_mode,
    )
    config = {
        "model_id": "xaj",
        "warmup_days": 30,
        "parameters": copy.deepcopy(DEFAULT_XAJ_PARAMS),
        "workbench": {
            "template_scheme_id": payload.base_scheme_id,
            "allow_optimization": payload.allow_optimization,
            "start_date": payload.start_date.isoformat(),
            "end_date": payload.end_date.isoformat(),
            "max_agent_decision_rounds": payload.max_agent_decision_rounds,
            "max_optimization_cycles": payload.max_optimization_cycles,
        },
    }
    content_hash = sha256_bytes(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    deps.repository.create_scheme(
        scheme_id=scheme_id,
        task_id=task_id,
        model_id="xaj",
        status="base",
        config=config,
        content_hash=content_hash,
    )
    deps.repository.ensure_task_state(task_id, current_scheme_id=scheme_id)
    deps.task_configs[task_id] = payload.model_dump(mode="json")
    return task_id


def build_task_summary(deps: AppDependencies, task_id: str) -> TaskSummary:
    task = deps.repository.get_task(task_id)
    state = deps.repository.ensure_task_state(task_id)
    config = deps.task_configs.get(task_id) or {}
    model_id = str(config.get("model_id") or "xaj")
    active = False
    executor = getattr(deps, "executor", None)
    if executor is not None:
        try:
            active = executor.status(task_id).worker_active
        except Exception:
            active = False
    status = "created"
    if task.terminal_status:
        status = str(task.terminal_status)
    elif state.paused:
        status = "paused"
    elif active:
        status = "running"
    elif task.phase == "E" and not state.needs_follow_up:
        status = "completed"
    elif state.agent_rounds_used > 0:
        status = "idle"
    return TaskSummary(
        task_id=task_id,
        basin_id=task.basin_id,
        model_id=model_id,
        phase=task.phase,  # type: ignore[arg-type]
        status=status,
        paused=bool(state.paused),
        current_scheme_id=state.current_scheme_id,
        agent_rounds_used=state.agent_rounds_used,
        optimization_cycles_used=state.optimization_cycles_used,
    )


def uuid_suffix() -> str:
    return uuid.uuid4().hex[:12]
