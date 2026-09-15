from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from hydro_agent.skills.manager import SkillManager

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillWriteRequest(BaseModel):
    skill_md: str = Field(min_length=1)


class SkillResourceWriteRequest(BaseModel):
    content: str


def _manager(request: Request) -> SkillManager:
    return request.app.state.skill_manager


@router.get("")
def list_skills(request: Request):
    return {"items": _manager(request).list_payload()}


@router.post("/reload")
def reload_skills(request: Request):
    manager = _manager(request)
    skill_ids = manager.registry.reload()
    return {"skill_ids": list(skill_ids), "count": len(skill_ids)}


@router.get("/{skill_id}")
def skill_detail(skill_id: str, request: Request):
    try:
        return _manager(request).detail_payload(skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="skill not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/{skill_id}")
def save_skill(skill_id: str, payload: SkillWriteRequest, request: Request):
    try:
        return _manager(request).save_skill(skill_id, payload.skill_md)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="skill not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{skill_id}/override")
def delete_skill_override(skill_id: str, request: Request):
    try:
        return _manager(request).delete_override(skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="user skill override not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{skill_id}/resources")
def list_skill_resources(skill_id: str, request: Request):
    try:
        return {"items": _manager(request).list_resources(skill_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="skill not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{skill_id}/resources/{resource_path:path}")
def read_skill_resource(skill_id: str, resource_path: str, request: Request):
    try:
        content = _manager(request).read_resource(skill_id, resource_path)
        return {"skill_id": skill_id, "path": resource_path, "content": content}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="skill or resource not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/{skill_id}/resources/{resource_path:path}")
def save_skill_resource(
    skill_id: str,
    resource_path: str,
    payload: SkillResourceWriteRequest,
    request: Request,
):
    try:
        return _manager(request).save_resource(skill_id, resource_path, payload.content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="skill not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
