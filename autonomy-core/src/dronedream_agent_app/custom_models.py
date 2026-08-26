"""User-owned model profiles with local encrypted credentials."""

from __future__ import annotations

import ctypes
import os
import re
import secrets
import threading
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from openai import APIStatusError, OpenAI

from .storage import AppStore

ApiStyle = Literal["responses", "chat-completions"]


class CredentialVault(Protocol):
    def put(self, name: str, secret: str) -> None: ...
    def get(self, name: str) -> str: ...
    def delete(self, name: str) -> None: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsCredentialVault:
    """DPAPI CurrentUser vault; encrypted blobs are useless outside this Windows user."""

    def __init__(self, root: Path) -> None:
        if os.name != "nt":
            raise RuntimeError("CUSTOM_MODEL_CREDENTIAL_VAULT_UNAVAILABLE")
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]

    def _path(self, name: str) -> Path:
        if not re.fullmatch(r"[a-z0-9-]{8,80}", name):
            raise ValueError("CUSTOM_MODEL_PROFILE_ID_INVALID")
        return self.root / f"{name}.dpapi"

    def _protect(self, value: bytes) -> bytes:
        source_buffer = ctypes.create_string_buffer(value)
        source = _DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
        output = _DataBlob()
        if not self._crypt32.CryptProtectData(
            ctypes.byref(source), "DroneDream AUTONOMY", None, None, None, 1, ctypes.byref(output)
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)

    def _unprotect(self, value: bytes) -> bytes:
        source_buffer = ctypes.create_string_buffer(value)
        source = _DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
        output = _DataBlob()
        if not self._crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)

    def put(self, name: str, secret: str) -> None:
        target = self._path(name)
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(self._protect(secret.encode("utf-8")))
        temporary.replace(target)

    def get(self, name: str) -> str:
        try:
            return self._unprotect(self._path(name).read_bytes()).decode("utf-8")
        except FileNotFoundError as error:
            raise KeyError(name) from error

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)


@dataclass(frozen=True)
class ModelConnection:
    selection_id: str
    provider: str
    model_id: str
    api_key: str
    base_url: str
    api_style: ApiStyle
    capability_id: str
    source: Literal["default", "custom"]


@dataclass(frozen=True)
class _Grant:
    connection: ModelConnection
    thread_id: str
    expires_at: datetime


_PROVIDERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("openai", "openai", ("api.openai.com",)),
    ("azure-openai", "azure-openai", ("openai.azure.com", "services.ai.azure.com")),
    ("anthropic", "claude", ("api.anthropic.com",)),
    ("deepseek", "deepseek", ("api.deepseek.com",)),
    ("kimi", "kimi", ("api.moonshot.ai", "moonshot.cn")),
    ("openrouter", "openrouter", ("openrouter.ai",)),
    ("xai", "xai", ("api.x.ai",)),
    ("groq", "groq", ("api.groq.com",)),
    ("mistral", "mistral", ("api.mistral.ai",)),
    ("together", "together", ("api.together.xyz",)),
    ("qwen", "qwen", ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com")),
    ("zhipu", "zhipu", ("open.bigmodel.cn",)),
    ("minimax", "minimax", ("api.minimax.chat", "api.minimaxi.com")),
    ("doubao", "doubao", ("volces.com", "volcengineapi.com")),
    ("hunyuan", "hunyuan", ("hunyuan.tencentcloudapi.com",)),
    ("baichuan", "baichuan", ("api.baichuan-ai.com",)),
    ("stepfun", "stepfun", ("api.stepfun.com",)),
    ("siliconflow", "siliconflow", ("api.siliconflow.cn", "api.siliconflow.com")),
    ("gemini", "gemini", ("generativelanguage.googleapis.com",)),
    ("vertexai", "vertexai", ("aiplatform.googleapis.com",)),
    ("cerebras", "cerebras", ("api.cerebras.ai",)),
    ("cohere", "cohere", ("api.cohere.ai",)),
    ("perplexity", "perplexity", ("api.perplexity.ai",)),
    ("nvidia", "nvidia", ("integrate.api.nvidia.com",)),
    ("cloudflare", "cloudflare", ("api.cloudflare.com",)),
    ("replicate", "replicate", ("api.replicate.com",)),
    ("huggingface", "huggingface", ("huggingface.co",)),
    ("github-models", "github", ("models.github.ai", "models.inference.ai.azure.com")),
    ("fireworks", "fireworks", ("api.fireworks.ai",)),
    ("sambanova", "sambanova", ("api.sambanova.ai",)),
    ("novita", "novita", ("api.novita.ai",)),
    ("ai21", "ai21", ("api.ai21.com",)),
    ("upstage", "upstage", ("api.upstage.ai",)),
    ("modelscope", "modelscope", ("modelscope.cn",)),
    ("yi", "yi", ("api.lingyiwanwu.com",)),
    ("ollama", "ollama", ("127.0.0.1", "localhost")),
)

