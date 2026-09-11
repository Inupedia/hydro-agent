from __future__ import annotations

from fastapi import APIRouter, HTTPException

from hydro_agent.workflow.definition import list_versions, load_definition
from hydro_agent.workflow.generate import definition_api_payload

router = APIRouter(prefix="/api/workflow-definition", tags=["workflow"])


@router.get("")
def current_workflow_definition():
    payload = definition_api_payload()
    payload["available_versions"] = list(list_versions())
    return payload


@router.get("/{version}")
def workflow_definition_version(version: str):
    try:
        load_definition(version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="workflow version not found") from exc
    return definition_api_payload(version)
