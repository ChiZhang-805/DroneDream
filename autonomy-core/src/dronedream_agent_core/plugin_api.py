"""Runtime-neutral plugin definitions discovered without core tool-name coupling."""

from __future__ import annotations

import hashlib
import importlib
import os
import pkgutil
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

import jsonschema
from pydantic import BaseModel

from .capability_broker import CapabilityBrokerHostServices
from .contracts import MapAsset
from .extensions import ExtensionPlugin, ExtensionRegistry
from .hashing import sha256_json
from .plugin_contracts import (
    PLUGIN_EXTENSION_HOOKS,
    PLUGIN_MCP_CAPABILITY_KINDS,
    PluginCapability,
    PluginManifest,
    PluginSnapshot,
    PluginSnapshotEntry,
)
from .plugin_process import McpStdioClient, PluginProcessError, resolve_plugin_command
from .tools import ToolPlugin, ToolRegistry

if TYPE_CHECKING:
    from .capability_broker import CoreCapabilityBroker, ScopedCapabilityBroker


@dataclass(frozen=True)
class ToolEnvironment:
    map_graph: MapAsset
    semantic_path: Path
    vehicle_diameter_m: float
    vehicle_height_m: float
    waypoint_hold_seconds: float
    plugin_configuration: dict[str, object] | None = None
    capability_broker: ScopedCapabilityBroker | None = None
    broker_factory: CoreCapabilityBroker | None = None


ToolFactory = Callable[[ToolEnvironment], list[ToolPlugin]]


@dataclass(frozen=True)
class PluginDefinition:
    manifest: PluginManifest
    tool_factory: ToolFactory | None = None
    hooks: dict[str, Callable[..., Any]] | None = None


class PluginDefinitionProvider(Protocol):
    def __call__(self) -> PluginDefinition: ...


def _jsonable_mcp_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable_mcp_value(value.model_dump(mode="json"))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable_mcp_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable_mcp_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ValueError(f"PLUGIN_EXTENSION_INPUT_NOT_JSON:{type(value).__name__}")


def _snapshot_bundle_path(value: str) -> Path:
    """Resolve a Windows-installed bundle when the runtime bridge executes in WSL."""

    if os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", value):
        windows_path = PureWindowsPath(value)
        drive = windows_path.drive[0].lower()
        return Path("/mnt") / drive / Path(*windows_path.parts[1:])
    return Path(value)


