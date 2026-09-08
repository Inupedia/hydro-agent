import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel

from .settings import LLMSettings


class LLMError(RuntimeError):
    """Sanitized provider failure: no headers, key or raw response body."""


class Completion(FrozenModel):
    model: str
    content: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    wall_time_seconds: float = Field(ge=0)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SiliconFlowClient:
    def __init__(self, settings: LLMSettings):
        self.settings = settings

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int = 1024) -> Completion:
        if not 1 <= max_tokens <= 4096:
            raise ValueError("max_tokens must be between 1 and 4096")
        request = Request(
            self.settings.base_url + "/chat/completions",
            data=json.dumps(
                {
                    "model": self.settings.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "stream": False,
                    "reasoning_effort": "low",
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.settings.api_key.get_secret_value(),
            },
            method="POST",
        )
        started = time.monotonic()
        # No automatic retries: each call can spend the user's API budget.
        try:
            with build_opener(NoRedirect()).open(
                request, timeout=self.settings.timeout_seconds
            ) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise LLMError("provider response exceeds limit")
            data = json.loads(raw)
            choice = data["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise LLMError("provider returned incomplete completion")
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise LLMError("provider returned empty completion")
            if data.get("model") != self.settings.model:
                raise LLMError("provider returned unexpected model")
            usage = data["usage"]
            return Completion(
                model=data["model"],
                content=content,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                wall_time_seconds=time.monotonic() - started,
            )
        except HTTPError as exc:
            raise LLMError(f"provider HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise LLMError("provider connection failed or timed out") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("invalid provider response") from None
