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
            plugin_id="model.custom.openai-compatible",
            name="自定义模型连接器",
            version="1.0.0",
            description="为用户自带凭证的 OpenAI 兼容模型提供可插拔运行边界。",
            publisher="DroneDream",
            runtime=PluginRuntime(kind="model-provider"),
            capabilities=[
                PluginCapability(
                    capability_id="model.custom.openai-compatible",
                    kind="model-provider",
                    name="自定义 OpenAI 兼容模型",
                    description="使用本机加密凭证连接用户选择的兼容模型服务。",
                    metadata={"provider": "custom", "models": []},
                )
            ],
            permissions=["network.model-gateway"],
            default_enabled=True,
            removable=False,
            placement=PluginPlacement(
                category_id="models",
                category_label="模型与推理",
                slot_id="models.providers",
                slot_label="模型供应商",
                activation_mode="multiple",
                scope="general",
                category_order=50,
                slot_order=10,
                plugin_order=40,
            ),
        )
    )
