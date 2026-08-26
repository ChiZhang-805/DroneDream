from __future__ import annotations

import os

import pytest

from dronedream_agent_app.custom_models import (
    CustomModelService,
    WindowsCredentialVault,
    detect_provider,
    validate_custom_base_url,
)
from dronedream_agent_app.storage import AppStore


class MemoryVault:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def put(self, name: str, secret: str) -> None:
        self.values[name] = secret

    def get(self, name: str) -> str:
        return self.values[name]

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def test_provider_detection_prefers_endpoint_and_has_safe_fallback():
    assert detect_provider("https://api.openai.com/v1")["provider"] == "openai"
    assert detect_provider("https://openrouter.ai/api/v1")["provider"] == "openrouter"
    assert (
        detect_provider("https://generativelanguage.googleapis.com/v1beta/openai")["provider"]
        == "gemini"
    )
    assert detect_provider("https://api.cerebras.ai/v1")["provider"] == "cerebras"
    assert detect_provider("https://open.bigmodel.cn/api/paas/v4")["provider"] == "zhipu"
    assert detect_provider("https://dashscope.aliyuncs.com/compatible-mode/v1")["icon"] == "qwen"
    assert detect_provider("https://api.x.ai/v1")["provider"] == "xai"
    assert detect_provider("https://api.anthropic.com/v1")["icon"] == "claude"
    assert detect_provider("https://bedrock-runtime.us-east-1.amazonaws.com")["icon"] == "bedrock"
    assert detect_provider("https://models.github.ai/inference")["provider"] == "github-models"
    assert detect_provider("https://private.example/v1", "gsk_example")["provider"] == "groq"
    assert detect_provider("https://private.example/v1", model_id="claude-sonnet-4") == {
        "provider": "anthropic",
        "icon": "claude",
    }
    assert detect_provider("https://private.example/v1", model_id="qwen3-max")["provider"] == "qwen"
    assert detect_provider("https://private.example/v1", model_id="grok-4")["icon"] == "grok"
    assert detect_provider("https://private.example/v1")["provider"] == "openai-compatible"


def test_custom_endpoint_requires_https_except_for_loopback():
    assert validate_custom_base_url("http://127.0.0.1:11434/v1").startswith("http://")
    with pytest.raises(ValueError, match="CUSTOM_MODEL_BASE_URL_INVALID"):
        validate_custom_base_url("http://models.example/v1")
    with pytest.raises(ValueError, match="CUSTOM_MODEL_BASE_URL_INVALID"):
        validate_custom_base_url("https://models.example/v1?token=secret")


def test_custom_catalog_and_grant_never_return_long_lived_key(tmp_path):
    store = AppStore(tmp_path)
    vault = MemoryVault()
    service = CustomModelService(store, vault)
    profile = service.create(
        display_name="Private Planner",
        base_url="https://models.example/v1",
        model_id="planner-72b",
        api_key="secret-customer-key",
        api_style="chat-completions",
    )
    profile_id = str(profile["profile_id"])
    catalog = service.catalog()
    assert catalog == [
        {
            "id": f"custom:{profile_id}",
            "model": "planner-72b",
            "label": "Private Planner",
            "provider": "openai-compatible",
            "icon": "generic",
            "source": "custom",
            "profile_id": profile_id,
        }
    ]
    assert "secret-customer-key" not in str(profile)
    assert "secret-customer-key" not in str(store.list_custom_models())

    thread = store.create_thread("custom", f"custom:{profile_id}")
    grant = service.issue_grant(profile_id, str(thread["thread_id"]))
    assert str(grant["grant"]).startswith("ddc_")
    connection = service.consume_grant(
        str(grant["grant"]), str(thread["thread_id"]), f"custom:{profile_id}"
    )
    assert connection.api_key == "secret-customer-key"
    with pytest.raises(ValueError, match="CUSTOM_MODEL_GRANT_INVALID"):
        service.consume_grant(str(grant["grant"]), str(thread["thread_id"]), f"custom:{profile_id}")


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI contract")
def test_windows_vault_round_trip_is_encrypted_at_rest(tmp_path):
    vault = WindowsCredentialVault(tmp_path)
    secret = "test-token-that-must-not-be-plaintext"
    vault.put("cmp-12345678", secret)
    blob = (tmp_path / "cmp-12345678.dpapi").read_bytes()
    assert secret.encode() not in blob
    assert vault.get("cmp-12345678") == secret
    vault.delete("cmp-12345678")
    assert not (tmp_path / "cmp-12345678.dpapi").exists()
