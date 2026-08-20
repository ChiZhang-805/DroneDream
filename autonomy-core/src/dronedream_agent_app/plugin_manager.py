"""Transactional, reversible plugin management for the desktop application."""

from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import stat
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import jsonschema
from pydantic import BaseModel, ValidationError

from dronedream_agent_core.capability_broker import (
    CapabilityBrokerHostServices,
    CoreCapabilityBroker,
)
from dronedream_agent_core.extensions import ExtensionPlugin, ExtensionRegistry
from dronedream_agent_core.hashing import canonical_json, sha256_json
from dronedream_agent_core.plugin_api import (
    PluginDefinition,
    ToolEnvironment,
    discover_builtin_plugins,
)
from dronedream_agent_core.plugin_contracts import (
    PLUGIN_EXTENSION_HOOKS,
    PLUGIN_MCP_CAPABILITY_KINDS,
    PluginCapability,
    PluginGovernanceOperation,
    PluginGovernancePolicy,
    PluginLifecycleReceipt,
    PluginManifest,
    PluginSnapshot,
    PluginSnapshotEntry,
    PluginUsageEvent,
)
from dronedream_agent_core.plugin_governance import evaluate_plugin_governance
from dronedream_agent_core.plugin_panels import materialize_panel, validate_panel_document
from dronedream_agent_core.plugin_process import (
    McpSessionPool,
    McpStdioClient,
    PluginProcessError,
    resolve_plugin_command,
)
from dronedream_agent_core.plugin_trust import PluginTrustStore, TrustStoreError
from dronedream_agent_core.tools import ToolPlugin, ToolRegistry

from .storage import AppStore


class PluginManagerError(RuntimeError):
    """A plugin lifecycle transition was rejected without weakening the core."""


def _version_tuple(value: str) -> tuple[int, int, int]:
    core = value.split("-", 1)[0].split("+", 1)[0]
    major, minor, patch = core.split(".")
    return int(major), int(minor), int(patch)


def _version_matches(version: str, requirement: str) -> bool:
    if requirement == "*":
        return True
    actual = _version_tuple(version)
    if requirement.startswith(">="):
        return actual >= _version_tuple(requirement[2:])
    if requirement.startswith("^"):
        minimum = _version_tuple(requirement[1:])
        return actual >= minimum and actual[0] == minimum[0]
    return actual == _version_tuple(requirement)


def _mcp_json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _mcp_json_value(value.model_dump(mode="json"))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _mcp_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_mcp_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise PluginManagerError(f"PLUGIN_EXTENSION_INPUT_NOT_JSON:{type(value).__name__}")


