"""Bridge the desktop application to the real multi-call mission orchestrator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from dronedream_agent_core.assets import load_school_map_catalog
from dronedream_agent_core.capability_broker import (
    CoreCapabilityBroker,
    CredentialResolver,
)
from dronedream_agent_core.context import ContextStore
from dronedream_agent_core.contracts import (
    AttachmentArtifact,
    MapAsset,
    MissionRequest,
    VehicleAsset,
)
from dronedream_agent_core.model_port import ProviderSettings, StructuredModelPort
from dronedream_agent_core.orchestrator import MissionOrchestrator, PreparationConfig
from dronedream_agent_core.plugin_api import ToolEnvironment
from dronedream_agent_core.plugin_contracts import CapabilityBrokerReceipt, PluginHookReceipt

from .custom_models import ModelConnection
from .plugin_manager import PluginManager
from .storage import AppStore


def _validate_gateway(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or not parsed.hostname
        or not parsed.hostname.endswith(".supabase.co")
        or not parsed.path.rstrip("/").endswith("/functions/v1/model-gateway")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("INVALID_MODEL_GATEWAY")
    return value.rstrip("/")


class MissionService:
    def __init__(
        self,
        store: AppStore,
        plugin_manager: PluginManager,
        credential_resolver: CredentialResolver | None = None,
    ) -> None:
        self.store = store
        self.plugin_manager = plugin_manager
        self.credential_resolver = credential_resolver

    def _decode_attachments(
        self,
        *,
        thread_id: str,
        attachment_ids: list[str],
        extension_registry,
    ) -> tuple[list[AttachmentArtifact], list[PluginHookReceipt]]:
        artifacts: list[AttachmentArtifact] = []
        all_receipts: list[PluginHookReceipt] = []
        for attachment_id in attachment_ids:
            record = self.store.get_attachment(attachment_id, thread_id)
            source = Path(str(record["local_path"])).resolve()
            source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
            outputs, receipts = extension_registry.invoke_multiple(
                "input.attachment-decoders",
                "decode_attachment",
                path=str(source),
                attachment_id=attachment_id,
                display_name=str(record["display_name"]),
                content_type=str(record["content_type"]),
                size_bytes=int(record["byte_size"]),
                source_sha256=source_sha256,
            )
            all_receipts.extend(receipts)
            candidates = [
                (output, receipt)
                for output, receipt in zip(outputs, receipts, strict=True)
                if isinstance(output, dict) and output.get("accepted") is True
            ]
            if not candidates:
                raise ValueError(f"ATTACHMENT_DECODER_NOT_FOUND:{attachment_id}")
            decoded, receipt = max(
                candidates,
                key=lambda item: int(item[0].get("priority", 0)),
            )
            artifacts.append(
                AttachmentArtifact(
                    attachment_id=attachment_id,
                    display_name=str(record["display_name"]),
                    content_type=str(record["content_type"]),
                    size_bytes=int(record["byte_size"]),
                    source_sha256=source_sha256,
                    decoder_plugin_id=receipt.plugin_id,
                    decoded_kind=str(decoded["decoded_kind"]),  # type: ignore[arg-type]
                    text=(str(decoded["text"]) if decoded.get("text") is not None else None),
                    structured_data=(
                        dict(decoded["structured_data"])
                        if isinstance(decoded.get("structured_data"), dict)
                        else {}
                    ),
                    model_input=(
                        dict(decoded["model_input"])
                        if isinstance(decoded.get("model_input"), dict)
                        else {}
                    ),
                    issue_codes=[str(item) for item in decoded.get("issue_codes", [])],
                )
            )
        return artifacts, all_receipts

    def prepare(
        self,
        *,
        thread_id: str,
        message: str,
        map_id: str,
        vehicle_id: str,
        connection: ModelConnection,
        role_connections: dict[str, ModelConnection] | None = None,
        locale: str,
        start_entity: str,
        attachment_ids: list[str],
        input_channel: str = "text",
        input_metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        app_settings = self.store.get_settings()
        memory_enabled = bool(app_settings.get("memory_enabled", True))
        persisted_task_context = memory_enabled and bool(
            app_settings.get("remember_task_preferences", True)
        )
        effective_input_metadata = dict(input_metadata or {})
        effective_input_metadata["memory_policy"] = {
            "persisted_task_context": persisted_task_context,
            "remember_asset_choices": memory_enabled
            and bool(app_settings.get("remember_asset_choices", True)),
            "safety_boundaries_are_non_relaxable": True,
        }
        map_asset = self.store.get_asset(map_id, "map")
        vehicle_asset = self.store.get_asset(vehicle_id, "vehicle")
        if map_asset["status"] != "qualified":
            raise ValueError("MAP_NOT_QUALIFIED")
        if vehicle_asset["status"] != "qualified":
            raise ValueError("VEHICLE_NOT_QUALIFIED")
        provider = connection.provider
        map_manifest = map_asset["manifest"]
        vehicle_manifest = vehicle_asset["manifest"]
        assert isinstance(map_manifest, dict) and isinstance(vehicle_manifest, dict)
        map_files = map_manifest["files"]
        vehicle_files = vehicle_manifest["files"]
        assert isinstance(map_files, dict) and isinstance(vehicle_files, dict)
        map_root = Path(str(map_asset["bundle_root"]))
        vehicle_root = Path(str(vehicle_asset["bundle_root"]))
        graph_path = map_root / str(map_files["graph"])
        semantic_path = map_root / str(map_files["semantic"])
        vehicle_sdf = vehicle_root / str(vehicle_files["vehicle_sdf"])
        graph = MapAsset.model_validate_json(graph_path.read_text(encoding="utf-8"))
        vehicle = VehicleAsset.model_validate_json(
            (vehicle_root / str(vehicle_files["vehicle_metadata"])).read_text(encoding="utf-8")
        )
        catalog = load_school_map_catalog(semantic_path)
        mission_root = self.store.missions_root / thread_id
        mission_root.mkdir(parents=True, exist_ok=True)
        revision = len(list(mission_root.glob("plan-*"))) + 1
        output_dir = mission_root / f"plan-{revision:04d}"
        attachment_root = self.store.attachments_root / thread_id
        attachment_root.mkdir(parents=True, exist_ok=True)
        broker_receipts: list[CapabilityBrokerReceipt] = []
        broker_factory = CoreCapabilityBroker(
            read_roots={
                "map": map_root,
                "vehicle": vehicle_root,
                "attachments": attachment_root,
            },
            write_roots={
                "output": output_dir,
                "staging": self.store.plugin_staging_root / thread_id / f"plan-{revision:04d}",
            },
            credential_resolver=self.credential_resolver,
            receipt_sink=broker_receipts.append,
        )
        plugin_snapshot = self.plugin_manager.snapshot(thread_id=thread_id)
        _policy_entry, _policy_manifest, policy_capability = (
            self.plugin_manager.capability_for_slot(plugin_snapshot, "planning.workflow-policy")
        )
        policy = policy_capability.metadata
        _retry_entry, _retry_manifest, retry_capability = self.plugin_manager.capability_for_slot(
            plugin_snapshot, "harness.retry-policy"
        )
        _timeout_entry, _timeout_manifest, timeout_capability = (
            self.plugin_manager.capability_for_slot(plugin_snapshot, "harness.timeout-policy")
        )
        _budget_entry, _budget_manifest, budget_capability = (
            self.plugin_manager.capability_for_slot(plugin_snapshot, "harness.budget-policy")
        )
        retry_policy = retry_capability.metadata
        timeout_policy = timeout_capability.metadata
        budget_policy = budget_capability.metadata
        tool_registry = self.plugin_manager.build_tool_registry(
            environment=ToolEnvironment(
                map_graph=graph,
                semantic_path=semantic_path,
                vehicle_diameter_m=vehicle.body_radius_m * 2,
                vehicle_height_m=vehicle.body_height_m,
                waypoint_hold_seconds=0.4,
                broker_factory=broker_factory,
            ),
            snapshot=plugin_snapshot,
        )
        extension_registry = self.plugin_manager.build_extension_registry(
            snapshot=plugin_snapshot,
            broker_factory=broker_factory,
        )
        attachments, attachment_receipts = self._decode_attachments(
            thread_id=thread_id,
            attachment_ids=attachment_ids,
            extension_registry=extension_registry,
        )
        context = ContextStore(self.store.root / "mission-context.sqlite3")

        def build_port(model_connection: ModelConnection) -> StructuredModelPort:
            settings = ProviderSettings(
                name=model_connection.provider,
                model=model_connection.model_id,
                api_key_env="DRONEDREAM_MODEL_CREDENTIAL",
                base_url=model_connection.base_url,
                api_style=model_connection.api_style,
            )
            return StructuredModelPort(
                model_connection.provider,
                max_attempts=int(retry_policy.get("provider_attempts", 3)),
                timeout_seconds=float(timeout_policy.get("model_seconds", 180.0)),
                settings=settings,
                api_key=model_connection.api_key,
            )

        primary = build_port(connection)
        critic = build_port((role_connections or {}).get("critic", connection))
        model_ports = {"primary": primary, "critic": critic}
        for role_port, role_connection in (role_connections or {}).items():
            model_ports[role_port] = build_port(role_connection)
        try:
            orchestrator = MissionOrchestrator(
                config=PreparationConfig(
                    provider=provider,  # type: ignore[arg-type]
                    critic_provider=provider,  # type: ignore[arg-type]
                    vehicle_diameter_m=vehicle.body_radius_m * 2,
                    vehicle_height_m=vehicle.body_height_m,
                    max_intent_rounds=int(policy.get("max_intent_rounds", 3)),
                    max_planning_rounds=int(policy.get("max_planning_rounds", 5)),
                    plugin_router_rounds=int(policy.get("plugin_router_rounds", 2)),
                    maximum_plugin_calls=int(policy.get("maximum_plugin_calls", 8)),
                    intent_reviews_per_round=int(policy.get("intent_reviews_per_round", 1)),
                    plan_reviews_per_round=int(policy.get("plan_reviews_per_round", 1)),
                    maximum_model_calls=int(budget_policy.get("maximum_model_calls", 48)),
                    maximum_optional_tool_calls=int(budget_policy.get("maximum_tool_calls", 16)),
                    model_timeout_seconds=float(timeout_policy.get("model_seconds", 180.0)),
                    persisted_task_context=persisted_task_context,
                ),
                map_catalog=catalog,
                map_graph=graph,
                semantic_path=semantic_path,
                vehicle_sdf=vehicle_sdf,
                vehicle_asset_id=vehicle.asset_id,
                vehicle=vehicle,
                context_store=context,
                primary_port=primary,
                critic_port=critic,
                model_ports=model_ports,
                tool_registry=tool_registry,
                extension_registry=extension_registry,
                plugin_snapshot=plugin_snapshot,
                initial_hook_receipts=attachment_receipts,
            )
            prepared = orchestrator.prepare(
                MissionRequest(
                    conversation_id=thread_id,
                    message=message,
                    start_entity=start_entity,
                    locale=locale,  # type: ignore[arg-type]
                    attachments=attachments,
                    input_channel=input_channel,  # type: ignore[arg-type]
                    input_metadata=effective_input_metadata,
                ),
                output_dir,
            )
            binding = context.lifecycle.binding(thread_id)
        finally:
            context.close()
        broker_receipt_path = output_dir / "capability-broker-receipts.json"
        broker_receipt_payload = [item.model_dump(mode="json") for item in broker_receipts]
        broker_receipt_path.write_text(
            json.dumps(broker_receipt_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summary = {
            "locale": locale,
            "thread_id": thread_id,
            "mission_id": binding.thread.mission_id,
            "plan_revision_id": binding.plan_revision.plan_revision_id,
            "status": prepared.status,
            "contract_id": prepared.contract.contract_id,
            "goal": prepared.intent.goal,
            "target_entity": prepared.intent.target_entity,
            "return_entity": prepared.intent.return_entity,
            "planning_attempts": prepared.planning_attempts,
            "model_calls": len(prepared.model_calls),
            "model_selection_id": connection.selection_id,
            "model_id": connection.model_id,
            "model_source": connection.source,
            "role_models": {
                role_port: {
                    "selection_id": role_connection.selection_id,
                    "model_id": role_connection.model_id,
                    "provider": role_connection.provider,
                    "source": role_connection.source,
                }
                for role_port, role_connection in (role_connections or {}).items()
            },
            "plugin_snapshot_id": prepared.plugin_snapshot.snapshot_id,
            "plugin_catalog_sha256": prepared.plugin_snapshot.catalog_sha256,
            "route_nodes": prepared.execution_route.node_ids,
            "minimum_clearance_m": prepared.route_clearance.minimum_clearance_m,
            "output_dir": str(output_dir),
            "capability_broker_receipts": len(broker_receipts),
            "capability_broker_receipts_sha256": hashlib.sha256(
                broker_receipt_path.read_bytes()
            ).hexdigest(),
        }
        notification_outputs, notification_receipts = extension_registry.invoke_multiple(
            "notifications.plan-ready",
            "render_plan_notification",
            summary=summary,
            prepared=prepared,
        )
        notifications = [
            output
            for output in notification_outputs
            if isinstance(output, dict)
            and output.get("channel") == "task-timeline"
            and output.get("kind") in {"plan", "status"}
            and isinstance(output.get("content"), str)
        ]
        summary["notifications"] = notifications
        summary["notification_plugin_receipts"] = [
            receipt.model_dump(mode="json") for receipt in notification_receipts
        ]
        (output_dir / "desktop-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return summary