def _verified_external_manifest(entry: PluginSnapshotEntry) -> tuple[PluginManifest, Path]:
    manifest = entry.manifest
    if manifest is None or entry.bundle_root is None:
        raise ValueError(f"PLUGIN_SNAPSHOT_EXTERNAL_METADATA_MISSING:{entry.plugin_id}")
    if (
        manifest.plugin_id != entry.plugin_id
        or manifest.version != entry.version
        or sha256_json(manifest) != entry.manifest_sha256
        or [item.capability_id for item in manifest.capabilities] != entry.capability_ids
    ):
        raise ValueError(f"PLUGIN_SNAPSHOT_DRIFT:{entry.plugin_id}")
    if manifest.runtime.kind != "mcp-stdio":
        raise ValueError(f"PLUGIN_RUNTIME_NOT_REBUILDABLE:{entry.plugin_id}")
    root = _snapshot_bundle_path(entry.bundle_root).resolve()
    if not root.is_dir():
        raise ValueError(f"PLUGIN_SNAPSHOT_BUNDLE_MISSING:{entry.plugin_id}")
    resolve_plugin_command(root, manifest.runtime.command)
    files = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and path.name != "plugin.json"
    }
    if set(files) != set(manifest.file_sha256):
        raise ValueError(f"PLUGIN_SNAPSHOT_FILE_MANIFEST_DRIFT:{entry.plugin_id}")
    for relative, path in files.items():
        if root not in path.resolve().parents:
            raise ValueError(f"PLUGIN_SNAPSHOT_FILE_ESCAPE:{entry.plugin_id}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != manifest.file_sha256[relative]:
            raise ValueError(f"PLUGIN_SNAPSHOT_FILE_HASH_DRIFT:{entry.plugin_id}:{relative}")
    return manifest, root


def _call_external_mcp(
    *,
    root: Path,
    manifest: PluginManifest,
    entry: PluginSnapshotEntry,
    capability: PluginCapability,
    arguments: dict[str, Any],
    broker_factory: CoreCapabilityBroker | None = None,
) -> dict[str, Any]:
    verified_manifest, verified_root = _verified_external_manifest(entry)
    if verified_manifest != manifest or verified_root != root:
        raise PluginProcessError(f"PLUGIN_SNAPSHOT_DRIFT:{entry.plugin_id}")
    if capability.input_schema:
        jsonschema.validate(arguments, capability.input_schema)
    runtime = manifest.runtime
    permissions = list(
        capability.required_permissions
        if capability.required_permissions is not None
        else manifest.permissions
    )
    host_services = None
    if broker_factory is not None:
        scoped_manifest = manifest.model_copy(update={"permissions": permissions})
        host_services = CapabilityBrokerHostServices(broker_factory.scope(scoped_manifest))
    with McpStdioClient(
        plugin_root=root,
        command=runtime.command,
        protocol_version=runtime.protocol_version,
        startup_timeout_seconds=runtime.startup_timeout_seconds,
        call_timeout_seconds=runtime.call_timeout_seconds,
        configuration=dict(entry.configuration),
        permissions=permissions,
        resource_policy=manifest.resource_policy,
        host_services=host_services,
    ) as client:
        output = client.call_tool(capability.capability_id, arguments)
    if capability.output_schema:
        jsonschema.validate(output, capability.output_schema)
    return output


def load_object(reference: str) -> object:
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("PLUGIN_ENTRYPOINT_INVALID")
    module = importlib.import_module(module_name)
    return getattr(module, attribute)


def discover_builtin_plugins() -> dict[str, PluginDefinition]:
    """Discover first-party definitions by package scan, including frozen executables."""

    package = importlib.import_module("dronedream_agent_plugins")
    definitions: dict[str, PluginDefinition] = {}
    for module_info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        module = importlib.import_module(module_info.name)
        provider = getattr(module, "plugin_definition", None)
        providers = getattr(module, "plugin_definitions", None)
        if provider is None and providers is None:
            continue
        discovered = [provider()] if provider is not None else list(providers())
        for definition in discovered:
            if not isinstance(definition, PluginDefinition):
                raise TypeError(f"invalid plugin definition from {module_info.name}")
            plugin_id = definition.manifest.plugin_id
            if plugin_id in definitions:
                raise ValueError(f"duplicate discovered plugin id: {plugin_id}")
            definitions[plugin_id] = definition
    return definitions


def build_discovered_tool_registry(
    environment: ToolEnvironment,
) -> tuple[ToolRegistry, PluginSnapshot]:
    """Build the standalone CLI catalog from discoverable first-party modules."""

    registry = ToolRegistry(allowed_authorities={"read", "plan", "simulate"})
    entries: list[PluginSnapshotEntry] = []
    for plugin_id, definition in sorted(discover_builtin_plugins().items()):
        manifest = definition.manifest
        if not manifest.default_enabled:
            continue
        package_sha256 = sha256_json(manifest)
        entries.append(
            PluginSnapshotEntry(
                plugin_id=plugin_id,
                version=manifest.version,
                package_sha256=package_sha256,
                manifest_sha256=package_sha256,
                configuration_sha256=sha256_json({}),
                configuration={},
                capability_ids=[item.capability_id for item in manifest.capabilities],
                manifest=manifest,
            )
        )
        if definition.tool_factory is None:
            continue
        for tool in definition.tool_factory(environment):
            registry.register(
                replace(
                    tool,
                    plugin_id=plugin_id,
                    plugin_package_sha256=package_sha256,
                    slot_id=manifest.placement.slot_id,
                )
            )
    snapshot = PluginSnapshot(
        snapshot_id=f"plugin-snapshot-{uuid4().hex[:24]}",
        catalog_sha256=sha256_json([item.model_dump(mode="json") for item in entries]),
        plugins=entries,
        created_at=datetime.now(UTC),
    )
    return registry, snapshot


def build_snapshot_tool_registry(
    environment: ToolEnvironment, snapshot: PluginSnapshot
) -> ToolRegistry:
    """Rebuild first-party deterministic tools from an exact prepared snapshot."""

    registry = ToolRegistry(allowed_authorities={"read", "plan", "simulate"})
    definitions = discover_builtin_plugins()
    for entry in snapshot.plugins:
        definition = definitions.get(entry.plugin_id)
        if definition is None:
            manifest, root = _verified_external_manifest(entry)
            for capability in manifest.capabilities:
                if (
                    capability.kind not in PLUGIN_MCP_CAPABILITY_KINDS
                    or "extension_hook" in capability.metadata
                ):
                    continue

                def call_external(
                    value: dict[str, object],
                    *,
                    _root: Path = root,
                    _manifest: PluginManifest = manifest,
                    _entry: PluginSnapshotEntry = entry,
                    _capability: PluginCapability = capability,
                ) -> dict[str, Any]:
                    return _call_external_mcp(
                        root=_root,
                        manifest=_manifest,
                        entry=_entry,
                        capability=_capability,
                        arguments=_jsonable_mcp_value(value),
                    )

                registry.register(
                    ToolPlugin(
                        tool_id=capability.capability_id,
                        version=manifest.version,
                        authority=capability.authority,  # type: ignore[arg-type]
                        input_type=None,
                        output_type=None,
                        input_schema=capability.input_schema,
                        output_schema=capability.output_schema,
                        handler=call_external,
                        plugin_id=entry.plugin_id,
                        plugin_package_sha256=entry.package_sha256,
                        routing_metadata=capability.metadata,
                        slot_id=manifest.placement.slot_id,
                    )
                )
            continue
        if definition.tool_factory is None:
            continue
        manifest = definition.manifest
        manifest_sha256 = sha256_json(manifest)
        if (
            manifest.version != entry.version
            or manifest_sha256 != entry.manifest_sha256
            or manifest_sha256 != entry.package_sha256
        ):
            raise ValueError(f"PLUGIN_SNAPSHOT_DRIFT:{entry.plugin_id}")
        for tool in definition.tool_factory(environment):
            registry.register(
                replace(
                    tool,
                    plugin_id=entry.plugin_id,
                    plugin_package_sha256=entry.package_sha256,
                    slot_id=manifest.placement.slot_id,
                )
            )
    registry.configure_extensions(build_discovered_extension_registry(snapshot))
    return registry


def build_discovered_extension_registry(
    snapshot: PluginSnapshot | None = None,
    *,
    broker_factory: CoreCapabilityBroker | None = None,
) -> ExtensionRegistry:
    """Build the non-tool Harness registry, optionally bound to a prepared snapshot."""

    definitions = discover_builtin_plugins()
    selected = None if snapshot is None else {item.plugin_id: item for item in snapshot.plugins}
    registry = ExtensionRegistry()
    for plugin_id, definition in sorted(definitions.items()):
        if not definition.hooks:
            continue
        manifest = definition.manifest
        if selected is None and not manifest.default_enabled:
            continue
        package_sha256 = sha256_json(manifest)
        entry = selected.get(plugin_id) if selected is not None else None
        if selected is not None and entry is None:
            continue
        if entry is not None and (
            entry.version != manifest.version
            or entry.manifest_sha256 != package_sha256
            or entry.package_sha256 != package_sha256
        ):
            raise ValueError(f"PLUGIN_SNAPSHOT_DRIFT:{plugin_id}")
        capability = manifest.capabilities[0]
        placement = manifest.placement
        hooks: dict[str, Callable[..., Any]] = {}
        for hook_name, handler in definition.hooks.items():

            def call_hook(
                *,
                _handler: Callable[..., Any] = handler,
                _configuration: dict[str, Any] = dict(entry.configuration) if entry else {},
                **kwargs: Any,
            ) -> Any:
                kwargs.setdefault("configuration", _configuration)
                return _handler(**kwargs)

            hooks[hook_name] = call_hook
        registry.register(
            ExtensionPlugin(
                plugin_id=plugin_id,
                version=manifest.version,
                package_sha256=package_sha256,
                capability_id=capability.capability_id,
                slot_id=placement.slot_id,
                activation_mode=placement.activation_mode,
                failure_mode=placement.failure_mode,
                swap_policy=placement.swap_policy,
                pipeline_order=placement.pipeline_order,
                runs_after=tuple(placement.runs_after),
                runs_before=tuple(placement.runs_before),
                hooks=hooks,
            )
        )
    if snapshot is not None:
        for entry in snapshot.plugins:
            if entry.plugin_id in definitions:
                continue
            manifest, root = _verified_external_manifest(entry)
            capabilities = [
                item
                for item in manifest.capabilities
                if item.metadata.get("extension_hook") in PLUGIN_EXTENSION_HOOKS
            ]
            if not capabilities:
                continue
            placement = manifest.placement
            for capability in capabilities:
                hook_name = str(capability.metadata["extension_hook"])

                def call_external_extension(
                    *,
                    _root: Path = root,
                    _manifest: PluginManifest = manifest,
                    _entry: PluginSnapshotEntry = entry,
                    _capability: PluginCapability = capability,
                    **kwargs: Any,
                ) -> Any:
                    output = _call_external_mcp(
                        root=_root,
                        manifest=_manifest,
                        entry=_entry,
                        capability=_capability,
                        arguments=_jsonable_mcp_value(kwargs),
                        broker_factory=broker_factory,
                    )
                    if _manifest.placement.activation_mode == "pipeline":
                        if "value" not in output:
                            raise PluginProcessError("PLUGIN_EXTENSION_PIPELINE_VALUE_MISSING")
                        return output["value"]
                    return output

                registry.register(
                    ExtensionPlugin(
                        plugin_id=entry.plugin_id,
                        version=entry.version,
                        package_sha256=entry.package_sha256,
                        capability_id=capability.capability_id,
                        slot_id=placement.slot_id,
                        activation_mode=placement.activation_mode,
                        failure_mode=placement.failure_mode,
                        swap_policy=placement.swap_policy,
                        pipeline_order=placement.pipeline_order,
                        runs_after=tuple(placement.runs_after),
                        runs_before=tuple(placement.runs_before),
                        hooks={hook_name: call_external_extension},
                    )
                )
    return registry
