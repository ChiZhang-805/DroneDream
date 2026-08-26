from __future__ import annotations

from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _ingest(expected: str, *, request: Any, **_: Any) -> dict[str, object]:
    if request.input_channel != expected:
        return {"accepted": False, "channel": expected}
    metadata = dict(request.input_metadata)
    if expected == "voice":
        has_voice_media = any(
            attachment.decoded_kind in {"audio", "text"} for attachment in request.attachments
        )
        has_transcript = metadata.get("transcript_source") in {
            "web-speech",
            "audio-attachment",
        } and bool(request.message.strip())
        if not has_voice_media and not has_transcript:
            return {"accepted": False, "channel": expected, "issue": "VOICE_MEDIA_REQUIRED"}
    if expected == "camera" and not any(
        attachment.decoded_kind == "image" for attachment in request.attachments
    ):
        return {"accepted": False, "channel": expected, "issue": "CAMERA_IMAGE_REQUIRED"}
    if expected == "webhook" and metadata.get("signature_verified") is not True:
        return {"accepted": False, "channel": expected, "issue": "WEBHOOK_SIGNATURE_REQUIRED"}
    if expected == "scheduled" and not isinstance(metadata.get("schedule_id"), str):
        return {"accepted": False, "channel": expected, "issue": "SCHEDULE_ID_REQUIRED"}
    return {
        "accepted": True,
        "channel": expected,
        "message": request.message,
        "metadata_keys": sorted(metadata),
    }


def plugin_definitions() -> list[PluginDefinition]:
    labels = {
        "text": "文字输入",
        "voice": "语音输入",
        "camera": "相机输入",
        "api": "API 输入",
        "webhook": "Webhook 输入",
        "scheduled": "定时任务输入",
    }
    definitions: list[PluginDefinition] = []
    for order, (channel, label) in enumerate(labels.items(), start=1):

        def handler(*, request: Any, _channel: str = channel, **kwargs: Any) -> dict[str, object]:
            return _ingest(_channel, request=request, **kwargs)

        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=f"input.channel-{channel}",
                name=label,
                description=f"验证并接收 {label}，统一转为结构化任务请求。",
                capability_id=f"input.channel-{channel}.ingest",
                capability_kind="input-channel",
                capability_name=label,
                capability_description=f"{label}入口。",
                category_id="input",
                category_label="输入与理解",
                slot_id="input.channels",
                slot_label="输入通道",
                activation_mode="multiple",
                category_order=10,
                slot_order=10,
                plugin_order=order * 10,
                hooks={"ingest_input": handler},
                default_enabled=True,
                failure_mode="isolate",
            )
        )
    return definitions
