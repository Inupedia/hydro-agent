import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from hydro_agent.api.schemas import TaskCreateRequest, TaskSummary
from hydro_agent.api.services import build_task_summary, create_workbench_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", status_code=201, response_model=TaskSummary)
def create_task(payload: TaskCreateRequest, request: Request) -> TaskSummary:
    deps = request.app.state.deps
    try:
        task_id = create_workbench_task(deps, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_task_summary(deps, task_id)


@router.get("", response_model=list[TaskSummary])
def list_tasks(request: Request) -> list[TaskSummary]:
    deps = request.app.state.deps
    return [build_task_summary(deps, task.task_id) for task in deps.repository.list_tasks()]


@router.get("/{task_id}", response_model=TaskSummary)
def get_task(task_id: str, request: Request) -> TaskSummary:
    deps = request.app.state.deps
    try:
        return build_task_summary(deps, task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, request: Request) -> None:
    deps = request.app.state.deps
    try:
        deps.repository.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    executor = getattr(deps, "executor", None)
    if executor is not None:
        try:
            if executor.status(task_id).worker_active:
                raise HTTPException(status_code=409, detail="任务正在运行，无法删除")
        except HTTPException:
            raise
        except Exception:
            pass
    deps.repository.delete_task(task_id)
    deps.report_artifacts.pop(task_id, None)
    deps.metrics_by_task.pop(task_id, None)
    deps.llm_traces.pop(task_id, None)
    deps.agent_round_logs.pop(task_id, None)
    deps.task_configs.pop(task_id, None)
    if deps.report_root:
        shutil.rmtree(Path(deps.report_root) / task_id, ignore_errors=True)
