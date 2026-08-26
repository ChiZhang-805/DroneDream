from __future__ import annotations

from dronedream_agent_core.plugin_api import PluginDefinition
from dronedream_agent_core.plugin_contracts import (
    PluginCapability,
    PluginManifest,
    PluginPlacement,
    PluginRuntime,
)


def plugin_definition() -> PluginDefinition:
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="voice.web-speech",
            name="系统实时语音",
            version="1.0.0",
            description="使用系统 WebView 的连续语音识别，把实时转写追加到任务输入框。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python", entrypoint=f"{__name__}:plugin_definition"
            ),
            capabilities=[
                PluginCapability(
                    capability_id="voice.web-speech.transcribe",
                    kind="voice",
                    name="实时语音输入",
                    description="连续采集并转写中文语音。",
                    metadata={"engine": "web-speech", "continuous": True},
                )
            ],
            permissions=[],
            default_enabled=True,
            removable=False,
            placement=PluginPlacement(
                category_id="interaction",
                category_label="交互与界面",
                slot_id="interaction.voice-input",
                slot_label="语音输入",
                activation_mode="single",
                scope="interface",
                category_order=80,
                slot_order=10,
                plugin_order=10,
            ),
        )
    )
