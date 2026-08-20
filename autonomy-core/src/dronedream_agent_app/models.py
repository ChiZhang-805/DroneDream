"""Strict HTTP contracts for the local desktop application."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class AppModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ThreadCreate(AppModel):
    title: str = Field(default="新任务", min_length=1, max_length=120)
    selected_model: str = Field(default="gpt-5.4", min_length=1, max_length=80)


class ThreadPatch(AppModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    selected_model: str | None = Field(default=None, min_length=1, max_length=80)
    selected_map_id: str | None = Field(default=None, max_length=120)
    selected_vehicle_id: str | None = Field(default=None, max_length=120)
    pinned: bool | None = None
    archived: bool | None = None


class MessageCreate(AppModel):
    content: str = Field(min_length=1, max_length=4_000)
    role: Literal["user", "assistant", "system"] = "user"
    kind: Literal["text", "status", "plan", "error"] = "text"
    metadata: dict[str, object] = Field(default_factory=dict)


class ModelRoleConnectionRequest(AppModel):
    role_port: Literal["critic", "safety", "perception", "local"]
    model_id: str = Field(min_length=1, max_length=80)
    model_grant: str = Field(pattern=r"^dd[gc]_[A-Za-z0-9_-]{20,124}$")
    gateway_base_url: HttpUrl | None = None


class MissionPrepareRequest(AppModel):
    message: str = Field(min_length=3, max_length=4_000)
    map_id: str = Field(min_length=1, max_length=120)
    vehicle_id: str = Field(min_length=1, max_length=120)
    model_id: str = Field(min_length=1, max_length=80)
    model_grant: str = Field(pattern=r"^dd[gc]_[A-Za-z0-9_-]{20,124}$")
    gateway_base_url: HttpUrl | None = None
    locale: Literal["zh-CN", "en-US"] = "zh-CN"
    start_entity: str = Field(default="office launch pad", min_length=1, max_length=160)
    attachment_ids: list[str] = Field(default_factory=list, max_length=12)
    role_models: list[ModelRoleConnectionRequest] = Field(default_factory=list, max_length=4)
    input_channel: Literal["text", "voice", "camera", "api", "webhook", "scheduled"] = "text"
    input_metadata: dict[str, object] = Field(default_factory=dict)


class MissionExecuteRequest(AppModel):
    model_id: str = Field(min_length=1, max_length=80)
    model_grant: str = Field(pattern=r"^dd[gc]_[A-Za-z0-9_-]{20,124}$")
    gateway_base_url: HttpUrl | None = None


class CustomModelDiscoverRequest(AppModel):
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str = Field(min_length=8, max_length=8_192)


class CustomModelCreateRequest(CustomModelDiscoverRequest):
    display_name: str = Field(min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=160)
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    api_style: Literal["responses", "chat-completions"] = "chat-completions"


class SettingsPatch(AppModel):
    locale: Literal["zh-CN", "en-US"] | None = None
    theme: Literal["system", "light", "dark"] | None = None
    update_channel: Literal["stable", "preview"] | None = None
    default_model_id: str | None = Field(default=None, min_length=1, max_length=160)
    memory_enabled: bool | None = None
    remember_task_preferences: bool | None = None
    remember_asset_choices: bool | None = None
    plugin_update_ring: Literal["stable", "preview", "canary", "pinned"] | None = None


class RuntimeMessageRequest(AppModel):
    text: str = Field(min_length=1, max_length=1_000)


class OperatorTakeoverGrantRequest(AppModel):
    message_id: str = Field(pattern=r"^runtime-msg-[0-9a-f]{32}$")
    operator_id: str = Field(min_length=1, max_length=160)
    duration_seconds: int = Field(default=300, ge=10, le=600)


class OperatorControlRequest(AppModel):
    message_id: str = Field(pattern=r"^runtime-msg-[0-9a-f]{32}$")
    grant_token: str = Field(min_length=32, max_length=256)
    action: Literal["velocity", "release"] = "velocity"
    north_mps: float = Field(default=0.0, ge=-3.0, le=3.0)
    east_mps: float = Field(default=0.0, ge=-3.0, le=3.0)
    down_mps: float = Field(default=0.0, ge=-2.0, le=2.0)
    yaw_rate_dps: float = Field(default=0.0, ge=-180.0, le=180.0)
    duration_seconds: float = Field(default=0.25, gt=0.0, le=0.5)


class PluginConfigurationRequest(AppModel):
    configuration: dict[str, object] = Field(default_factory=dict)


class ConnectorCredentialCreateRequest(AppModel):
    display_name: str = Field(min_length=1, max_length=80)
    secret: str = Field(min_length=1, max_length=16_384)
    allowed_plugin_ids: list[str] = Field(min_length=1, max_length=32)


class PluginRollbackRequest(AppModel):
    version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


class TrustedPublisherRequest(AppModel):
    key_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    publisher: str = Field(min_length=1, max_length=120)
    public_key_base64: str = Field(min_length=40, max_length=80)


class PluginMarketplaceInstallRequest(AppModel):
    source_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    plugin_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