_PROVIDER_ICON_BY_NAME = {provider: icon for provider, icon, _hosts in _PROVIDERS}
_PROVIDER_ICON_BY_NAME.update(
    {
        "claude": "claude",
        "grok": "grok",
        "glm": "zhipu",
        "lmstudio": "lmstudio",
        "moonshot": "kimi",
        "yi": "yi",
    }
)

_MODEL_PROVIDER_HINTS: tuple[tuple[str, str, str], ...] = (
    (r"(^|[/._-])claude([/._-]|$)", "anthropic", "claude"),
    (r"(^|[/._-])gemini([/._-]|$)", "gemini", "gemini"),
    (r"(^|[/._-])grok([/._-]|$)", "xai", "grok"),
    (r"(^|[/._-])(gpt|o1|o3|o4|codex)([/._-]|$)", "openai", "openai"),
    (r"deepseek", "deepseek", "deepseek"),
    (r"(^|[/._-])(kimi|moonshot)([/._-]|$)", "kimi", "kimi"),
    (r"qwen", "qwen", "qwen"),
    (r"(^|[/._-])(glm|chatglm)([/._-]|$)", "zhipu", "zhipu"),
    (r"minimax", "minimax", "minimax"),
    (r"(^|[/._-])doubao([/._-]|$)", "doubao", "doubao"),
    (r"hunyuan", "hunyuan", "hunyuan"),
    (r"baichuan", "baichuan", "baichuan"),
    (r"(^|[/._-])step([/._-]|$)", "stepfun", "stepfun"),
    (r"(mistral|mixtral|codestral)", "mistral", "mistral"),
    (r"(^|[/._-])command([/._-]|$)", "cohere", "cohere"),
    (r"(^|[/._-])sonar([/._-]|$)", "perplexity", "perplexity"),
    (r"(^|[/._-])yi([/._-]|$)", "yi", "yi"),
    (r"(jamba|jurassic)", "ai21", "ai21"),
)


def validate_custom_base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        parsed.scheme not in ({"http", "https"} if loopback else {"https"})
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("CUSTOM_MODEL_BASE_URL_INVALID")
    return value.strip().rstrip("/")


def detect_provider(base_url: str, api_key: str = "", model_id: str = "") -> dict[str, str]:
    host = (urlparse(base_url).hostname or "").lower()
    if host.startswith("bedrock-runtime.") and host.endswith(".amazonaws.com"):
        return {"provider": "bedrock", "icon": "bedrock"}
    for provider, icon, hosts in _PROVIDERS:
        if any(host == value or host.endswith(f".{value}") for value in hosts):
            if provider == "ollama" and "1234" in urlparse(base_url).netloc:
                return {"provider": "lmstudio", "icon": "lmstudio"}
            return {"provider": provider, "icon": icon}
    prefix = api_key[:12].lower()
    if prefix.startswith("sk-or-"):
        return {"provider": "openrouter", "icon": "openrouter"}
    if prefix.startswith("gsk_"):
        return {"provider": "groq", "icon": "groq"}
    if prefix.startswith("aiza"):
        return {"provider": "gemini", "icon": "gemini"}
    normalized_model = model_id.strip().lower()
    for pattern, provider, icon in _MODEL_PROVIDER_HINTS:
        if re.search(pattern, normalized_model):
            return {"provider": provider, "icon": icon}
    return {"provider": "openai-compatible", "icon": "generic"}


