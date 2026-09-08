import json
import time
from collections.abc import Callable
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
        return self.complete_stream(messages, max_tokens=max_tokens, on_delta=None)

    def complete_stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 1024,
        on_delta: Callable[[str], None] | None = None,
    ) -> Completion:
        if not 1 <= max_tokens <= 4096:
            raise ValueError("max_tokens must be between 1 and 4096")
        request = Request(
            self.settings.base_url + "/chat/completions",
            data=json.dumps(
                {
                    "model": self.settings.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "stream": True,
                    "reasoning_effort": "low",
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.settings.api_key.get_secret_value(),
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        started = time.monotonic()
        content_parts: list[str] = []
        thinking_open = False
        thinking_closed = False
        model_name = self.settings.model
        try:
            with build_opener(NoRedirect()).open(
                request, timeout=self.settings.timeout_seconds
            ) as response:
                while True:
                    raw_line = response.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if data.get("model"):
                        model_name = str(data["model"])
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    piece = delta.get("content") or ""
                    if reasoning:
                        if not thinking_open:
                            token = f"[thinking]\n{reasoning}"
                            thinking_open = True
                        else:
                            token = reasoning
                        content_parts.append(token)
                        if on_delta:
                            on_delta(token)
                    if piece:
                        if thinking_open and not thinking_closed:
                            sep = "\n[/thinking]\n"
                            content_parts.append(sep)
                            if on_delta:
                                on_delta(sep)
                            thinking_closed = True
                        content_parts.append(piece)
                        if on_delta:
                            on_delta(piece)
            content = "".join(content_parts).strip()
            if not content:
                raise LLMError("provider returned empty completion")
            visible = content
            if "[/thinking]" in visible:
                visible = visible.split("[/thinking]", 1)[-1].strip()
            return Completion(
                model=model_name or self.settings.model,
                content=visible or content,
                prompt_tokens=0,
                completion_tokens=0,
                wall_time_seconds=time.monotonic() - started,
            )
        except HTTPError as exc:
            raise LLMError(f"provider HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise LLMError("provider connection failed or timed out") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("invalid provider response") from None
