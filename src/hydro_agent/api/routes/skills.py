from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from hydro_agent.skills.manager import SkillManager

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillWriteRequest(BaseModel):
    skill_md: str = Field(min_length=1)


class SkillResourceWriteRequest(BaseModel):
    content: str


class SkillBindingWriteRequest(BaseModel):
    activation_stages: tuple[str, ...] = ()
    activation_model_ids: tuple[str, ...] = ()


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


@router.post("/migrate-legacy")
def migrate_legacy_skills(request: Request):
    """Rename user overlays still using the retired twelve Skill IDs."""

    return _manager(request).migrate_legacy_overrides()


@router.get("/{skill_id}")
def skill_detail(skill_id: str, request: Request):
    try:
        return _manager(request).detail_payload(skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="skill not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{skill_id}/validate")
def validate_skill(skill_id: str, payload: SkillWriteRequest, request: Request):
    return _manager(request).validate_skill(skill_id, payload.skill_md)


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


@router.put("/{skill_id}/binding")
def save_skill_binding(skill_id: str, payload: SkillBindingWriteRequest, request: Request):
    try:
        return _manager(request).save_binding(
            skill_id,
            activation_stages=payload.activation_stages,
            activation_model_ids=payload.activation_model_ids,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="skill not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{skill_id}/copy-from-builtin")
def copy_skill_from_builtin(skill_id: str, request: Request):
    try:
        return _manager(request).copy_from_builtin(skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="skill not found") from exc
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
