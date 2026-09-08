import io
import json
from urllib.error import HTTPError

import pytest
from pydantic import ValidationError

from hydro_agent.llm import client
from hydro_agent.llm.settings import LLMSettings


def test_settings_secret_and_override(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("SILICONFLOW_API_KEY=file-secret\n", encoding="utf-8")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "environment-secret")
    settings = LLMSettings.from_env(path)
    assert settings.api_key.get_secret_value() == "environment-secret"
    assert "environment-secret" not in repr(settings)
    assert "environment-secret" not in settings.model_dump_json()
    assert settings.model == "zai-org/GLM-5.3"


@pytest.mark.parametrize(
    "url",
    [
        "http://api.siliconflow.cn/v1",
        "https://evil.example/v1",
        "https://api.siliconflow.cn@evil.example/v1",
    ],
)
def test_endpoint_rejection(url):
    with pytest.raises(ValidationError):
        LLMSettings(base_url=url, api_key="test-secret")


def test_request_and_usage(monkeypatch):
    class StreamResponse:
        def __init__(self, chunks: list[bytes]):
            self._chunks = list(chunks)

        def readline(self):
            if not self._chunks:
                return b""
            return self._chunks.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Opener:
        def open(self, request, timeout):
            body = json.loads(request.data)
            assert body["model"] == "zai-org/GLM-5.3"
            assert body["max_tokens"] == 1024
            assert body["stream"] is True
            assert request.get_header("Authorization") == "Bearer test-secret"
            chunk = {
                "model": body["model"],
                "choices": [{"delta": {"content": "OK"}}],
            }
            return StreamResponse(
                [
                    f"data: {json.dumps(chunk)}\n".encode(),
                    b"data: [DONE]\n",
                ]
            )

    monkeypatch.setattr(client, "build_opener", lambda *args: Opener())
    result = client.SiliconFlowClient(LLMSettings(api_key="test-secret")).complete(
        [{"role": "user", "content": "OK"}]
    )
    assert result.content == "OK"
    assert result.prompt_tokens == 0


def test_error_redacted_without_retry_on_auth(monkeypatch):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(1)
            raise HTTPError(request.full_url, 401, "test-secret", {}, io.BytesIO(b"test-secret"))

    monkeypatch.setattr(client, "build_opener", lambda *args: Opener())
    with pytest.raises(client.LLMError, match="provider HTTP 401") as error:
        client.SiliconFlowClient(LLMSettings(api_key="test-secret")).complete([])
    assert "test-secret" not in str(error.value)
    assert len(calls) == 1


def test_retries_transient_http_503(monkeypatch):
    calls = []
    sleeps: list[float] = []

    class StreamResponse:
        def __init__(self, chunks: list[bytes]):
            self._chunks = list(chunks)

        def readline(self):
            if not self._chunks:
                return b""
            return self._chunks.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Opener:
        def open(self, request, timeout):
            calls.append(1)
            if len(calls) < 3:
                raise HTTPError(request.full_url, 503, "busy", {}, io.BytesIO(b"busy"))
            chunk = {
                "model": "zai-org/GLM-5.3",
                "choices": [{"delta": {"content": "OK"}}],
            }
            return StreamResponse(
                [
                    f"data: {json.dumps(chunk)}\n".encode(),
                    b"data: [DONE]\n",
                ]
            )

    monkeypatch.setattr(client, "build_opener", lambda *args: Opener())
    monkeypatch.setattr(client.time, "sleep", lambda seconds: sleeps.append(seconds))
    result = client.SiliconFlowClient(
        LLMSettings(api_key="test-secret", max_retries=4)
    ).complete([{"role": "user", "content": "OK"}])
    assert result.content == "OK"
    assert len(calls) == 3
    assert sleeps == [0.8, 1.6]
