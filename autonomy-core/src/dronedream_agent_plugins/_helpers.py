from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition
from dronedream_agent_core.plugin_contracts import (
    PluginCapability,
    PluginManifest,
    PluginPlacement,
    PluginRuntime,
)


def hook_plugin(
    *,
    module_name: str,
    plugin_id: str,
    name: str,
    description: str,
    capability_id: str,
    capability_kind: str,
    capability_name: str,
    capability_description: str,
    category_id: str,
    category_label: str,
    slot_id: str,
    slot_label: str,
    activation_mode: str,
    category_order: int,
    slot_order: int,
    plugin_order: int,
    hooks: dict[str, Callable[..., Any]],
    default_enabled: bool = False,
    failure_mode: str = "isolate",
    swap_policy: str = "next-mission",
    pipeline_order: int = 500,
    runs_after: list[str] | None = None,
    runs_before: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    configuration_schema: dict[str, Any] | None = None,
    permissions: list[str] | None = None,
) -> PluginDefinition:
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id=plugin_id,
            name=name,
            version="1.0.0",
            description=description,
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python", entrypoint=f"{module_name}:plugin_definitions"
            ),
            capabilities=[
                PluginCapability(
                    capability_id=capability_id,
                    kind=capability_kind,  # type: ignore[arg-type]
                    name=capability_name,
                    description=capability_description,
                    authority="plan",
                    input_schema={"type": "object", "additionalProperties": True},
                    output_schema={"type": "object", "additionalProperties": True},
                    metadata=metadata or {},
                )
            ],
            permissions=permissions or ["mission.read"],  # type: ignore[arg-type]
            default_enabled=default_enabled,
            removable=False,
            placement=PluginPlacement(
                category_id=category_id,
                category_label=category_label,
                slot_id=slot_id,
                slot_label=slot_label,
                activation_mode=activation_mode,  # type: ignore[arg-type]
                scope="mission",
                failure_mode=failure_mode,  # type: ignore[arg-type]
                swap_policy=swap_policy,  # type: ignore[arg-type]
                category_order=category_order,
                slot_order=slot_order,
                plugin_order=plugin_order,
                pipeline_order=pipeline_order,
                runs_after=runs_after or [],
                runs_before=runs_before or [],
            ),
            configuration_schema=configuration_schema or {},
        ),
        hooks=hooks,
    )
