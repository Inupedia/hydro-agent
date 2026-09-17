import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values
from pydantic import Field, SecretStr, field_validator

from hydro_agent.execution.contracts import FrozenModel


class LLMSettings(FrozenModel):
    base_url: str = "https://api.siliconflow.cn/v1"
    model: str = "zai-org/GLM-5.3"
    api_key: SecretStr = Field(repr=False)
    timeout_seconds: int = Field(default=60, gt=0, le=300)
    max_retries: int = Field(default=4, ge=0, le=8)

    @field_validator("api_key")
    @classmethod
    def nonempty_key(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError("LLM API key is required")
        return value

    @field_validator("base_url")
    @classmethod
    def provider_url(cls, value):
        parsed = urlparse(value)
        if (
            parsed.scheme not in ("https", "http")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "expected an OpenAI-compatible HTTPS endpoint without query/fragment"
            )
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("http is only allowed for localhost endpoints")
        return value.rstrip("/")

    @classmethod
    def from_env(cls, env_file: Path | None = Path(".env")):
        # Explicit file only; do not search parents or mutate process environment.
        values = dict(dotenv_values(env_file)) if env_file and env_file.is_file() else {}
        values.update(os.environ)
        return cls(
            base_url=values.get("HYDRO_LLM_BASE_URL", cls.model_fields["base_url"].default),
            model=values.get("HYDRO_LLM_MODEL", cls.model_fields["model"].default),
            api_key=SecretStr(
                values.get("HYDRO_LLM_API_KEY")
                or values.get("SILICONFLOW_API_KEY")
                or ""
            ),
            timeout_seconds=values.get("HYDRO_LLM_TIMEOUT_SECONDS", 60),
            max_retries=values.get("HYDRO_LLM_MAX_RETRIES", 4),
        )
