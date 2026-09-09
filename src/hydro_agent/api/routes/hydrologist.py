from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/hydrologist", tags=["hydrologist tune"])


def _service(request: Request):
    value = getattr(request.app.state.deps, "hydrologist", None)
    if value is None:
        raise HTTPException(503, "水文员调参服务未配置")
    return value


def _graph(request: Request):
    value = getattr(request.app.state.deps, "hydrologist_graph", None)
    if value is None:
        raise HTTPException(503, "水文员 LangGraph 未配置")
    return value


@router.get("/sessions")
def list_sessions(request: Request):
    return _service(request).list()


class CreateSession(BaseModel):
    plan_id: str
    task_id: str | None = None


@router.post("/sessions", status_code=201)
def create_session(payload: CreateSession, request: Request):
    try:
        return _service(request).create(plan_id=payload.plan_id, task_id=payload.task_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request):
    try:
        return _service(request).get(session_id)
    except KeyError as exc:
        raise HTTPException(404, "调参会话不存在") from exc


class StepRequest(BaseModel):
    step: str = Field(description="baseline | update_params | compare | submit")
    params: dict[str, float] | None = None
    note: str = ""
    task_id: str | None = None


@router.post("/sessions/{session_id}/step")
def run_step(session_id: str, payload: StepRequest, request: Request):
    graph = _graph(request)
    try:
        result = graph.invoke(
            {
                "session_id": session_id,
                "step": payload.step,
                "params": payload.params or {},
                "note": payload.note,
                "task_id": payload.task_id,
            }
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    session = result.get("session")
    if session is None:
        raise HTTPException(500, "LangGraph 未返回会话状态")
    if session.get("status") == "failed" and session.get("error"):
        raise HTTPException(409, session["error"])
    return session
