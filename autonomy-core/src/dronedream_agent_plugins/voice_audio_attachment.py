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
            plugin_id="voice.audio-attachment",
            name="音频文件输入",
            version="1.0.0",
            description="关闭实时麦克风采集，通过任务附件提交已有音频文件。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python", entrypoint=f"{__name__}:plugin_definition"
            ),
            capabilities=[
                PluginCapability(
                    capability_id="voice.audio-attachment.select",
                    kind="voice",
                    name="音频附件输入",
                    description="使用文件选择器添加已有录音。",
                    metadata={"engine": "audio-attachment"},
                )
            ],
            permissions=[],
            default_enabled=False,
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
                plugin_order=20,
            ),
        )
    )