class PluginManager:
    required_tool_slots = frozenset(
        {
            "planning.route-strategy",
            "planning.alternative-ranker",
            "safety.route-clearance",
            "flight-control.track-export",
            "runtime.track-export",
        }
    )
    required_single_slots = frozenset(
        {
            *required_tool_slots,
            "safety.interruption-policy",
            "simulation.runtime-adapter",
            "simulation.simulator-descriptor",
            "simulation.clock-policy",
            "simulation.monte-carlo-policy",
            "runtime.track-export",
            "assets.map-importer",
            "assets.vehicle-importer",
            "planning.workflow-policy",
            "harness.profile",
            "harness.workflow-topology",
            "harness.scheduler",
            "harness.retry-policy",
            "harness.timeout-policy",
            "harness.budget-policy",
            "harness.fallback-policy",
            "harness.cache-policy",
            "harness.event-bus",
            "models.role-policy",
            "models.runtime-router",
            "models.consensus-policy",
            "context.compaction-strategy",
            "context.store",
            "context.retrieval-policy",
            "context.summarization-policy",
            "context.retention-policy",
            "tools.router-policy",
            "tools.execution-policy",
            "runtime.checkpoint-policy",
            "runtime.replan-policy",
            "runtime.amendment-classifier",
            "runtime.amendment-policy",
            "native.transport",
            "native.state-estimator",
            "native.localization",
            "native.controller",
            "native.watchdog",
        }
    )
    protected_slots = frozenset(
        {
            *required_tool_slots,
            "safety.interruption-policy",
            "simulation.runtime-adapter",
        }
    )

    def __init__(
        self,
        store: AppStore,
        *,
        app_version: str = "0.1.0",
        official_plugins_root: Path | None = None,
        plugin_isolator_path: Path | None = None,
    ) -> None:
        self.store = store
        self.app_version = app_version
        self._definitions = discover_builtin_plugins()
        self._plugin_isolator_path = plugin_isolator_path
        self._disable_guard: Callable[[str, str], list[str]] | None = None
        self._mutation_lock = threading.RLock()
        self._call_condition = threading.Condition()
        self._inflight_calls: dict[str, int] = {}
        self._official_packages: dict[tuple[str, str], str] = {}
        self.trust_store = PluginTrustStore(store.root / "trust" / "plugin-publishers.json")
        self._mcp_sessions = McpSessionPool(on_unhealthy=self._quarantine_unhealthy_session)
        self.seed_builtin_plugins()
        if official_plugins_root is not None:
            self.seed_official_plugins(official_plugins_root)

    def set_disable_guard(self, guard: Callable[[str, str], list[str]]) -> None:
        self._disable_guard = guard

    def close(self) -> None:
        self._mcp_sessions.close()

    def _quarantine_unhealthy_session(self, plugin_id: str, issue_code: str) -> None:
        try:
            plugin = self.store.get_plugin(plugin_id)
            if not bool(plugin["enabled"]) or plugin["status"] != "healthy":
                return
            failed = self.store.set_plugin_lifecycle(
                plugin_id,
                enabled=False,
                status="quarantined",
                health="failed",
                last_error=issue_code[:800],
            )
            self._receipt(
                plugin=failed,
                operation="quarantine",
                previous_state="healthy",
                current_state="quarantined",
                accepted=True,
                issue_codes=[issue_code[:96]],
            )
        except (KeyError, RuntimeError, ValueError):
            return

    def _mcp_client(
        self,
        plugin: dict[str, object],
        manifest: PluginManifest,
        *,
        configuration: dict[str, Any] | None = None,
        capability: PluginCapability | None = None,
        broker_factory: CoreCapabilityBroker | None = None,
    ) -> McpStdioClient:
        runtime = manifest.runtime
        permissions = list(
            capability.required_permissions
            if capability is not None and capability.required_permissions is not None
            else manifest.permissions
        )
        host_services = None
        host_scope_id = "none"
        if broker_factory is not None:
            scoped_manifest = manifest.model_copy(update={"permissions": permissions})
            host_services = CapabilityBrokerHostServices(broker_factory.scope(scoped_manifest))
            host_scope_id = (
                f"{id(broker_factory)}:{capability.capability_id if capability else '*'}"
            )
        return self._mcp_sessions.get(
            plugin_id=str(plugin["plugin_id"]),
            package_sha256=str(plugin["package_sha256"]),
            plugin_root=Path(str(plugin["bundle_root"])),
            command=runtime.command,
            protocol_version=runtime.protocol_version,
            startup_timeout_seconds=runtime.startup_timeout_seconds,
            call_timeout_seconds=runtime.call_timeout_seconds,
            configuration=configuration
            if configuration is not None
            else dict(
                self.store.get_plugin_configuration(str(plugin["plugin_id"]))["configuration"]
            ),
            permissions=permissions,
            resource_policy=manifest.resource_policy,
            host_scope_id=host_scope_id,
            host_services=host_services,
            require_os_isolation=not bool(plugin["builtin"]),
            isolator_path=self._plugin_isolator_path,
            client_factory=McpStdioClient,
        )

    def _acquire_call(self, plugin_id: str) -> None:
        with self._call_condition:
            plugin = self.store.get_plugin(plugin_id)
            if not bool(plugin["enabled"]) or plugin["status"] != "healthy":
                raise PluginManagerError("PLUGIN_NOT_ACCEPTING_CALLS")
            self._inflight_calls[plugin_id] = self._inflight_calls.get(plugin_id, 0) + 1

    def _acquire_snapshot_call(self, plugin_id: str) -> None:
        """Lease code already frozen into a task even if the next catalog has changed."""

        with self._call_condition:
            self._inflight_calls[plugin_id] = self._inflight_calls.get(plugin_id, 0) + 1

    def _release_call(self, plugin_id: str) -> None:
        with self._call_condition:
            remaining = self._inflight_calls.get(plugin_id, 1) - 1
            if remaining <= 0:
                self._inflight_calls.pop(plugin_id, None)
            else:
                self._inflight_calls[plugin_id] = remaining
            self._call_condition.notify_all()

    def _drain_calls(self, plugin_id: str, timeout_seconds: float = 20.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        with self._call_condition:
            while self._inflight_calls.get(plugin_id, 0):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PluginManagerError("PLUGIN_INFLIGHT_DRAIN_TIMEOUT")
                self._call_condition.wait(remaining)

    @staticmethod
    def _manifest_hash(manifest: PluginManifest) -> str:
        return sha256_json(manifest)

    def seed_builtin_plugins(self) -> None:
        for plugin_id, definition in sorted(self._definitions.items()):
            manifest = definition.manifest
            package_sha256 = self._manifest_hash(manifest)
            try:
                existing = self.store.get_plugin(plugin_id)
            except KeyError:
                enabled = manifest.default_enabled
            else:
                enabled = bool(existing["enabled"])
                if not manifest.disable_allowed:
                    enabled = True
            self.store.upsert_plugin(
                manifest=manifest,
                package_sha256=package_sha256,
                bundle_root=None,
                builtin=True,
                enabled=enabled,
                status="healthy" if enabled else "disabled",
                health="healthy" if enabled else "unknown",
                trust_status="verified",
                trust_decision={"status": "verified", "source": "builtin"},
            )

    def seed_official_plugins(self, root: Path) -> None:
        index_path = root / "index.json"
        if not index_path.is_file():
            raise PluginManagerError("OFFICIAL_PLUGIN_INDEX_MISSING")
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            if index.get("schema_version") != "dronedream.official-plugin-index.v1":
                raise PluginManagerError("OFFICIAL_PLUGIN_INDEX_INVALID")
            entries = index["plugins"]
            if not isinstance(entries, list):
                raise TypeError("plugins must be a list")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise TypeError("plugin entry must be an object")
                archive = (root / str(entry["file"])).resolve()
                if root.resolve() not in archive.parents or not archive.is_file():
                    raise PluginManagerError("OFFICIAL_PLUGIN_ARCHIVE_MISSING")
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                if digest != entry["sha256"]:
                    raise PluginManagerError("OFFICIAL_PLUGIN_ARCHIVE_HASH_MISMATCH")
                plugin_id = str(entry["plugin_id"])
                version = str(entry["version"])
                self._official_packages[(plugin_id, version)] = digest
                try:
                    installed = self.store.get_plugin_version(plugin_id, version)
                except KeyError:
                    installed = None
                if installed is not None:
                    if installed["package_sha256"] != digest:
                        raise PluginManagerError("OFFICIAL_PLUGIN_VERSION_DRIFT")
                else:
                    imported = self.import_bundle(archive)
                    imported_version = imported.get("staged_version", imported.get("version"))
                    if imported["plugin_id"] != plugin_id or imported_version != version:
                        raise PluginManagerError("OFFICIAL_PLUGIN_IDENTITY_MISMATCH")
                trust_decision = {
                    "schema_version": "dronedream.plugin-trust-decision.v1",
                    "status": "verified",
                    "source": "bundled-official-index",
                    "plugin_id": plugin_id,
                    "version": version,
                    "package_sha256": digest,
                    "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
                    "issue_codes": [],
                }
                self.store.set_plugin_version_trust(
                    plugin_id,
                    version=version,
                    trust_status="verified",
                    trust_decision=trust_decision,
                )
                current = self.store.get_plugin(plugin_id)
                if current["version"] != version and not bool(current["enabled"]):
                    self.activate_version(plugin_id, version, operation="activate")
                elif current["version"] == version:
                    self.store.set_plugin_trust(
                        plugin_id,
                        version=version,
                        trust_status="verified",
                        trust_decision=trust_decision,
                    )
        except (KeyError, OSError, TypeError, ValueError) as error:
            raise PluginManagerError("OFFICIAL_PLUGIN_INDEX_INVALID") from error

    def list_plugins(self) -> list[dict[str, object]]:
        values = self.store.list_plugins()
        for value in values:
            self._decorate(value)
        return values

    def _decorate(self, value: dict[str, object]) -> None:
        manifest = value.get("manifest")
        if not isinstance(manifest, dict):
            return
        parsed = PluginManifest.model_validate(manifest)
        value["capabilities"] = [item.model_dump(mode="json") for item in parsed.capabilities]
        value["permissions"] = list(parsed.permissions)
        value["dependencies"] = [item.model_dump(mode="json") for item in parsed.dependencies]
        placement = parsed.placement.model_dump(mode="json")
        value["placement"] = placement
        value["disable_allowed"] = parsed.disable_allowed
        value["slot_required"] = (
            isinstance(placement, dict) and placement.get("slot_id") in self.required_single_slots
        )

    def get_plugin(self, plugin_id: str) -> dict[str, object]:
        value = self.store.get_plugin(plugin_id)
        self._decorate(value)
        value["versions"] = self.store.list_plugin_versions(plugin_id)
        value["events"] = self.store.list_plugin_events(plugin_id)
        value["governance_decisions"] = self.store.list_plugin_governance_decisions(plugin_id)
        value["usage"] = self.store.list_plugin_usage(plugin_id)
        value["usage_summary"] = self.store.summarize_plugin_usage(plugin_id)
        value["configuration"] = self.store.get_plugin_configuration(plugin_id)["configuration"]
        return value

    def governance_policy(self) -> PluginGovernancePolicy:
        value = self.store.get_settings().get("plugin_governance", {})
        return PluginGovernancePolicy.model_validate(value)

    def set_governance_policy(self, policy: PluginGovernancePolicy) -> dict[str, object]:
        """Validate the whole installed catalog before committing a stricter ceiling."""

        for plugin in self.store.list_plugins():
            if bool(plugin["builtin"]):
                continue
            manifest = self._manifest(plugin)
            decision = evaluate_plugin_governance(
                policy=policy,
                manifest=manifest,
                operation="enable" if bool(plugin["enabled"]) else "import",
                trust_status=str(plugin["trust_status"]),
                installed_external_plugins=max(
                    0,
                    sum(not bool(item["builtin"]) for item in self.store.list_plugins()) - 1,
                ),
            )
            if not decision.accepted:
                raise PluginManagerError(
                    "PLUGIN_GOVERNANCE_CATALOG_REJECTED:"
                    + manifest.plugin_id
                    + ":"
                    + ",".join(decision.issue_codes)
                )
        return self.store.patch_settings({"plugin_governance": policy.model_dump(mode="json")})

    def _govern(
        self,
        *,
        manifest: PluginManifest,
        operation: PluginGovernanceOperation,
        trust_status: str,
    ) -> dict[str, object]:
        policy = self.governance_policy()
        external_count = sum(not bool(item["builtin"]) for item in self.store.list_plugins())
        decision = evaluate_plugin_governance(
            policy=policy,
            manifest=manifest,
            operation=operation,
            trust_status=trust_status,
            installed_external_plugins=external_count,
        )
        payload = decision.model_dump(mode="json")
        self.store.record_plugin_governance_decision(payload)
        if not decision.accepted:
            raise PluginManagerError("PLUGIN_GOVERNANCE_DENIED:" + ",".join(decision.issue_codes))
        return payload

    @staticmethod
    def _encoded_size(value: Any) -> int:
        try:
            return len(canonical_json(_mcp_json_value(value)).encode("utf-8"))
        except (PluginManagerError, TypeError, ValueError):
            return 0

    def _record_usage(
        self,
        *,
        plugin_id: str,
        plugin_version: str,
        capability_id: str,
        slot_id: str,
        invocation_kind: str,
        started: float,
        input_value: Any,
        output_value: Any = None,
        issue_code: str | None = None,
    ) -> None:
        event = PluginUsageEvent(
            invocation_id=f"plugin-call-{uuid4().hex[:24]}",
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            capability_id=capability_id,
            slot_id=slot_id,
            invocation_kind=invocation_kind,  # type: ignore[arg-type]
            outcome="error" if issue_code else "success",
            duration_ms=max(0.0, (time.perf_counter() - started) * 1_000),
            input_bytes=self._encoded_size(input_value),
            output_bytes=self._encoded_size(output_value),
            issue_code=issue_code[:160] if issue_code else None,
        )
        self.store.record_plugin_usage(event.model_dump(mode="json"))

    def invoke_single_slot(self, slot_id: str, hook: str, **kwargs: Any) -> Any:
        matches: list[tuple[dict[str, object], PluginDefinition]] = []
        for plugin in self.store.list_plugins():
            if not bool(plugin["enabled"]) or plugin["status"] != "healthy":
                continue
            manifest = self._manifest(plugin)
            if manifest.placement.slot_id != slot_id:
                continue
            definition = self._definitions.get(manifest.plugin_id)
            if definition is not None:
                matches.append((plugin, definition))
        if len(matches) != 1:
            raise PluginManagerError(f"PLUGIN_SLOT_RESOLUTION_FAILED:{slot_id}")
        plugin, definition = matches[0]
        handler = (definition.hooks or {}).get(hook)
        if handler is None:
            raise PluginManagerError(f"PLUGIN_SLOT_HOOK_MISSING:{slot_id}:{hook}")
        plugin_id = str(plugin["plugin_id"])
        capability_id = manifest.capabilities[0].capability_id
        started = time.perf_counter()
        self._acquire_call(plugin_id)
        try:
            output = handler(**kwargs)
            self._record_usage(
                plugin_id=plugin_id,
                plugin_version=manifest.version,
                capability_id=capability_id,
                slot_id=slot_id,
                invocation_kind="hook",
                started=started,
                input_value=kwargs,
                output_value=output,
            )
            return output
        except BaseException as error:
            self._record_usage(
                plugin_id=plugin_id,
                plugin_version=manifest.version,
                capability_id=capability_id,
                slot_id=slot_id,
                invocation_kind="hook",
                started=started,
                input_value=kwargs,
                issue_code=type(error).__name__,
            )
            raise
        finally:
            self._release_call(plugin_id)

    def import_asset(self, *, kind: str, archive: Path) -> dict[str, object]:
        """Run the selected importer without granting it direct asset-store writes."""

        if kind not in {"map", "vehicle"}:
            raise PluginManagerError("ASSET_KIND_INVALID")
        slot_id = "assets.map-importer" if kind == "map" else "assets.vehicle-importer"
        matches: list[tuple[dict[str, object], PluginManifest]] = []
        for plugin in self.store.list_plugins():
            if not bool(plugin["enabled"]) or plugin["status"] != "healthy":
                continue
            manifest = self._manifest(plugin)
            if manifest.placement.slot_id == slot_id:
                matches.append((plugin, manifest))
        if len(matches) != 1:
            raise PluginManagerError(f"PLUGIN_SLOT_RESOLUTION_FAILED:{slot_id}")
        plugin, manifest = matches[0]
        plugin_id = str(plugin["plugin_id"])
        if bool(plugin["builtin"]):
            imported = self.invoke_single_slot(slot_id, "import", store=self.store, archive=archive)
            if not isinstance(imported, dict):
                raise PluginManagerError("ASSET_IMPORT_RESULT_INVALID")
            return {**imported, "importer_plugin_id": plugin_id}
        if manifest.runtime.kind != "mcp-stdio":
            raise PluginManagerError("ASSET_IMPORTER_RUNTIME_UNSUPPORTED")
        if "asset.read" not in manifest.permissions:
            raise PluginManagerError("ASSET_IMPORTER_READ_PERMISSION_REQUIRED")
        if "asset.write-staging" not in manifest.permissions:
            raise PluginManagerError("ASSET_IMPORTER_STAGING_PERMISSION_REQUIRED")
        capabilities = [
            item
            for item in manifest.capabilities
            if item.metadata.get("extension_hook") == "import_asset"
        ]
        if len(capabilities) != 1:
            raise PluginManagerError("ASSET_IMPORTER_CAPABILITY_INVALID")
        capability = capabilities[0]
        source_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        self._acquire_call(plugin_id)
        try:
            plugin_root = Path(str(plugin["bundle_root"]))
            self._verify_integrity(plugin_root, manifest)
            with tempfile.TemporaryDirectory(prefix="dd-asset-import-") as temporary:
                exchange_root = Path(temporary)
                input_root = exchange_root / "input"
                output_root = exchange_root / "output"
                input_root.mkdir()
                output_root.mkdir()
                input_archive = input_root / "source.zip"
                shutil.copy2(archive, input_archive)
                output_archive = output_root / f"canonical-{kind}.zip"
                broker = CoreCapabilityBroker(
                    read_roots={"imports": input_root},
                    write_roots={"staging": output_root},
                )
                client = self._mcp_client(
                    plugin,
                    manifest,
                    capability=capability,
                    broker_factory=broker,
                )
                arguments = {
                    "asset_kind": kind,
                    "input_root": "imports",
                    "input_path": input_archive.name,
                    "input_sha256": source_sha256,
                    "output_root": "staging",
                    "output_path": output_archive.name,
                }
                jsonschema.validate(arguments, capability.input_schema)
                result = client.call_tool(capability.capability_id, arguments)
                jsonschema.validate(result, capability.output_schema)
                if (
                    not output_archive.is_file()
                    or output_archive.stat().st_size > 512 * 1024 * 1024
                ):
                    raise PluginManagerError("ASSET_IMPORTER_OUTPUT_INVALID")
                output_sha256 = hashlib.sha256(output_archive.read_bytes()).hexdigest()
                if result.get("output_sha256") != output_sha256:
                    raise PluginManagerError("ASSET_IMPORTER_OUTPUT_HASH_MISMATCH")
                imported = self.store.import_asset_bundle(output_archive, kind)
                return {
                    **imported,
                    "importer_plugin_id": plugin_id,
                    "source_sha256": source_sha256,
                    "canonical_bundle_sha256": output_sha256,
                }
        except (PluginProcessError, PluginManagerError, jsonschema.ValidationError) as error:
            failed = self.store.set_plugin_lifecycle(
                plugin_id,
                enabled=False,
                status="quarantined",
                health="failed",
                last_error=str(error)[:800],
            )
            self._receipt(
                plugin=failed,
                operation="quarantine",
                previous_state="healthy",
                current_state="quarantined",
                accepted=True,
                issue_codes=[str(error)[:96]],
            )
            if isinstance(error, PluginManagerError):
                raise
            raise PluginManagerError(str(error)) from error
        finally:
            self._release_call(plugin_id)

    def capability_for_slot(
        self, snapshot: PluginSnapshot, slot_id: str
    ) -> tuple[PluginSnapshotEntry, PluginManifest, PluginCapability]:
        matches: list[tuple[PluginSnapshotEntry, PluginManifest, PluginCapability]] = []
        for entry in snapshot.plugins:
            plugin = self.store.get_plugin(entry.plugin_id)
            manifest = self._manifest(plugin)
            if manifest.placement.slot_id != slot_id:
                continue
            for capability in manifest.capabilities:
                matches.append((entry, manifest, capability))
        if len(matches) != 1:
            raise PluginManagerError(f"PLUGIN_SLOT_RESOLUTION_FAILED:{slot_id}")
        return matches[0]

    def ui_panel_document(
        self, plugin_id: str, *, data_sources: dict[str, object] | None = None
    ) -> dict[str, object]:
        plugin = self.store.get_plugin(plugin_id)
        manifest = self._manifest(plugin)
        if not bool(plugin["enabled"]) or manifest.runtime.kind != "ui-declarative":
            raise PluginManagerError("UI_PLUGIN_NOT_ACTIVE")
        capability = next((item for item in manifest.capabilities if item.kind == "ui-panel"), None)
        if capability is None:
            raise PluginManagerError("UI_PLUGIN_PANEL_MISSING")
        entrypoint = capability.metadata.get("entrypoint")
        if not isinstance(entrypoint, str):
            raise PluginManagerError("UI_PLUGIN_ENTRYPOINT_MISSING")
        root = Path(str(plugin["bundle_root"])).resolve()
        panel = (root / entrypoint).resolve()
        if root not in panel.parents or not panel.is_file() or panel.stat().st_size > 256_000:
            raise PluginManagerError("UI_PLUGIN_ENTRYPOINT_INVALID")
        try:
            value = json.loads(panel.read_text(encoding="utf-8"))
            document = validate_panel_document(value)
        except (OSError, ValueError, ValidationError) as error:
            raise PluginManagerError("UI_PLUGIN_DOCUMENT_INVALID") from error
        sources = {
            "plugin": plugin,
            "configuration": self.store.get_plugin_configuration(plugin_id)["configuration"],
            "events": {"items": self.store.list_plugin_events(plugin_id)},
            **(data_sources or {}),
        }
        return materialize_panel(
            document,
            sources=sources,
            configuration_schema=manifest.configuration_schema,
        )

    def _dependents(self, plugin_id: str, *, enabled_only: bool) -> list[str]:
        dependents: list[str] = []
        for candidate in self.store.list_plugins():
            if enabled_only and not bool(candidate["enabled"]):
                continue
            manifest = self._manifest(candidate)
            if any(
                dependency.plugin_id == plugin_id and not dependency.optional
                for dependency in manifest.dependencies
            ):
                dependents.append(manifest.plugin_id)
        return sorted(dependents)

    def _receipt(
        self,
        *,
        plugin: dict[str, object],
        operation: str,
        previous_state: str | None,
        current_state: str,
        accepted: bool,
        issue_codes: list[str] | None = None,
    ) -> dict[str, object]:
        receipt = PluginLifecycleReceipt.model_validate(
            {
                "receipt_id": f"plugin-event-{uuid4().hex[:24]}",
                "plugin_id": plugin["plugin_id"],
                "version": plugin["version"],
                "operation": operation,
                "previous_state": previous_state,
                "current_state": current_state,
                "accepted": accepted,
                "issue_codes": issue_codes or [],
                "package_sha256": plugin["package_sha256"],
                "created_at": datetime.now(UTC),
            }
        )
        payload = receipt.model_dump(mode="json")
        self.store.record_plugin_event(payload)
        return payload

    @staticmethod
    def _validated_archive_members(bundle: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        members = bundle.infolist()
        total_size = sum(item.file_size for item in members)
        if not members or len(members) > 2_000 or total_size > 512 * 1024 * 1024:
            raise PluginManagerError("PLUGIN_BUNDLE_LIMIT_EXCEEDED")
        for item in members:
            path = Path(item.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or "\x00" in item.filename:
                raise PluginManagerError("PLUGIN_BUNDLE_PATH_TRAVERSAL")
            if item.file_size > 256 * 1024 * 1024:
                raise PluginManagerError("PLUGIN_BUNDLE_FILE_TOO_LARGE")
            if path.as_posix() == "plugin.json" and item.file_size > 2 * 1024 * 1024:
                raise PluginManagerError("PLUGIN_MANIFEST_TOO_LARGE")
            unix_type = (item.external_attr >> 16) & 0o170000
            if unix_type == stat.S_IFLNK:
                raise PluginManagerError("PLUGIN_BUNDLE_SYMLINK_FORBIDDEN")
        return members

    @staticmethod
    def _verify_integrity(staging: Path, manifest: PluginManifest) -> None:
        files = {
            path.relative_to(staging).as_posix(): path
            for path in staging.rglob("*")
            if path.is_file() and path.name != "plugin.json"
        }
        if set(files) != set(manifest.file_sha256):
            raise PluginManagerError("PLUGIN_FILE_MANIFEST_MISMATCH")
        for relative, path in files.items():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != manifest.file_sha256[relative]:
                raise PluginManagerError(f"PLUGIN_FILE_HASH_MISMATCH:{relative}")

    def _validate_dependencies(self, manifest: PluginManifest, *, require_enabled: bool) -> None:
        for dependency in manifest.dependencies:
            try:
                installed = self.store.get_plugin(dependency.plugin_id)
            except KeyError:
                if dependency.optional:
                    continue
                raise PluginManagerError(
                    f"PLUGIN_DEPENDENCY_MISSING:{dependency.plugin_id}"
                ) from None
            if not _version_matches(str(installed["version"]), dependency.version):
                raise PluginManagerError(f"PLUGIN_DEPENDENCY_VERSION:{dependency.plugin_id}")
            if require_enabled and not bool(installed["enabled"]):
                raise PluginManagerError(f"PLUGIN_DEPENDENCY_DISABLED:{dependency.plugin_id}")

    def _validate_conflicts(self, manifest: PluginManifest) -> None:
        enabled = {
            str(item["plugin_id"]): self._manifest(item)
            for item in self.store.list_plugins()
            if bool(item["enabled"]) and item["plugin_id"] != manifest.plugin_id
        }
        direct = set(manifest.conflicts).intersection(enabled)
        reverse = {
            plugin_id
            for plugin_id, candidate in enabled.items()
            if manifest.plugin_id in candidate.conflicts
        }
        conflicts = sorted(direct | reverse)
        if conflicts:
            raise PluginManagerError("PLUGIN_CONFLICT:" + ",".join(conflicts))

    def _validate_slot_contract(self, manifest: PluginManifest) -> None:
        peers = []
        for record in self.store.list_plugins():
            if record["plugin_id"] == manifest.plugin_id:
                continue
            candidate = self._manifest(record)
            if candidate.placement.slot_id == manifest.placement.slot_id:
                peers.append(candidate)
        if any(
            peer.placement.activation_mode != manifest.placement.activation_mode for peer in peers
        ):
            raise PluginManagerError("PLUGIN_SLOT_ACTIVATION_MODE_MISMATCH")
        if manifest.placement.activation_mode != "pipeline":
            return
        active = [
            peer for peer in peers if bool(self.store.get_plugin(peer.plugin_id)["enabled"])
        ] + [manifest]
        by_id = {item.plugin_id: item for item in active}
        edges: dict[str, set[str]] = {plugin_id: set() for plugin_id in by_id}
        indegree: dict[str, int] = {plugin_id: 0 for plugin_id in by_id}
        for item in active:
            for predecessor in item.placement.runs_after:
                if predecessor in by_id and item.plugin_id not in edges[predecessor]:
                    edges[predecessor].add(item.plugin_id)
                    indegree[item.plugin_id] += 1
            for successor in item.placement.runs_before:
                if successor in by_id and successor not in edges[item.plugin_id]:
                    edges[item.plugin_id].add(successor)
                    indegree[successor] += 1
        ready = [plugin_id for plugin_id, degree in indegree.items() if degree == 0]
        visited = 0
        while ready:
            current = ready.pop()
            visited += 1
            for successor in edges[current]:
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    ready.append(successor)
        if visited != len(by_id):
            raise PluginManagerError("PLUGIN_PIPELINE_ORDERING_CYCLE")

    @staticmethod
    def _validate_static_bundle(staging: Path, manifest: PluginManifest) -> None:
        if manifest.runtime.kind == "mcp-stdio":
            if not any(item.kind in PLUGIN_MCP_CAPABILITY_KINDS for item in manifest.capabilities):
                raise PluginManagerError("MCP_PLUGIN_HAS_NO_TOOL_CAPABILITY")
            try:
                resolve_plugin_command(staging, manifest.runtime.command)
            except PluginProcessError as error:
                raise PluginManagerError(str(error)) from error
            return
        if manifest.runtime.kind == "ui-declarative":
            for capability in manifest.capabilities:
                if capability.kind != "ui-panel":
                    continue
                entrypoint = capability.metadata.get("entrypoint")
                if not isinstance(entrypoint, str) or not entrypoint:
                    raise PluginManagerError("UI_PLUGIN_ENTRYPOINT_MISSING")
                panel = (staging / entrypoint).resolve()
                if staging.resolve() not in panel.parents or not panel.is_file():
                    raise PluginManagerError("UI_PLUGIN_ENTRYPOINT_INVALID")
                try:
                    value = json.loads(panel.read_text(encoding="utf-8"))
                except (OSError, ValueError) as error:
                    raise PluginManagerError("UI_PLUGIN_DOCUMENT_INVALID") from error
                try:
                    validate_panel_document(value)
                except (ValueError, ValidationError) as error:
                    raise PluginManagerError("UI_PLUGIN_DOCUMENT_INVALID") from error
            return
        if manifest.runtime.kind == "ros2-node":
            package_name = manifest.runtime.command[0]
            package_manifest = staging / "ros_ws" / "src" / package_name / "package.xml"
            if not package_manifest.is_file():
                raise PluginManagerError("ROS2_PLUGIN_PACKAGE_MISSING")

    def import_bundle(self, archive: Path) -> dict[str, object]:
        if not zipfile.is_zipfile(archive):
            raise PluginManagerError("PLUGIN_BUNDLE_MUST_BE_ZIP")
        package_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=self.store.plugins_root))
        moved = False
        try:
            with zipfile.ZipFile(archive) as bundle:
                members = self._validated_archive_members(bundle)
                bundle.extractall(staging, members)
            manifest_path = staging / "plugin.json"
            if not manifest_path.is_file():
                raise PluginManagerError("PLUGIN_MANIFEST_MISSING")
            try:
                manifest = PluginManifest.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
            except (OSError, ValidationError) as error:
                raise PluginManagerError("PLUGIN_MANIFEST_INVALID") from error
            if manifest.runtime.kind not in {"mcp-stdio", "ros2-node", "ui-declarative"}:
                raise PluginManagerError("PLUGIN_RUNTIME_NOT_IMPORTABLE")
            if manifest.runtime.kind == "ros2-node":
                raise PluginManagerError("NATIVE_PLUGIN_REQUIRES_CERTIFIED_INSTALLER")
            if not manifest.removable:
                raise PluginManagerError("THIRD_PARTY_PLUGIN_MUST_BE_REMOVABLE")
            if "vehicle.actuate" in manifest.permissions:
                raise PluginManagerError("THIRD_PARTY_ACTUATION_NOT_CERTIFIED")
            if manifest.placement.slot_id in self.protected_slots:
                raise PluginManagerError("THIRD_PARTY_PROTECTED_SLOT_NOT_CERTIFIED")
            extension_capabilities = [
                capability
                for capability in manifest.capabilities
                if "extension_hook" in capability.metadata
            ]
            if extension_capabilities:
                if manifest.runtime.kind != "mcp-stdio":
                    raise PluginManagerError("EXTENSION_HOOK_REQUIRES_MCP_STDIO")
                if len(extension_capabilities) > 32:
                    raise PluginManagerError("EXTENSION_PLUGIN_CAPABILITY_LIMIT")
                if (
                    manifest.placement.activation_mode == "single"
                    and len(extension_capabilities) != 1
                ):
                    raise PluginManagerError("SINGLE_SLOT_REQUIRES_ONE_HOOK_CAPABILITY")
                for extension_capability in extension_capabilities:
                    extension_hook = extension_capability.metadata.get("extension_hook")
                    if extension_hook not in PLUGIN_EXTENSION_HOOKS:
                        raise PluginManagerError("EXTENSION_HOOK_NOT_SUPPORTED")
                    if (
                        not extension_capability.input_schema
                        or not extension_capability.output_schema
                    ):
                        raise PluginManagerError("EXTENSION_HOOK_SCHEMA_REQUIRED")
                    if extension_hook == "import_asset" and (
                        len(extension_capabilities) != 1
                        or extension_capability.kind not in {"map-importer", "vehicle-importer"}
                        or manifest.placement.slot_id
                        not in {"assets.map-importer", "assets.vehicle-importer"}
                        or "asset.write-staging" not in manifest.permissions
                    ):
                        raise PluginManagerError("ASSET_IMPORTER_CONTRACT_INVALID")
            if _version_tuple(manifest.minimum_app_version) > _version_tuple(self.app_version):
                raise PluginManagerError("PLUGIN_APP_VERSION_INCOMPATIBLE")
            self._verify_integrity(staging, manifest)
            trust_decision = self.trust_store.verify(manifest, package_sha256)
            self._govern(
                manifest=manifest,
                operation="import",
                trust_status=trust_decision.status,
            )
            self._validate_static_bundle(staging, manifest)
            self._validate_dependencies(manifest, require_enabled=False)
            destination = (
                self.store.plugins_root / manifest.plugin_id / manifest.version
            ).resolve()
            root = self.store.plugins_root.resolve()
            if root not in destination.parents:
                raise PluginManagerError("PLUGIN_DESTINATION_INVALID")
            try:
                current = self.store.get_plugin(manifest.plugin_id)
            except KeyError:
                current = None
            try:
                existing_version = self.store.get_plugin_version(
                    manifest.plugin_id, manifest.version
                )
            except KeyError:
                existing_version = None
            if existing_version is not None and (
                existing_version["package_sha256"] != package_sha256
            ):
                raise PluginManagerError("PLUGIN_VERSION_IMMUTABLE")
            if destination.exists():
                if existing_version is None:
                    raise PluginManagerError("PLUGIN_VERSION_DIRECTORY_UNTRACKED")
                shutil.rmtree(staging)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staging), destination)
                moved = True
            if current is None:
                installed = self.store.upsert_plugin(
                    manifest=manifest,
                    package_sha256=package_sha256,
                    bundle_root=destination,
                    builtin=False,
                    enabled=False,
                    status="disabled",
                    health="unknown",
                    trust_status=trust_decision.status,
                    trust_decision=trust_decision.model_dump(mode="json"),
                )
                operation = "install"
            else:
                if existing_version is None:
                    self.store.install_plugin_version(
                        manifest=manifest,
                        package_sha256=package_sha256,
                        bundle_root=destination,
                        trust_status=trust_decision.status,
                        trust_decision=trust_decision.model_dump(mode="json"),
                    )
                installed = current
                operation = "update"
                installed = {
                    **installed,
                    "staged_version": manifest.version,
                    "staged_package_sha256": package_sha256,
                }
            receipt = self._receipt(
                plugin={
                    **installed,
                    "version": manifest.version,
                    "package_sha256": package_sha256,
                },
                operation=operation,
                previous_state=str(current["status"]) if current is not None else None,
                current_state=str(installed["status"]),
                accepted=True,
            )
            return {**installed, "receipt": receipt}
        except BaseException:
            if moved and "destination" in locals() and destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            raise
        finally:
            if staging.exists() and not moved:
                shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _manifest(plugin: dict[str, object]) -> PluginManifest:
        value = plugin.get("manifest")
        if not isinstance(value, dict):
            raise PluginManagerError("PLUGIN_MANIFEST_RECORD_INVALID")
        return PluginManifest.model_validate(value)

    def _mcp_tools(
        self, plugin: dict[str, object], manifest: PluginManifest
    ) -> list[dict[str, Any]]:
        root = Path(str(plugin["bundle_root"]))
        self._verify_integrity(root, manifest)
        try:
            return self._mcp_client(plugin, manifest).list_tools()
        except PluginProcessError as error:
            raise PluginManagerError(str(error)) from error

    def healthcheck(self, plugin_id: str) -> dict[str, object]:
        plugin = self.store.get_plugin(plugin_id)
        manifest = self._manifest(plugin)
        previous = str(plugin["status"])
        try:
            if bool(plugin["builtin"]):
                definition = self._definitions.get(plugin_id)
                if definition is None or definition.manifest != manifest:
                    raise PluginManagerError("BUILTIN_PLUGIN_DEFINITION_MISMATCH")
            elif manifest.runtime.kind == "mcp-stdio":
                catalog = self._mcp_tools(plugin, manifest)
                expected = {
                    item.capability_id: item
                    for item in manifest.capabilities
                    if item.kind in PLUGIN_MCP_CAPABILITY_KINDS
                }
                actual = {str(item.get("name", "")): item for item in catalog}
                if set(expected) != set(actual):
                    raise PluginManagerError("PLUGIN_TOOL_CATALOG_MISMATCH")
                for tool_id, capability in expected.items():
                    tool = actual[tool_id]
                    if tool.get("inputSchema") != capability.input_schema:
                        raise PluginManagerError("PLUGIN_TOOL_INPUT_SCHEMA_MISMATCH")
                    if tool.get("outputSchema") != capability.output_schema:
                        raise PluginManagerError("PLUGIN_TOOL_OUTPUT_SCHEMA_MISMATCH")
            elif manifest.runtime.kind in {"ros2-node", "ui-declarative"}:
                root = Path(str(plugin["bundle_root"]))
                self._validate_static_bundle(root, manifest)
            self.store.set_plugin_lifecycle(
                plugin_id,
                status="healthy" if bool(plugin["enabled"]) else "disabled",
                health="healthy",
            )
        except (PluginManagerError, ValidationError) as error:
            failed = self.store.set_plugin_lifecycle(
                plugin_id,
                enabled=False,
                status="quarantined",
                health="failed",
                last_error=str(error)[:800],
            )
            self._receipt(
                plugin=failed,
                operation="quarantine",
                previous_state=previous,
                current_state="quarantined",
                accepted=True,
                issue_codes=[str(error)[:96]],
            )
            raise
        checked = self.store.get_plugin(plugin_id)
        receipt = self._receipt(
            plugin=checked,
            operation="healthcheck",
            previous_state=previous,
            current_state=str(checked["status"]),
            accepted=True,
        )
        return {**checked, "receipt": receipt}

    def enable(self, plugin_id: str) -> dict[str, object]:
        with self._mutation_lock:
            return self._enable(plugin_id)

    def _enable(self, plugin_id: str) -> dict[str, object]:
        plugin = self.store.get_plugin(plugin_id)
        manifest = self._manifest(plugin)
        official_digest = self._official_packages.get((manifest.plugin_id, manifest.version))
        if not bool(plugin["builtin"]) and official_digest != str(plugin["package_sha256"]):
            try:
                trust_decision = self.trust_store.verify(manifest, str(plugin["package_sha256"]))
            except TrustStoreError as error:
                raise PluginManagerError(str(error)) from error
            self.store.set_plugin_trust(
                plugin_id,
                version=manifest.version,
                trust_status=trust_decision.status,
                trust_decision=trust_decision.model_dump(mode="json"),
            )
            plugin = self.store.get_plugin(plugin_id)
            if trust_decision.status not in {"verified", "local-approved"}:
                raise PluginManagerError(
                    "PLUGIN_TRUST_REQUIRED:" + ",".join(trust_decision.issue_codes)
                )
        self._govern(
            manifest=manifest,
            operation="enable",
            trust_status=str(plugin["trust_status"]),
        )
        previous = str(plugin["status"])
        self._validate_dependencies(manifest, require_enabled=True)
        self._validate_conflicts(manifest)
        self._validate_slot_contract(manifest)
        self.healthcheck(plugin_id)
        peers: list[tuple[dict[str, object], PluginManifest]] = []
        if manifest.placement.activation_mode == "single":
            for candidate in self.store.list_plugins():
                if candidate["plugin_id"] == plugin_id or not bool(candidate["enabled"]):
                    continue
                candidate_manifest = self._manifest(candidate)
                if candidate_manifest.placement.slot_id == manifest.placement.slot_id:
                    peers.append((candidate, candidate_manifest))
        affected_threads: list[str] = []
        for _candidate, candidate_manifest in peers:
            dependents = self._dependents(candidate_manifest.plugin_id, enabled_only=True)
            if dependents:
                raise PluginManagerError("PLUGIN_REQUIRED_BY_ENABLED:" + ",".join(dependents))
        draining = {
            str(candidate["plugin_id"]): {
                "enabled": True,
                "status": "draining",
                "health": str(candidate["health"]),
            }
            for candidate, _candidate_manifest in peers
        }
        if draining:
            self.store.set_plugin_lifecycles(draining)
        try:
            for _candidate, candidate_manifest in peers:
                self._drain_calls(candidate_manifest.plugin_id)
                if self._disable_guard:
                    affected_threads.extend(
                        self._disable_guard(
                            candidate_manifest.plugin_id,
                            candidate_manifest.placement.swap_policy,
                        )
                    )
        except (RuntimeError, PluginManagerError) as error:
            if peers:
                self.store.set_plugin_lifecycles(
                    {
                        str(candidate["plugin_id"]): {
                            "enabled": bool(candidate["enabled"]),
                            "status": str(candidate["status"]),
                            "health": str(candidate["health"]),
                            "last_error": candidate.get("last_error"),
                        }
                        for candidate, _candidate_manifest in peers
                    }
                )
            raise PluginManagerError(f"PLUGIN_SWAP_FAILED:{error}") from error
        updates: dict[str, dict[str, object]] = {
            plugin_id: {
                "enabled": True,
                "status": "healthy",
                "health": "healthy",
                "last_error": None,
            }
        }
        for candidate, _candidate_manifest in peers:
            updates[str(candidate["plugin_id"])] = {
                "enabled": False,
                "status": "disabled",
                "health": "unknown",
                "last_error": None,
            }
        self.store.set_plugin_lifecycles(updates)
        for candidate, _candidate_manifest in peers:
            self._mcp_sessions.invalidate(str(candidate["plugin_id"]))
        enabled = self.store.get_plugin(plugin_id)
        replaced = [str(candidate["plugin_id"]) for candidate, _manifest in peers]
        replacement_receipts = [
            self._receipt(
                plugin=self.store.get_plugin(replaced_id),
                operation="disable",
                previous_state="healthy",
                current_state="disabled",
                accepted=True,
            )
            for replaced_id in replaced
        ]
        receipt = self._receipt(
            plugin=enabled,
            operation="enable",
            previous_state=previous,
            current_state="healthy",
            accepted=True,
        )
        return {
            **enabled,
            "receipt": receipt,
            "replacement_receipts": replacement_receipts,
            "replaced_plugins": replaced,
            "affected_threads": sorted(set(affected_threads)),
        }

    def disable(self, plugin_id: str) -> dict[str, object]:
        with self._mutation_lock:
            return self._disable(plugin_id)

    def _disable(
        self, plugin_id: str, *, replacement_plugin_id: str | None = None
    ) -> dict[str, object]:
        plugin = self.store.get_plugin(plugin_id)
        manifest = self._manifest(plugin)
        if not manifest.disable_allowed:
            raise PluginManagerError("PLUGIN_REQUIRED_BY_SAFETY_KERNEL")
        if (
            manifest.placement.slot_id in self.required_single_slots
            and replacement_plugin_id is None
            and not any(
                bool(candidate["enabled"])
                and candidate["plugin_id"] != plugin_id
                and self._manifest(candidate).placement.slot_id == manifest.placement.slot_id
                for candidate in self.store.list_plugins()
            )
        ):
            raise PluginManagerError("PLUGIN_SLOT_REQUIRES_ONE_ENABLED")
        dependents = self._dependents(plugin_id, enabled_only=True)
        if dependents:
            raise PluginManagerError("PLUGIN_REQUIRED_BY_ENABLED:" + ",".join(dependents))
        previous = str(plugin["status"])
        self.store.set_plugin_lifecycle(
            plugin_id, enabled=True, status="draining", health=str(plugin["health"])
        )
        try:
            self._drain_calls(plugin_id)
            affected_threads = (
                self._disable_guard(plugin_id, manifest.placement.swap_policy)
                if self._disable_guard
                else []
            )
        except (RuntimeError, PluginManagerError) as error:
            self.store.set_plugin_lifecycle(
                plugin_id, enabled=True, status=previous, health=str(plugin["health"])
            )
            raise PluginManagerError(f"PLUGIN_DRAIN_FAILED:{error}") from error
        disabled = self.store.set_plugin_lifecycle(
            plugin_id, enabled=False, status="disabled", health="unknown"
        )
        self._mcp_sessions.invalidate(plugin_id)
        receipt = self._receipt(
            plugin=disabled,
            operation="disable",
            previous_state=previous,
            current_state="disabled",
            accepted=True,
        )
        return {**disabled, "receipt": receipt, "affected_threads": affected_threads}

    def rollback(self, plugin_id: str, version: str) -> dict[str, object]:
        return self.activate_version(plugin_id, version, operation="rollback")

    def promote_version(self, plugin_id: str, version: str) -> dict[str, object]:
        """Health-gated version promotion with fail-closed automatic rollback."""

        with self._mutation_lock:
            current = self.store.get_plugin(plugin_id)
            previous_version = str(current["version"])
            previous_enabled = bool(current["enabled"])
            if previous_version == version:
                return {**current, "promoted": False, "rollback": False}
            target = self.store.get_plugin_version(plugin_id, version)
            target_manifest = PluginManifest.model_validate(target["manifest"])
            self._govern(
                manifest=target_manifest,
                operation="promote",
                trust_status=str(target["trust_status"]),
            )
            selected_ring = str(self.store.get_settings().get("plugin_update_ring", "stable"))
            allowed_rings = {
                "stable": {"stable"},
                "preview": {"stable", "preview"},
                "canary": {"stable", "preview", "canary"},
                "pinned": set(),
            }
            if target_manifest.provenance.update_ring not in allowed_rings.get(
                selected_ring, {"stable"}
            ):
                raise PluginManagerError("PLUGIN_UPDATE_RING_DENIED")
            if previous_enabled:
                self._disable(plugin_id)
            self._mcp_sessions.invalidate(plugin_id)
            self.store.activate_plugin_version(plugin_id, version)
            try:
                promoted = (
                    self._enable(plugin_id) if previous_enabled else self.healthcheck(plugin_id)
                )
            except (PluginManagerError, ValidationError) as error:
                self._mcp_sessions.invalidate(plugin_id)
                self.store.activate_plugin_version(plugin_id, previous_version)
                recovery_error: str | None = None
                try:
                    (self._enable(plugin_id) if previous_enabled else self.healthcheck(plugin_id))
                except (PluginManagerError, ValidationError) as rollback_error:
                    recovery_error = str(rollback_error)
                restored = self.store.get_plugin(plugin_id)
                rollback_receipt = self._receipt(
                    plugin=restored,
                    operation="rollback",
                    previous_state="failed",
                    current_state=str(restored["status"]),
                    accepted=recovery_error is None,
                    issue_codes=[
                        "PLUGIN_PROMOTION_AUTO_ROLLBACK",
                        f"FAILED_VERSION_{version}",
                        f"RESTORED_VERSION_{previous_version}",
                        str(error)[:96],
                    ]
                    + ([f"ROLLBACK_FAILED:{recovery_error}"[:96]] if recovery_error else []),
                )
                if recovery_error:
                    raise PluginManagerError(
                        f"PLUGIN_PROMOTION_AND_ROLLBACK_FAILED:{error}:{recovery_error}"
                    ) from error
                raise PluginManagerError(
                    f"PLUGIN_PROMOTION_ROLLED_BACK:{error}:{rollback_receipt['receipt_id']}"
                ) from error
            selected = self.store.get_plugin(plugin_id)
            promotion_receipt = self._receipt(
                plugin=selected,
                operation="update",
                previous_state=str(current["status"]),
                current_state=str(selected["status"]),
                accepted=True,
                issue_codes=[
                    "PLUGIN_PROMOTION_HEALTH_GATED",
                    f"PREVIOUS_VERSION_{previous_version}",
                    f"ACTIVE_VERSION_{version}",
                ],
            )
            return {
                **selected,
                "promoted": True,
                "rollback": False,
                "receipt": promotion_receipt,
                "healthcheck": promoted,
            }

    def activate_version(
        self, plugin_id: str, version: str, *, operation: str = "activate"
    ) -> dict[str, object]:
        current = self.store.get_plugin(plugin_id)
        manifest = self._manifest(current)
        if not manifest.removable:
            raise PluginManagerError("PLUGIN_REQUIRED_BY_SAFETY_KERNEL")
        if bool(current["enabled"]):
            self.disable(plugin_id)
        self._mcp_sessions.invalidate(plugin_id)
        rolled_back = self.store.activate_plugin_version(plugin_id, version)
        receipt = self._receipt(
            plugin=rolled_back,
            operation=operation,
            previous_state=str(current["status"]),
            current_state="disabled",
            accepted=True,
        )
        return {**rolled_back, "receipt": receipt}

    def uninstall(self, plugin_id: str) -> dict[str, object]:
        with self._mutation_lock:
            plugin = self.store.get_plugin(plugin_id)
            manifest = self._manifest(plugin)
            if bool(plugin["builtin"]) or not manifest.removable:
                raise PluginManagerError("BUILTIN_PLUGIN_NOT_UNINSTALLABLE")
            dependents = self._dependents(plugin_id, enabled_only=False)
            if dependents:
                raise PluginManagerError("PLUGIN_REQUIRED_BY:" + ",".join(dependents))
            if self._disable_guard is not None:
                # Deletion is stronger than disabling the next catalog: an active
                # task still owns the bundle recorded in its frozen snapshot.
                try:
                    self._disable_guard(plugin_id, "restart")
                except RuntimeError as error:
                    raise PluginManagerError(f"PLUGIN_UNINSTALL_REQUIRES_IDLE:{error}") from error
            if bool(plugin["enabled"]):
                self._disable(plugin_id)
            self._drain_calls(plugin_id)
            self._mcp_sessions.invalidate(plugin_id)
            root = (self.store.plugins_root / plugin_id).resolve()
            plugins_root = self.store.plugins_root.resolve()
            if root.parent != plugins_root:
                raise PluginManagerError("PLUGIN_UNINSTALL_PATH_INVALID")
            if root.exists():
                shutil.rmtree(root)
            removed = self.store.mark_plugin_uninstalled(plugin_id)
            receipt = self._receipt(
                plugin=removed,
                operation="uninstall",
                previous_state=str(plugin["status"]),
                current_state="uninstalled",
                accepted=True,
            )
            return {**removed, "receipt": receipt}

    def configure(self, plugin_id: str, configuration: dict[str, object]) -> dict[str, object]:
        with self._mutation_lock:
            return self._configure(plugin_id, configuration)

    def approve_local_package(self, plugin_id: str) -> dict[str, object]:
        """Approve only the exact immutable bytes currently selected for a local plugin."""

        with self._mutation_lock:
            plugin = self.store.get_plugin(plugin_id)
            if bool(plugin["builtin"]):
                return plugin
            manifest = self._manifest(plugin)
            self._govern(
                manifest=manifest,
                operation="trust-local-package",
                trust_status=str(plugin["trust_status"]),
            )
            package_sha256 = str(plugin["package_sha256"])
            try:
                self.trust_store.approve_local(manifest, package_sha256)
                decision = self.trust_store.verify(manifest, package_sha256)
            except TrustStoreError as error:
                raise PluginManagerError(str(error)) from error
            trusted = self.store.set_plugin_trust(
                plugin_id,
                version=manifest.version,
                trust_status=decision.status,
                trust_decision=decision.model_dump(mode="json"),
            )
            receipt = self._receipt(
                plugin=trusted,
                operation="trust-local-package",
                previous_state=str(plugin["status"]),
                current_state=str(trusted["status"]),
                accepted=True,
                issue_codes=[f"TRUST_STATUS:{decision.status}"],
            )
            return {**trusted, "receipt": receipt}

    def approve_local_version(self, plugin_id: str, version: str) -> dict[str, object]:
        """Approve the exact bytes of an installed or staged local version."""

        with self._mutation_lock:
            current = self.store.get_plugin(plugin_id)
            if bool(current["builtin"]):
                return self.store.get_plugin_version(plugin_id, version)
            target = self.store.get_plugin_version(plugin_id, version)
            manifest = PluginManifest.model_validate(target["manifest"])
            self._govern(
                manifest=manifest,
                operation="trust-local-package",
                trust_status=str(target["trust_status"]),
            )
            package_sha256 = str(target["package_sha256"])
            try:
                self.trust_store.approve_local(manifest, package_sha256)
                decision = self.trust_store.verify(manifest, package_sha256)
            except TrustStoreError as error:
                raise PluginManagerError(str(error)) from error
            trusted = self.store.set_plugin_version_trust(
                plugin_id,
                version=version,
                trust_status=decision.status,
                trust_decision=decision.model_dump(mode="json"),
            )
            receipt_plugin = {
                "plugin_id": plugin_id,
                "version": version,
                "package_sha256": package_sha256,
                "status": current["status"],
            }
            receipt = self._receipt(
                plugin=receipt_plugin,
                operation="trust-local-package",
                previous_state=str(current["status"]),
                current_state=str(current["status"]),
                accepted=True,
                issue_codes=[f"TRUST_STATUS:{decision.status}", "STAGED_VERSION_APPROVAL"],
            )
            return {**trusted, "receipt": receipt}

    def revoke_package(self, plugin_id: str) -> dict[str, object]:
        with self._mutation_lock:
            plugin = self.store.get_plugin(plugin_id)
            if bool(plugin["builtin"]):
                raise PluginManagerError("BUILTIN_TRUST_CANNOT_BE_REVOKED_LOCALLY")
            if bool(plugin["enabled"]):
                self._disable(plugin_id)
                plugin = self.store.get_plugin(plugin_id)
            manifest = self._manifest(plugin)
            package_sha256 = str(plugin["package_sha256"])
            try:
                self.trust_store.revoke_package(package_sha256)
                decision = self.trust_store.verify(manifest, package_sha256)
            except TrustStoreError as error:
                raise PluginManagerError(str(error)) from error
            revoked = self.store.set_plugin_trust(
                plugin_id,
                version=manifest.version,
                trust_status=decision.status,
                trust_decision=decision.model_dump(mode="json"),
            )
            receipt = self._receipt(
                plugin=revoked,
                operation="revoke-package",
                previous_state=str(plugin["status"]),
                current_state=str(revoked["status"]),
                accepted=True,
                issue_codes=[f"TRUST_STATUS:{decision.status}"],
            )
            return {**revoked, "receipt": receipt}

    def add_trusted_publisher(
        self, *, key_id: str, publisher: str, public_key_base64: str
    ) -> dict[str, object]:
        try:
            self.trust_store.add_publisher(
                key_id=key_id,
                publisher=publisher,
                public_key_base64=public_key_base64,
            )
        except TrustStoreError as error:
            raise PluginManagerError(str(error)) from error
        return {"key_id": key_id, "publisher": publisher, "trusted": True}

    def _configure(self, plugin_id: str, configuration: dict[str, object]) -> dict[str, object]:
        plugin = self.store.get_plugin(plugin_id)
        manifest = self._manifest(plugin)
        sensitive_fragments = {"api_key", "apikey", "authorization", "password", "secret"}

        def reject_inline_secrets(value: object, path: tuple[str, ...] = ()) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    normalized = str(key).casefold().replace("-", "_")
                    if any(fragment in normalized for fragment in sensitive_fragments):
                        raise PluginManagerError(
                            "PLUGIN_CONFIGURATION_INLINE_SECRET_FORBIDDEN:"
                            + ".".join((*path, str(key)))
                        )
                    reject_inline_secrets(item, (*path, str(key)))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    reject_inline_secrets(item, (*path, str(index)))

        reject_inline_secrets(configuration)
        schema = manifest.configuration_schema
        if schema:
            jsonschema.validate(configuration, schema)
        elif configuration:
            raise PluginManagerError("PLUGIN_HAS_NO_CONFIGURATION")
        self._mcp_sessions.invalidate(plugin_id)
        return self.store.save_plugin_configuration(plugin_id, configuration)

    def _validate_enabled_catalog(self, enabled_ids: set[str]) -> None:
        records = {str(item["plugin_id"]): item for item in self.store.list_plugins()}
        missing = sorted(enabled_ids - records.keys())
        if missing:
            raise PluginManagerError("PLUGIN_PROFILE_MEMBER_MISSING:" + ",".join(missing))
        manifests = {plugin_id: self._manifest(records[plugin_id]) for plugin_id in enabled_ids}
        for plugin_id, record in records.items():
            manifest = self._manifest(record)
            if not manifest.disable_allowed and plugin_id not in enabled_ids:
                raise PluginManagerError("PLUGIN_REQUIRED_BY_SAFETY_KERNEL")
        slot_members: dict[str, list[PluginManifest]] = {}
        for manifest in manifests.values():
            slot_members.setdefault(manifest.placement.slot_id, []).append(manifest)
        for slot_id, members in slot_members.items():
            if members[0].placement.activation_mode == "single" and len(members) != 1:
                raise PluginManagerError(f"PLUGIN_SINGLE_SLOT_CARDINALITY:{slot_id}")
        missing_required = sorted(
            slot_id
            for slot_id in self.required_single_slots
            if len(slot_members.get(slot_id, [])) != 1
        )
        if missing_required:
            raise PluginManagerError(
                "PLUGIN_REQUIRED_SLOT_CARDINALITY:" + ",".join(missing_required)
            )
        for plugin_id, manifest in manifests.items():
            for dependency in manifest.dependencies:
                if dependency.optional:
                    continue
                dependency_manifest = manifests.get(dependency.plugin_id)
                if dependency_manifest is None or not _version_matches(
                    dependency_manifest.version, dependency.version
                ):
                    raise PluginManagerError(
                        f"PLUGIN_DEPENDENCY_UNAVAILABLE:{plugin_id}:{dependency.plugin_id}"
                    )
            conflicts = sorted(set(manifest.conflicts) & enabled_ids)
            if conflicts:
                raise PluginManagerError(f"PLUGIN_CONFLICT:{plugin_id}:" + ",".join(conflicts))
        for slot_id, members in slot_members.items():
            if members[0].placement.activation_mode != "pipeline":
                continue
            by_id = {item.plugin_id: item for item in members}
            edges: dict[str, set[str]] = {plugin_id: set() for plugin_id in by_id}
            indegree: dict[str, int] = {plugin_id: 0 for plugin_id in by_id}
            for item in members:
                for predecessor in item.placement.runs_after:
                    if predecessor in by_id and item.plugin_id not in edges[predecessor]:
                        edges[predecessor].add(item.plugin_id)
                        indegree[item.plugin_id] += 1
                for successor in item.placement.runs_before:
                    if successor in by_id and successor not in edges[item.plugin_id]:
                        edges[item.plugin_id].add(successor)
                        indegree[successor] += 1
            ready = [plugin_id for plugin_id, degree in indegree.items() if degree == 0]
            visited = 0
            while ready:
                current = ready.pop()
                visited += 1
                for successor in edges[current]:
                    indegree[successor] -= 1
                    if indegree[successor] == 0:
                        ready.append(successor)
            if visited != len(by_id):
                raise PluginManagerError(f"PLUGIN_PIPELINE_CYCLE:{slot_id}")

    def apply_profile(self, profile_plugin_id: str) -> dict[str, object]:
        """Atomically select a curated persona bundle without touching active snapshots."""

        with self._mutation_lock:
            profile_record = self.store.get_plugin(profile_plugin_id)
            profile_manifest = self._manifest(profile_record)
            if profile_manifest.placement.slot_id != "harness.profile":
                raise PluginManagerError("PLUGIN_NOT_HARNESS_PROFILE")
            capability = next(
                (item for item in profile_manifest.capabilities if item.kind == "harness-profile"),
                None,
            )
            if capability is None:
                raise PluginManagerError("PLUGIN_PROFILE_CAPABILITY_MISSING")
            recommended_value = capability.metadata.get("recommended_plugins", [])
            managed_value = capability.metadata.get("managed_plugins", [])
            if (
                not isinstance(recommended_value, list)
                or not all(isinstance(item, str) for item in recommended_value)
                or not isinstance(managed_value, list)
                or not all(isinstance(item, str) for item in managed_value)
            ):
                raise PluginManagerError("PLUGIN_PROFILE_METADATA_INVALID")
            recommended = set(recommended_value)
            recommended.add(profile_plugin_id)
            managed = set(managed_value)
            records = {str(item["plugin_id"]): item for item in self.store.list_plugins()}
            missing = sorted((recommended | managed) - records.keys())
            if missing:
                raise PluginManagerError("PLUGIN_PROFILE_MEMBER_MISSING:" + ",".join(missing))
            desired_enabled = {
                plugin_id for plugin_id, record in records.items() if bool(record["enabled"])
            }
            for plugin_id in recommended:
                manifest = self._manifest(records[plugin_id])
                if manifest.placement.activation_mode == "single":
                    desired_enabled -= {
                        candidate_id
                        for candidate_id, candidate in records.items()
                        if self._manifest(candidate).placement.slot_id == manifest.placement.slot_id
                    }
                desired_enabled.add(plugin_id)
            desired_enabled -= managed - recommended
            self._validate_enabled_catalog(desired_enabled)
            for plugin_id in sorted(recommended):
                self.healthcheck(plugin_id)
            disabled_ids = sorted(
                plugin_id
                for plugin_id, record in records.items()
                if bool(record["enabled"]) and plugin_id not in desired_enabled
            )
            enabled_ids = sorted(
                plugin_id
                for plugin_id, record in records.items()
                if not bool(record["enabled"]) and plugin_id in desired_enabled
            )
            affected_threads: list[str] = []
            if disabled_ids:
                self.store.set_plugin_lifecycles(
                    {
                        plugin_id: {
                            "enabled": True,
                            "status": "draining",
                            "health": str(records[plugin_id]["health"]),
                        }
                        for plugin_id in disabled_ids
                    }
                )
            try:
                for plugin_id in disabled_ids:
                    manifest = self._manifest(records[plugin_id])
                    self._drain_calls(plugin_id)
                    if self._disable_guard:
                        affected_threads.extend(
                            self._disable_guard(plugin_id, manifest.placement.swap_policy)
                        )
            except (RuntimeError, PluginManagerError) as error:
                self.store.set_plugin_lifecycles(
                    {
                        plugin_id: {
                            "enabled": bool(records[plugin_id]["enabled"]),
                            "status": str(records[plugin_id]["status"]),
                            "health": str(records[plugin_id]["health"]),
                            "last_error": records[plugin_id].get("last_error"),
                        }
                        for plugin_id in disabled_ids
                    }
                )
                raise PluginManagerError(f"PLUGIN_PROFILE_DRAIN_FAILED:{error}") from error
            updates: dict[str, dict[str, object]] = {}
            for plugin_id in enabled_ids:
                updates[plugin_id] = {
                    "enabled": True,
                    "status": "healthy",
                    "health": "healthy",
                    "last_error": None,
                }
            for plugin_id in disabled_ids:
                updates[plugin_id] = {
                    "enabled": False,
                    "status": "disabled",
                    "health": "unknown",
                    "last_error": None,
                }
            before = {
                plugin_id: {
                    "enabled": bool(records[plugin_id]["enabled"]),
                    "status": str(records[plugin_id]["status"]),
                    "health": str(records[plugin_id]["health"]),
                    "last_error": records[plugin_id].get("last_error"),
                }
                for plugin_id in updates
            }
            try:
                self.store.set_plugin_lifecycles(updates)
                snapshot = self.snapshot()
            except BaseException:
                self.store.set_plugin_lifecycles(before)
                raise
            receipts = []
            for plugin_id in enabled_ids:
                receipts.append(
                    self._receipt(
                        plugin=self.store.get_plugin(plugin_id),
                        operation="enable",
                        previous_state=str(records[plugin_id]["status"]),
                        current_state="healthy",
                        accepted=True,
                    )
                )
            for plugin_id in disabled_ids:
                receipts.append(
                    self._receipt(
                        plugin=self.store.get_plugin(plugin_id),
                        operation="disable",
                        previous_state=str(records[plugin_id]["status"]),
                        current_state="disabled",
                        accepted=True,
                    )
                )
            return {
                "profile_plugin_id": profile_plugin_id,
                "enabled_plugins": enabled_ids,
                "disabled_plugins": disabled_ids,
                "affected_threads": sorted(set(affected_threads)),
                "snapshot_id": snapshot.snapshot_id,
                "catalog_sha256": snapshot.catalog_sha256,
                "receipts": receipts,
            }

    def model_catalog(self) -> list[dict[str, str]]:
        models: list[dict[str, str]] = []
        for plugin in self.store.list_plugins():
            if not plugin["enabled"] or plugin["health"] != "healthy":
                continue
            manifest = self._manifest(plugin)
            for capability in manifest.capabilities:
                if capability.kind != "model-provider":
                    continue
                values = capability.metadata.get("models", [])
                if not isinstance(values, list):
                    continue
                for value in values:
                    if not isinstance(value, dict):
                        continue
                    model_id = value.get("id")
                    label = value.get("label")
                    provider = value.get("provider")
                    if all(isinstance(item, str) and item for item in (model_id, label, provider)):
                        models.append(
                            {
                                "id": model_id,
                                "model": model_id,
                                "label": label,
                                "provider": provider,
                                "icon": provider,
                                "source": "default",
                            }  # type: ignore[dict-item]
                        )
        return sorted(models, key=lambda value: value["id"])

    def model_binding_for_model(self, model_id: str) -> tuple[str, str, str]:
        for plugin in self.store.list_plugins():
            if not plugin["enabled"] or plugin["health"] != "healthy":
                continue
            manifest = self._manifest(plugin)
            for capability in manifest.capabilities:
                if capability.kind != "model-provider":
                    continue
                models = capability.metadata.get("models", [])
                if not isinstance(models, list):
                    continue
                for model in models:
                    if not isinstance(model, dict) or model.get("id") != model_id:
                        continue
                    provider = model.get("provider")
                    if isinstance(provider, str) and provider:
                        return provider, manifest.plugin_id, capability.capability_id
        raise PluginManagerError("MODEL_PROVIDER_PLUGIN_UNAVAILABLE")

    def provider_for_model(self, model_id: str) -> str:
        provider, _plugin_id, _capability_id = self.model_binding_for_model(model_id)
        return provider

    def assert_snapshot_active(
        self, snapshot: PluginSnapshot, required_capability_ids: set[str]
    ) -> None:
        by_capability = {
            capability_id: entry
            for entry in snapshot.plugins
            for capability_id in entry.capability_ids
        }
        missing = required_capability_ids - set(by_capability)
        if missing:
            raise PluginManagerError(
                "PLUGIN_SNAPSHOT_CAPABILITY_MISSING:" + ",".join(sorted(missing))
            )
        for capability_id in required_capability_ids:
            entry = by_capability[capability_id]
            plugin = self.store.get_plugin(entry.plugin_id)
            manifest = self._manifest(plugin)
            if (
                not bool(plugin["enabled"])
                or plugin["status"] != "healthy"
                or plugin["version"] != entry.version
                or plugin["package_sha256"] != entry.package_sha256
                or self._manifest_hash(manifest) != entry.manifest_sha256
                or sha256_json(
                    self.store.get_plugin_configuration(entry.plugin_id)["configuration"]
                )
                != entry.configuration_sha256
            ):
                raise PluginManagerError(f"PLUGIN_SNAPSHOT_CAPABILITY_DRIFT:{capability_id}")

    def snapshot(self, *, thread_id: str | None = None) -> PluginSnapshot:
        entries: list[PluginSnapshotEntry] = []
        active_slot_counts: dict[str, int] = {}
        for plugin in self.store.list_plugins():
            if not plugin["enabled"] or plugin["status"] != "healthy":
                continue
            manifest = self._manifest(plugin)
            slot_id = manifest.placement.slot_id
            if manifest.placement.activation_mode == "single":
                active_slot_counts[slot_id] = active_slot_counts.get(slot_id, 0) + 1
            configuration = self.store.get_plugin_configuration(manifest.plugin_id)["configuration"]
            entries.append(
                PluginSnapshotEntry(
                    plugin_id=manifest.plugin_id,
                    version=manifest.version,
                    package_sha256=str(plugin["package_sha256"]),
                    manifest_sha256=self._manifest_hash(manifest),
                    configuration_sha256=sha256_json(configuration),
                    configuration=configuration,
                    capability_ids=[item.capability_id for item in manifest.capabilities],
                    manifest=manifest,
                    bundle_root=(str(plugin["bundle_root"]) if plugin["bundle_root"] else None),
                )
            )
        invalid_slots = sorted(
            slot_id
            for slot_id in self.required_single_slots
            if active_slot_counts.get(slot_id, 0) != 1
        )
        if invalid_slots:
            raise PluginManagerError("PLUGIN_REQUIRED_SLOT_CARDINALITY:" + ",".join(invalid_slots))
        entries.sort(key=lambda value: value.plugin_id)
        catalog_payload = [item.model_dump(mode="json") for item in entries]
        snapshot = PluginSnapshot(
            snapshot_id=f"plugin-snapshot-{uuid4().hex[:24]}",
            catalog_sha256=sha256_json(catalog_payload),
            plugins=entries,
            created_at=datetime.now(UTC),
        )
        if thread_id is not None:
            self.store.save_plugin_snapshot(thread_id, snapshot)
        return snapshot

    def build_tool_registry(
        self,
        *,
        environment: ToolEnvironment,
        snapshot: PluginSnapshot,
    ) -> ToolRegistry:
        registry = ToolRegistry(allowed_authorities={"read", "plan", "simulate"})
        for entry in snapshot.plugins:
            plugin = self.store.get_plugin(entry.plugin_id)
            if (
                str(plugin["version"]) != entry.version
                or str(plugin["package_sha256"]) != entry.package_sha256
            ):
                raise PluginManagerError(f"PLUGIN_SNAPSHOT_DRIFT:{entry.plugin_id}")
            manifest = self._manifest(plugin)
            if self._manifest_hash(manifest) != entry.manifest_sha256:
                raise PluginManagerError(f"PLUGIN_MANIFEST_DRIFT:{entry.plugin_id}")
            configuration = self.store.get_plugin_configuration(entry.plugin_id)["configuration"]
            if sha256_json(configuration) != entry.configuration_sha256:
                raise PluginManagerError(f"PLUGIN_CONFIGURATION_DRIFT:{entry.plugin_id}")
            if bool(plugin["builtin"]):
                definition: PluginDefinition | None = self._definitions.get(entry.plugin_id)
                if definition is None or definition.tool_factory is None:
                    continue
                configured_environment = replace(
                    environment,
                    plugin_configuration=dict(configuration),
                    capability_broker=(
                        environment.broker_factory.scope(manifest)
                        if environment.broker_factory is not None
                        else environment.capability_broker
                    ),
                )
                for tool in definition.tool_factory(configured_environment):
                    original_handler = tool.handler

                    def call_builtin(
                        value: Any,
                        *,
                        handler: Callable[[Any], Any] = original_handler,
                        plugin_id: str = entry.plugin_id,
                        plugin_version: str = entry.version,
                        capability_id: str = tool.tool_id,
                        slot_id: str = manifest.placement.slot_id,
                    ) -> Any:
                        started = time.perf_counter()
                        self._acquire_snapshot_call(plugin_id)
                        try:
                            output = handler(value)
                            self._record_usage(
                                plugin_id=plugin_id,
                                plugin_version=plugin_version,
                                capability_id=capability_id,
                                slot_id=slot_id,
                                invocation_kind="tool",
                                started=started,
                                input_value=value,
                                output_value=output,
                            )
                            return output
                        except BaseException as error:
                            self._record_usage(
                                plugin_id=plugin_id,
                                plugin_version=plugin_version,
                                capability_id=capability_id,
                                slot_id=slot_id,
                                invocation_kind="tool",
                                started=started,
                                input_value=value,
                                issue_code=type(error).__name__,
                            )
                            raise
                        finally:
                            self._release_call(plugin_id)

                    registry.register(
                        replace(
                            tool,
                            handler=call_builtin,
                            plugin_id=entry.plugin_id,
                            plugin_package_sha256=entry.package_sha256,
                            slot_id=manifest.placement.slot_id,
                        )
                    )
                continue
            if manifest.runtime.kind != "mcp-stdio":
                continue
            for capability in manifest.capabilities:
                if capability.kind not in PLUGIN_MCP_CAPABILITY_KINDS:
                    continue
                if "extension_hook" in capability.metadata:
                    continue
                tool_id = capability.capability_id

                def call_mcp(
                    value: dict[str, object],
                    *,
                    plugin_record: dict[str, object] = plugin,
                    plugin_manifest: PluginManifest = manifest,
                    capability_id: str = tool_id,
                    snapshot_entry: PluginSnapshotEntry = entry,
                    plugin_capability: PluginCapability = capability,
                ) -> dict[str, Any]:
                    current_plugin_id = str(plugin_record["plugin_id"])
                    started = time.perf_counter()
                    self._acquire_snapshot_call(current_plugin_id)
                    try:
                        plugin_root = Path(str(plugin_record["bundle_root"]))
                        self._verify_integrity(plugin_root, plugin_manifest)
                        client = self._mcp_client(
                            plugin_record,
                            plugin_manifest,
                            configuration=dict(snapshot_entry.configuration),
                            capability=plugin_capability,
                            broker_factory=environment.broker_factory,
                        )
                        jsonschema.validate(value, plugin_capability.input_schema)
                        output = client.call_tool(capability_id, value)
                        jsonschema.validate(output, plugin_capability.output_schema)
                        self._record_usage(
                            plugin_id=current_plugin_id,
                            plugin_version=snapshot_entry.version,
                            capability_id=capability_id,
                            slot_id=plugin_manifest.placement.slot_id,
                            invocation_kind="tool",
                            started=started,
                            input_value=value,
                            output_value=output,
                        )
                        return output
                    except (PluginProcessError, jsonschema.ValidationError) as error:
                        self._record_usage(
                            plugin_id=current_plugin_id,
                            plugin_version=snapshot_entry.version,
                            capability_id=capability_id,
                            slot_id=plugin_manifest.placement.slot_id,
                            invocation_kind="tool",
                            started=started,
                            input_value=value,
                            issue_code=type(error).__name__,
                        )
                        failed = self.store.set_plugin_lifecycle(
                            current_plugin_id,
                            enabled=False,
                            status="quarantined",
                            health="failed",
                            last_error=str(error)[:800],
                        )
                        self._receipt(
                            plugin=failed,
                            operation="quarantine",
                            previous_state="healthy",
                            current_state="quarantined",
                            accepted=True,
                            issue_codes=[str(error)[:96]],
                        )
                        raise
                    finally:
                        self._release_call(current_plugin_id)

                registry.register(
                    ToolPlugin(
                        tool_id=tool_id,
                        version=manifest.version,
                        authority=capability.authority,  # type: ignore[arg-type]
                        input_type=None,
                        output_type=None,
                        input_schema=capability.input_schema,
                        output_schema=capability.output_schema,
                        handler=call_mcp,
                        plugin_id=entry.plugin_id,
                        plugin_package_sha256=entry.package_sha256,
                        routing_metadata=capability.metadata,
                        slot_id=manifest.placement.slot_id,
                    )
                )
        available_slots = {str(item["slot_id"]) for item in registry.catalog() if item["slot_id"]}
        missing = self.required_tool_slots - available_slots
        if missing:
            missing_list = ",".join(sorted(missing))
            raise PluginManagerError(f"REQUIRED_PLUGIN_SLOT_MISSING:{missing_list}")
        return registry

    def build_extension_registry(
        self,
        *,
        snapshot: PluginSnapshot,
        broker_factory: CoreCapabilityBroker | None = None,
    ) -> ExtensionRegistry:
        """Build hash-bound first-party Harness hooks with lifecycle draining guards."""

        registry = ExtensionRegistry()
        for entry in snapshot.plugins:
            plugin = self.store.get_plugin(entry.plugin_id)
            if (
                str(plugin["version"]) != entry.version
                or str(plugin["package_sha256"]) != entry.package_sha256
            ):
                raise PluginManagerError(f"PLUGIN_SNAPSHOT_DRIFT:{entry.plugin_id}")
            manifest = self._manifest(plugin)
            if self._manifest_hash(manifest) != entry.manifest_sha256:
                raise PluginManagerError(f"PLUGIN_MANIFEST_DRIFT:{entry.plugin_id}")
            definition = self._definitions.get(entry.plugin_id)
            wrapped: dict[str, Callable[..., Any]] = {}
            capability: PluginCapability | None = None

            def wrap_hook(
                handler: Callable[..., Any],
                plugin_id: str,
                plugin_version: str,
                capability_id: str,
                slot_id: str,
                configuration: dict[str, object],
            ) -> Callable[..., Any]:
                parameters = inspect.signature(handler).parameters
                accepts_configuration = "configuration" in parameters or any(
                    item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()
                )

                def call_hook(**kwargs: Any) -> Any:
                    started = time.perf_counter()
                    self._acquire_snapshot_call(plugin_id)
                    try:
                        if accepts_configuration:
                            kwargs.setdefault("configuration", configuration)
                        output = handler(**kwargs)
                        self._record_usage(
                            plugin_id=plugin_id,
                            plugin_version=plugin_version,
                            capability_id=capability_id,
                            slot_id=slot_id,
                            invocation_kind="hook",
                            started=started,
                            input_value=kwargs,
                            output_value=output,
                        )
                        return output
                    except BaseException as error:
                        self._record_usage(
                            plugin_id=plugin_id,
                            plugin_version=plugin_version,
                            capability_id=capability_id,
                            slot_id=slot_id,
                            invocation_kind="hook",
                            started=started,
                            input_value=kwargs,
                            issue_code=type(error).__name__,
                        )
                        raise
                    finally:
                        self._release_call(plugin_id)

                return call_hook

            if definition is not None and definition.hooks:
                capability = manifest.capabilities[0]
                for hook_name, handler in definition.hooks.items():
                    wrapped[hook_name] = wrap_hook(
                        handler,
                        entry.plugin_id,
                        entry.version,
                        capability.capability_id,
                        manifest.placement.slot_id,
                        dict(entry.configuration),
                    )
            elif manifest.runtime.kind == "mcp-stdio":
                extension_capabilities = [
                    item
                    for item in manifest.capabilities
                    if item.metadata.get("extension_hook") in PLUGIN_EXTENSION_HOOKS
                ]
                if not extension_capabilities:
                    continue
                placement = manifest.placement
                for extension_capability in extension_capabilities:
                    hook_name = str(extension_capability.metadata["extension_hook"])

                    def call_mcp_extension(
                        *,
                        _plugin: dict[str, object] = plugin,
                        _manifest: PluginManifest = manifest,
                        _capability: PluginCapability = extension_capability,
                        _entry: PluginSnapshotEntry = entry,
                        **kwargs: Any,
                    ) -> Any:
                        current_plugin_id = _entry.plugin_id
                        started = time.perf_counter()
                        arguments: Any = kwargs
                        self._acquire_snapshot_call(current_plugin_id)
                        try:
                            plugin_root = Path(str(_plugin["bundle_root"]))
                            self._verify_integrity(plugin_root, _manifest)
                            client = self._mcp_client(
                                _plugin,
                                _manifest,
                                configuration=dict(_entry.configuration),
                                capability=_capability,
                                broker_factory=broker_factory,
                            )
                            arguments = _mcp_json_value(kwargs)
                            jsonschema.validate(arguments, _capability.input_schema)
                            output = client.call_tool(_capability.capability_id, arguments)
                            jsonschema.validate(output, _capability.output_schema)
                            self._record_usage(
                                plugin_id=current_plugin_id,
                                plugin_version=_entry.version,
                                capability_id=_capability.capability_id,
                                slot_id=_manifest.placement.slot_id,
                                invocation_kind="hook",
                                started=started,
                                input_value=arguments,
                                output_value=output,
                            )
                            if _manifest.placement.activation_mode == "pipeline":
                                if "value" not in output:
                                    raise PluginProcessError(
                                        "PLUGIN_EXTENSION_PIPELINE_VALUE_MISSING"
                                    )
                                return output["value"]
                            return output
                        except (PluginProcessError, jsonschema.ValidationError) as error:
                            self._record_usage(
                                plugin_id=current_plugin_id,
                                plugin_version=_entry.version,
                                capability_id=_capability.capability_id,
                                slot_id=_manifest.placement.slot_id,
                                invocation_kind="hook",
                                started=started,
                                input_value=arguments,
                                issue_code=type(error).__name__,
                            )
                            failed = self.store.set_plugin_lifecycle(
                                current_plugin_id,
                                enabled=False,
                                status="quarantined",
                                health="failed",
                                last_error=str(error)[:800],
                            )
                            self._receipt(
                                plugin=failed,
                                operation="quarantine",
                                previous_state="healthy",
                                current_state="quarantined",
                                accepted=True,
                                issue_codes=[str(error)[:96]],
                            )
                            raise
                        finally:
                            self._release_call(current_plugin_id)

                    registry.register(
                        ExtensionPlugin(
                            plugin_id=entry.plugin_id,
                            version=entry.version,
                            package_sha256=entry.package_sha256,
                            capability_id=extension_capability.capability_id,
                            slot_id=placement.slot_id,
                            activation_mode=placement.activation_mode,
                            failure_mode=placement.failure_mode,
                            swap_policy=placement.swap_policy,
                            pipeline_order=placement.pipeline_order,
                            runs_after=tuple(placement.runs_after),
                            runs_before=tuple(placement.runs_before),
                            hooks={hook_name: call_mcp_extension},
                        )
                    )
                continue
            else:
                continue
            if capability is None:
                continue
            placement = manifest.placement
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
                    hooks=wrapped,
                )
            )
        return registry

    def catalog_json(self) -> str:
        return canonical_json(self.list_plugins())
