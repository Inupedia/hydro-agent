from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr, ValidationError

from hydro_agent.llm.settings import LLMSettings

router = APIRouter(prefix="/api/llm", tags=["llm"])


class LLMConfigRequest(BaseModel):
    provider_id: str = Field(default="custom", min_length=1, max_length=64)
    base_url: str = Field(min_length=8, max_length=512)
    model: str = Field(min_length=1, max_length=256)
    api_key: str = ""
    timeout_seconds: int = Field(default=60, ge=5, le=300)
    max_retries: int = Field(default=4, ge=0, le=8)


def _deps(request: Request):
    return request.app.state.deps


def _env_values() -> dict[str, str]:
    env_file = Path(os.getenv("HYDRO_AGENT_ENV_FILE", ".env"))
    values = dict(dotenv_values(env_file)) if env_file.is_file() else {}
    values.update(os.environ)
    return values


def _env_or_runtime(deps):
    runtime = deps.runtime_llm_settings
    if runtime is not None:
        return (
            runtime.base_url,
            runtime.model,
            runtime.api_key.get_secret_value(),
            runtime.timeout_seconds,
            runtime.max_retries,
        )
    values = _env_values()
    return (
        values.get("HYDRO_LLM_BASE_URL", LLMSettings.model_fields["base_url"].default),
        values.get("HYDRO_LLM_MODEL", LLMSettings.model_fields["model"].default),
        values.get("HYDRO_LLM_API_KEY") or values.get("SILICONFLOW_API_KEY") or "",
        int(values.get("HYDRO_LLM_TIMEOUT_SECONDS", 60)),
        int(values.get("HYDRO_LLM_MAX_RETRIES", 4)),
    )


@router.get("/settings")
def get_llm_settings(request: Request):
    deps = _deps(request)
    base_url, model, api_key, timeout_seconds, max_retries = _env_or_runtime(deps)
    provider_id = deps.runtime_llm_provider_id or "siliconflow"
    return {
        "provider_id": provider_id,
        "base_url": base_url,
        "model": model,
        "api_key_set": bool(api_key),
        "timeout_seconds": timeout_seconds,
        "max_retries": max_retries,
    }


@router.put("/settings")
def save_llm_settings(payload: LLMConfigRequest, request: Request):
    deps = _deps(request)
    _, _, current_key, _, _ = _env_or_runtime(deps)
    key = payload.api_key or current_key
    try:
        settings = LLMSettings(
            base_url=payload.base_url,
            model=payload.model,
            api_key=SecretStr(key),
            timeout_seconds=payload.timeout_seconds,
            max_retries=payload.max_retries,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    deps.runtime_llm_settings = settings
    deps.runtime_llm_provider_id = payload.provider_id
    deps.provider_model = settings.model
    return {
        "ok": True,
        "provider_id": payload.provider_id,
        "base_url": payload.base_url,
        "model": settings.model,
        "api_key_set": bool(settings.api_key.get_secret_value()),
        "timeout_seconds": settings.timeout_seconds,
        "max_retries": settings.max_retries,
    }
