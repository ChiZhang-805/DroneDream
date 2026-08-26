from __future__ import annotations

from dronedream_agent_core.plugin_api import PluginDefinition
from dronedream_agent_core.plugin_contracts import (
    PluginCapability,
    PluginManifest,
    PluginPlacement,
    PluginRuntime,
)


def plugin_definition() -> PluginDefinition:
    models = [
        {"id": "kimi-k2.6", "label": "Kimi K2.6", "provider": "kimi"},
        {"id": "kimi-k3", "label": "Kimi K3", "provider": "kimi"},
    ]
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="model.kimi",
            name="Kimi 模型",
            version="1.0.0",
            description="通过 DroneDream 托管网关提供结构化 Kimi 模型调用。",
            publisher="DroneDream",
            runtime=PluginRuntime(kind="model-provider"),
            capabilities=[
                PluginCapability(
                    capability_id="model.kimi.structured",
                    kind="model-provider",
                    name="Kimi 结构化模型",
                    description="提供意图、计划、检查点与完成验收模型角色。",
                    metadata={"provider": "kimi", "models": models},
                )
            ],
            permissions=["network.model-gateway"],
            default_enabled=True,
            placement=PluginPlacement(
                category_id="models",
                category_label="模型与推理",
                slot_id="models.providers",
                slot_label="模型供应商",
                activation_mode="multiple",
                scope="general",
                category_order=50,
                slot_order=10,
                plugin_order=30,
            ),
        )
    )
