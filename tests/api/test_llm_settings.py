from __future__ import annotations


def test_llm_settings_roundtrip_keeps_key_hidden(client, app_dependencies):
    response = client.get("/api/llm/settings")
    assert response.status_code == 200
    assert "base_url" in response.json()
    assert "api_key_set" in response.json()

    payload = {
        "provider_id": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key": "sk-test-secret",
        "timeout_seconds": 60,
        "max_retries": 4,
    }
    saved = client.put("/api/llm/settings", json=payload)
    assert saved.status_code == 200
    assert saved.json()["api_key_set"] is True
    assert "sk-test-secret" not in saved.text

    loaded = client.get("/api/llm/settings")
    assert loaded.status_code == 200
    assert loaded.json()["provider_id"] == "deepseek"
    assert loaded.json()["base_url"] == "https://api.deepseek.com"
    assert loaded.json()["model"] == "deepseek-chat"
    assert loaded.json()["api_key_set"] is True
    assert "sk-test-secret" not in loaded.text
    assert app_dependencies.runtime_llm_settings is not None
    assert app_dependencies.runtime_llm_settings.model == "deepseek-chat"