class CustomModelService:
    def __init__(self, store: AppStore, vault: CredentialVault | None = None) -> None:
        self.store = store
        self.vault = vault or WindowsCredentialVault(store.root / "credentials" / "models")
        self._grants: dict[str, _Grant] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _selection_id(profile_id: str) -> str:
        return f"custom:{profile_id}"

    def catalog(self) -> list[dict[str, object]]:
        return [
            {
                "id": self._selection_id(str(profile["profile_id"])),
                "model": profile["model_id"],
                "label": profile["display_name"],
                "provider": profile["provider"],
                "icon": profile["icon"],
                "source": "custom",
                "profile_id": profile["profile_id"],
            }
            for profile in self.store.list_custom_models()
            if bool(profile["enabled"])
        ]

    def discover(self, *, base_url: str, api_key: str) -> dict[str, object]:
        base_url = validate_custom_base_url(base_url)
        detected = detect_provider(base_url, api_key)
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=30, max_retries=0)
        try:
            models = sorted(
                {item.id.removeprefix("models/") for item in client.models.list().data if item.id}
            )
        except APIStatusError as error:
            if error.status_code in {401, 403}:
                raise
            return {
                **detected,
                "base_url": base_url,
                "models": [],
                "warning": "MODEL_CATALOG_UNAVAILABLE_ENTER_ID_MANUALLY",
            }
        if detected["provider"] == "openai-compatible":
            for model_id in models:
                candidate = detect_provider(base_url, api_key, model_id)
                if candidate["provider"] != "openai-compatible":
                    detected = candidate
                    break
        return {**detected, "base_url": base_url, "models": models[:500]}

    def create(
        self,
        *,
        display_name: str,
        base_url: str,
        model_id: str,
        api_key: str,
        api_style: ApiStyle,
        provider: str | None = None,
    ) -> dict[str, object]:
        base_url = validate_custom_base_url(base_url)
        detected = detect_provider(base_url, api_key, model_id)
        selected_provider = (provider or detected["provider"]).strip().lower()
        profile_id = f"cmp-{uuid4().hex[:24]}"
        profile = self.store.save_custom_model(
            {
                "profile_id": profile_id,
                "display_name": display_name,
                "provider": selected_provider,
                "icon": _PROVIDER_ICON_BY_NAME.get(selected_provider, detected["icon"]),
                "base_url": base_url,
                "api_style": api_style,
                "model_id": model_id,
                "enabled": True,
            }
        )
        try:
            self.vault.put(profile_id, api_key)
        except BaseException:
            self.store.delete_custom_model(profile_id)
            raise
        return {**profile, "selection_id": self._selection_id(profile_id), "has_api_key": True}

    def delete(self, profile_id: str) -> None:
        self.store.delete_custom_model(profile_id)
        self.vault.delete(profile_id)

    def test(self, profile_id: str) -> dict[str, object]:
        profile = self.store.get_custom_model(profile_id)
        result = self.discover(
            base_url=str(profile["base_url"]), api_key=self.vault.get(profile_id)
        )
        return {
            "ok": str(profile["model_id"]) in result["models"],
            "provider": result["provider"],
            "model_id": profile["model_id"],
            "model_count": len(result["models"]),
        }

    def issue_grant(self, profile_id: str, thread_id: str) -> dict[str, object]:
        profile = self.store.get_custom_model(profile_id)
        if not bool(profile["enabled"]):
            raise ValueError("CUSTOM_MODEL_DISABLED")
        grant = f"ddc_{secrets.token_urlsafe(32)}"
        expires_at = datetime.now(UTC) + timedelta(minutes=10)
        connection = ModelConnection(
            selection_id=self._selection_id(profile_id),
            provider="custom",
            model_id=str(profile["model_id"]),
            api_key=self.vault.get(profile_id),
            base_url=str(profile["base_url"]),
            api_style=str(profile["api_style"]),  # type: ignore[arg-type]
            capability_id="model.custom.openai-compatible",
            source="custom",
        )
        with self._lock:
            self._grants[grant] = _Grant(connection, thread_id, expires_at)
        return {"grant": grant, "expires_at": expires_at.isoformat()}

    def consume_grant(self, grant: str, thread_id: str, selection_id: str) -> ModelConnection:
        with self._lock:
            record = self._grants.pop(grant, None)
        if record is None:
            raise ValueError("CUSTOM_MODEL_GRANT_INVALID")
        if record.expires_at <= datetime.now(UTC):
            raise ValueError("CUSTOM_MODEL_GRANT_EXPIRED")
        if record.thread_id != thread_id or record.connection.selection_id != selection_id:
            raise ValueError("CUSTOM_MODEL_GRANT_SCOPE_MISMATCH")
        return record.connection
