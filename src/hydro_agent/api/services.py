from __future__ import annotations

import copy
import json
import uuid
from datetime import date, timedelta

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
        if payload.model_mode != plan.get("model_mode", "lumped"):
            raise ValueError("任务空间模式与模型方案不一致，请重新生成模型方案")
        if payload.forcing_mode != "R":
            raise ValueError("历史率定仅支持实测/再分析驱动资料")
        if (
            payload.start_date < date.fromisoformat(plan["suggested_start"])
            or payload.end_date + timedelta(days=3) > date.fromisoformat(plan["data_end"])
        ):
            raise ValueError("任务时段超出方案资料范围或预热长度不足")
        hist = int(plan.get("history_days") or 0)
        if hist and plan.get("data_start"):
            data_start = date.fromisoformat(plan["data_start"])
            calib_issue = payload.start_date - timedelta(days=1)
            if calib_issue < data_start + timedelta(days=hist - 1):
                raise ValueError(
                    "任务开始日过早：率定需要足够预热历史，请使用方案建议时段"
                )
        plan_config = json.loads(
            (deps.model_plans.directory(payload.model_plan_id) / "scheme.json").read_text(
                encoding="utf-8"
            )
        )
    elif deps.mode == "real":
        raise ValueError("请先完成流域模型准备；Agent 率定必须绑定可复现的模型方案")

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
        "model_mode": payload.model_mode,
        "warmup_days": 30,
        "parameters": copy.deepcopy(DEFAULT_XAJ_PARAMS),
        "workbench": {
            "template_scheme_id": payload.base_scheme_id,
            "model_mode": payload.model_mode,
            "allow_optimization": True,
            "start_date": payload.start_date.isoformat(),
            "end_date": payload.end_date.isoformat(),
            "max_agent_decision_rounds": payload.max_agent_decision_rounds,
            "max_optimization_cycles": payload.max_optimization_cycles,
        },
    }
    if plan_config is not None or deps.base_scheme_config is not None:
        base = plan_config if plan_config is not None else deps.base_scheme_config()
        for key in ("routing", "model_version", "model_plan_id", "model_mode", "units"):
            if key in base:
                config[key] = copy.deepcopy(base[key])
        config["model_id"] = str(base.get("model_id") or "xaj")
        config["model_mode"] = str(base.get("model_mode") or payload.model_mode)
        if base.get("warmup_days") is not None:
            config["warmup_days"] = int(base["warmup_days"])
        if isinstance(base.get("parameters"), dict) and base["parameters"]:
            config["parameters"] = copy.deepcopy(base["parameters"])
    if plan:
        config["model_plan_id"] = plan["plan_id"]
        config["model_plan_hash"] = plan["content_hash"]
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
    model_mode = str(config.get("model_mode") or "lumped")
    start_date = config.get("start_date")
    end_date = config.get("end_date")
    if start_date is None or end_date is None or "model_mode" not in config:
        try:
            schemes = deps.repository.list_schemes(task_id=task_id)
            for scheme in schemes:
                scheme_config = scheme.config_json or {}
                workbench = scheme_config.get("workbench") or {}
                start_date = start_date or workbench.get("start_date")
                end_date = end_date or workbench.get("end_date")
                model_mode = str(
                    scheme_config.get("model_mode") or workbench.get("model_mode") or model_mode
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
    current_config = (
        deps.repository.get_scheme(state.current_scheme_id).config_json
        if state.current_scheme_id
        else {}
    ) or {}
    return TaskSummary(
        task_id=task_id,
        basin_id=task.basin_id,
        model_id=model_id,
        model_mode=model_mode if model_mode in ("lumped", "distributed") else "lumped",  # type: ignore[arg-type]
        phase=task.phase,  # type: ignore[arg-type]
        status=status,
        paused=bool(state.paused),
        current_scheme_id=state.current_scheme_id,
        model_plan_id=current_config.get("model_plan_id"),
        agent_rounds_used=state.agent_rounds_used,
        optimization_cycles_used=state.optimization_cycles_used,
        start_date=str(start_date) if start_date else None,
        end_date=str(end_date) if end_date else None,
        forcing_mode=forcing if forcing in ("R", "F") else None,
        created_at=created_at,
    )


def uuid_suffix() -> str:
    return uuid.uuid4().hex[:12]
