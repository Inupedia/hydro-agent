from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Mapping
from typing import Any

from hydro_agent.api.deps import AppDependencies
from hydro_agent.api.schemas import TaskCreateRequest, TaskSummary
from hydro_agent.execution.hashing import sha256_bytes
from hydro_agent.workbench.timeline import build_experiment_timeline

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


def build_runtime_task_config(
    workbench: Mapping[str, Any],
    *,
    base: Mapping[str, Any] | None = None,
    model_plan_id: str | None = None,
) -> dict[str, Any]:
    """Restore the bounded runtime window from persisted task provenance."""
    runtime = copy.deepcopy(dict(base or {}))
    runtime.update(copy.deepcopy(dict(workbench)))
    validation_start = runtime.get("validation_start_date")
    validation_end = runtime.get("validation_end_date")
    if validation_start:
        runtime["start_date"] = validation_start
    if validation_end:
        runtime["end_date"] = validation_end
    if model_plan_id:
        runtime["model_plan_id"] = model_plan_id
    return runtime


def create_workbench_task(deps: AppDependencies, payload: TaskCreateRequest) -> str:
    if payload.end_date < payload.start_date:
        raise ValueError("end_date before start_date")
    if payload.model_id != "xaj":
        raise ValueError("only xaj is enabled in the XAJ-first workbench")
    if payload.forcing_mode not in ("R", "F"):
        raise ValueError("invalid forcing_mode")
    plan = None
    plan_config = None
    if payload.model_plan_id:
        if deps.mode != "real":
            raise ValueError("真实计算服务未就绪，不能将完整模型方案送入模拟演示")
        if deps.model_plans is None:
            raise ValueError("建模服务未配置")
        try:
            plan = deps.model_plans.require_ready(payload.model_plan_id)
        except KeyError as exc:
            raise ValueError("模型方案不存在") from exc
        if payload.basin_id != plan["basin_id"]:
            raise ValueError("任务流域与模型方案不一致")
        if payload.forcing_mode != "R":
            raise ValueError("老师历史资料仅支持 R 回算；不可当作未来气象预报")
        from datetime import date, timedelta

        if (
            payload.start_date < date.fromisoformat(plan["suggested_start"])
            or payload.end_date + timedelta(days=3) > date.fromisoformat(plan["data_end"])
        ):
            raise ValueError("任务时段超出方案资料范围或预热长度不足")
        plan_config = json.loads(
            (deps.model_plans.directory(payload.model_plan_id) / "scheme.json").read_text(
                encoding="utf-8"
            )
        )
    elif deps.mode == "real":
        raise ValueError("请先新建并复核模型方案，或选择已有完整方案")

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
            # These remain the user-selected research period for provenance/UI.
            "start_date": payload.start_date.isoformat(),
            "end_date": payload.end_date.isoformat(),
            "max_agent_decision_rounds": payload.max_agent_decision_rounds,
            "max_optimization_cycles": payload.max_optimization_cycles,
        },
    }
    if plan_config is not None or deps.base_scheme_config is not None:
        base = plan_config if plan_config is not None else deps.base_scheme_config()
        for key in ("routing", "model_version", "model_plan_id"):
            if key in base:
                config[key] = copy.deepcopy(base[key])
        config["model_id"] = str(base.get("model_id") or "xaj")
        if base.get("warmup_days") is not None:
            config["warmup_days"] = int(base["warmup_days"])
        if isinstance(base.get("parameters"), dict) and base["parameters"]:
            config["parameters"] = copy.deepcopy(base["parameters"])
    if plan:
        config["model_plan_id"] = plan["plan_id"]
        config["model_plan_hash"] = plan["content_hash"]

    timeline = build_experiment_timeline(
        start_date=payload.start_date,
        end_date=payload.end_date,
        warmup_days=int(config["warmup_days"]),
        validation_days=payload.validation_days,
    )
    config["workbench"].update(timeline.as_dict())
    # Hard cost guard: the API can accept a decade of research data, but it may
    # not silently convert that into thousands of daily Gate/replay executions.
    if timeline.estimated_rolling_forecast_runs > 270:
        raise ValueError("validation window would create too many rolling XAJ executions")

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

    # Runtime compatibility: legacy workbench handlers still consume start/end.
    # Feed them the bounded holdout, while preserving the complete research
    # period under explicit names. This immediately prevents a 10-year study
    # from becoming a 10-year daily Gate and A11 replay.
    runtime_config = build_runtime_task_config(
        config["workbench"],
        base=payload.model_dump(mode="json"),
        model_plan_id=plan["plan_id"] if plan else None,
    )
    deps.task_configs[task_id] = runtime_config
    return task_id


def build_task_summary(deps: AppDependencies, task_id: str) -> TaskSummary:
    task = deps.repository.get_task(task_id)
    state = deps.repository.ensure_task_state(task_id)
    config = deps.task_configs.get(task_id) or {}
    model_id = str(config.get("model_id") or "xaj")
    start_date = config.get("research_start_date") or config.get("start_date")
    end_date = config.get("research_end_date") or config.get("end_date")
    if start_date is None or end_date is None:
        try:
            schemes = deps.repository.list_schemes(task_id=task_id)
            for scheme in schemes:
                workbench = (scheme.config_json or {}).get("workbench") or {}
                start_date = (
                    start_date
                    or workbench.get("research_start_date")
                    or workbench.get("start_date")
                )
                end_date = (
                    end_date
                    or workbench.get("research_end_date")
                    or workbench.get("end_date")
                )
                if not model_id or model_id == "xaj":
                    model_id = str(scheme.model_id or model_id or "xaj")
                if start_date and end_date:
                    break
        except Exception:
            pass
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
    created_at = None
    if getattr(task, "created_at", None) is not None:
        created_at = task.created_at.isoformat()
    forcing = getattr(task, "forcing_mode", None) or config.get("forcing_mode")
    return TaskSummary(
        task_id=task_id,
        basin_id=task.basin_id,
        model_id=model_id,
        phase=task.phase,  # type: ignore[arg-type]
        status=status,
        paused=bool(state.paused),
        current_scheme_id=state.current_scheme_id,
        model_plan_id=(
            (deps.repository.get_scheme(state.current_scheme_id).config_json or {}).get(
                "model_plan_id"
            )
            if state.current_scheme_id
            else None
        ),
        agent_rounds_used=state.agent_rounds_used,
        optimization_cycles_used=state.optimization_cycles_used,
        start_date=str(start_date) if start_date else None,
        end_date=str(end_date) if end_date else None,
        forcing_mode=forcing if forcing in ("R", "F") else None,
        created_at=created_at,
        workflow_id=getattr(task, "workflow_id", None),
        workflow_version=getattr(task, "workflow_version", None),
        workflow_hash=getattr(task, "workflow_hash", None),
    )


def uuid_suffix() -> str:
    return uuid.uuid4().hex[:12]
