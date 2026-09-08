from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from hydro_agent.api.schemas import RunSummary, TimelineItem
from hydro_agent.api.timeline import timeline_label

router = APIRouter(prefix="/api/tasks", tags=["runs"])


@router.post("/{task_id}/run", response_model=RunSummary)
def start_run(task_id: str, request: Request) -> RunSummary:
    deps = request.app.state.deps
    executor = request.app.state.executor
    try:
        deps.repository.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    try:
        return executor.start(task_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/pause", response_model=RunSummary)
def pause_run(task_id: str, request: Request) -> RunSummary:
    executor = request.app.state.executor
    try:
        return executor.pause(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc


@router.post("/{task_id}/resume", response_model=RunSummary)
def resume_run(task_id: str, request: Request) -> RunSummary:
    executor = request.app.state.executor
    try:
        return executor.resume(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{task_id}/run", response_model=RunSummary)
def get_run(task_id: str, request: Request) -> RunSummary:
    executor = request.app.state.executor
    try:
        return executor.status(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc


@router.get("/{task_id}/timeline", response_model=list[TimelineItem])
def get_timeline(task_id: str, request: Request) -> list[TimelineItem]:
    deps = request.app.state.deps
    try:
        deps.repository.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    items: list[TimelineItem] = []
    for row in deps.repository.list_evidence(task_id):
        items.append(
            TimelineItem(
                id=row.evidence_id,
                occurred_at=row.created_at,
                label=timeline_label(row.action, row.status),
                status=row.status,
                action=row.action,
                evidence_id=row.evidence_id,
                details={
                    "action_run_id": row.action_run_id or "",
                    "observations": list(row.observations_json or []),
                    "metrics": dict(row.metrics_json or {}),
                    "gates": dict(row.gates_json or {}),
                },
            )
        )
    return items
