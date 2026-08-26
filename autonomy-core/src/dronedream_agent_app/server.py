"""Authenticated loopback API hosted inside the packaged desktop sidecar."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import tempfile
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware

from dronedream_agent_core.plugin_contracts import (
    PluginGovernancePolicy,
    PluginMarketplaceSource,
)

from . import __version__
from .connector_credentials import ConnectorCredentialService
from .custom_models import CredentialVault, CustomModelService, ModelConnection
from .mission_service import MissionService, _validate_gateway
from .models import (
    ConnectorCredentialCreateRequest,
    CustomModelCreateRequest,
    CustomModelDiscoverRequest,
    MessageCreate,
    MissionExecuteRequest,
    MissionPrepareRequest,
    OperatorControlRequest,
    OperatorTakeoverGrantRequest,
    PluginConfigurationRequest,
    PluginMarketplaceInstallRequest,
    PluginRollbackRequest,
    RuntimeMessageRequest,
    SettingsPatch,
    ThreadCreate,
    ThreadPatch,
    TrustedPublisherRequest,
)
from .plugin_manager import PluginManager, PluginManagerError
from .plugin_marketplace import PluginMarketplaceError, PluginMarketplaceService
from .runtime_manager import RuntimeBridgeError, RuntimeManager
from .storage import AppStore, AssetImportError


def create_app(
    *,
    store: AppStore,
    token: str,
    resource_root: Path | None = None,
    custom_model_credential_vault: CredentialVault | None = None,
    connector_credential_vault: CredentialVault | None = None,
    plugin_isolator_path: Path | None = None,
) -> FastAPI:
    official_plugins_root = (
        resource_root / "official-plugins" if resource_root is not None else None
    )
    plugin_manager = PluginManager(
        store,
        official_plugins_root=official_plugins_root,
        plugin_isolator_path=plugin_isolator_path,
    )
    plugin_marketplace = PluginMarketplaceService(store, plugin_manager)
    custom_models = CustomModelService(store, custom_model_credential_vault)
    connector_credentials = ConnectorCredentialService(store, connector_credential_vault)
    mission_service = MissionService(store, plugin_manager, connector_credentials)
    runtime_manager = RuntimeManager(store, resource_root, plugin_manager)
    plugin_manager.set_disable_guard(runtime_manager.prepare_plugin_disable)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            plugin_manager.close()

    app = FastAPI(
        title="DroneDream Autonomy Core",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost", "http://tauri.localhost", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def authorize(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="LOCAL_SESSION_REQUIRED"
            )

    local = Depends(authorize)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ready", "version": __version__}

    @app.post("/shutdown", dependencies=[local], status_code=202)
    def shutdown() -> dict[str, object]:
        runtime_manager.shutdown()

        def exit_after_response() -> None:
            time.sleep(0.15)
            os._exit(0)

        threading.Thread(target=exit_after_response, daemon=True).start()
        return {"accepted": True}

    @app.get("/v1/bootstrap", dependencies=[local])
    def bootstrap() -> dict[str, object]:
        default_models = plugin_manager.model_catalog()
        return {
            "models": [*default_models, *custom_models.catalog()],
            "threads": store.list_threads(),
            "maps": store.list_assets("map"),
            "vehicles": store.list_assets("vehicle"),
            "plugins": plugin_manager.list_plugins(),
            "connector_credentials": connector_credentials.list(),
            "settings": store.get_settings(),
        }

    @app.get("/v1/connector-credentials", dependencies=[local])
    def list_connector_credentials() -> list[dict[str, object]]:
        return connector_credentials.list()

    @app.post("/v1/connector-credentials", dependencies=[local], status_code=201)
    def create_connector_credential(
        payload: ConnectorCredentialCreateRequest,
    ) -> dict[str, object]:
        try:
            return connector_credentials.create(**payload.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.delete("/v1/connector-credentials/{reference}", dependencies=[local])
    def delete_connector_credential(reference: str) -> dict[str, object]:
        try:
            connector_credentials.delete(reference)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="CONNECTOR_CREDENTIAL_NOT_FOUND") from error
        return {"deleted": True, "reference": reference}

    @app.post("/v1/threads", dependencies=[local], status_code=201)
    def create_thread(payload: ThreadCreate) -> dict[str, object]:
        return store.create_thread(payload.title, payload.selected_model)

    @app.get("/v1/threads/{thread_id}", dependencies=[local])
    def get_thread(thread_id: str) -> dict[str, object]:
        try:
            return store.get_thread(thread_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="THREAD_NOT_FOUND") from error

    @app.patch("/v1/threads/{thread_id}", dependencies=[local])
    def patch_thread(thread_id: str, payload: ThreadPatch) -> dict[str, object]:
        try:
            return store.patch_thread(thread_id, payload.model_dump(exclude_unset=True))
        except KeyError as error:
            raise HTTPException(status_code=404, detail="THREAD_NOT_FOUND") from error

    @app.post("/v1/threads/{thread_id}/messages", dependencies=[local], status_code=201)
    def append_message(thread_id: str, payload: MessageCreate) -> dict[str, object]:
        try:
            return store.append_message(
                thread_id,
                role=payload.role,
                kind=payload.kind,
                content=payload.content,
                metadata=payload.metadata,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="THREAD_NOT_FOUND") from error

    @app.post("/v1/threads/{thread_id}/attachments", dependencies=[local], status_code=201)
    async def upload_attachment(
        thread_id: str,
        attachment: Annotated[UploadFile, File()],
    ) -> dict[str, object]:
        descriptor, temporary_name = tempfile.mkstemp(prefix="dd-attachment-")
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            size = 0
            with temporary.open("wb") as output:
                while chunk := await attachment.read(1024 * 1024):
                    size += len(chunk)
                    if size > 25 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="ATTACHMENT_TOO_LARGE")
                    output.write(chunk)
            return store.save_attachment(
                thread_id,
                display_name=attachment.filename or "attachment",
                content_type=attachment.content_type or "application/octet-stream",
                source=temporary,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="THREAD_NOT_FOUND") from error
        finally:
            temporary.unlink(missing_ok=True)

    @app.post("/v1/assets/import", dependencies=[local], status_code=201)
    async def import_asset(
        kind: Annotated[str, Form()],
        bundle: Annotated[UploadFile, File()],
    ) -> dict[str, object]:
        if kind not in {"map", "vehicle"}:
            raise HTTPException(status_code=400, detail="ASSET_KIND_INVALID")
        suffix = Path(bundle.filename or "bundle.zip").suffix
        descriptor, temporary_name = tempfile.mkstemp(prefix="dd-autonomy-", suffix=suffix)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            size = 0
            with temporary.open("wb") as output:
                while chunk := await bundle.read(1024 * 1024):
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="UPLOAD_TOO_LARGE")
                    output.write(chunk)
            return plugin_manager.import_asset(kind=kind, archive=temporary)
        except (AssetImportError, PluginManagerError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        finally:
            temporary.unlink(missing_ok=True)

    @app.post("/v1/threads/{thread_id}/prepare", dependencies=[local])
    def prepare(thread_id: str, payload: MissionPrepareRequest) -> dict[str, object]:
        try:
            thread = store.get_thread(thread_id)
            if payload.model_id != thread["selected_model"]:
                raise ValueError("PREPARATION_MODEL_MISMATCH")
            if payload.model_grant.startswith("ddc_"):
                connection = custom_models.consume_grant(
                    payload.model_grant, thread_id, payload.model_id
                )
            else:
                if payload.gateway_base_url is None:
                    raise ValueError("MODEL_GATEWAY_REQUIRED")
                provider, _plugin_id, capability_id = plugin_manager.model_binding_for_model(
                    payload.model_id
                )
                connection = ModelConnection(
                    selection_id=payload.model_id,
                    provider=provider,
                    model_id=payload.model_id,
                    api_key=payload.model_grant,
                    base_url=_validate_gateway(str(payload.gateway_base_url)),
                    api_style="chat-completions",
                    capability_id=capability_id,
                    source="default",
                )
            role_connections: dict[str, ModelConnection] = {}
            for role_model in payload.role_models:
                if role_model.role_port in role_connections:
                    raise ValueError("DUPLICATE_ROLE_MODEL_PORT")
                if role_model.model_grant.startswith("ddc_"):
                    role_connection = custom_models.consume_grant(
                        role_model.model_grant, thread_id, role_model.model_id
                    )
                else:
                    if role_model.gateway_base_url is None:
                        raise ValueError("MODEL_GATEWAY_REQUIRED")
                    role_provider, _plugin_id, role_capability_id = (
                        plugin_manager.model_binding_for_model(role_model.model_id)
                    )
                    role_connection = ModelConnection(
                        selection_id=role_model.model_id,
                        provider=role_provider,
                        model_id=role_model.model_id,
                        api_key=role_model.model_grant,
                        base_url=_validate_gateway(str(role_model.gateway_base_url)),
                        api_style="chat-completions",
                        capability_id=role_capability_id,
                        source="default",
                    )
                role_connections[role_model.role_port] = role_connection
            store.append_message(thread_id, role="user", kind="text", content=payload.message)
            result = mission_service.prepare(
                thread_id=thread_id,
                message=payload.message,
                map_id=payload.map_id,
                vehicle_id=payload.vehicle_id,
                connection=connection,
                role_connections=role_connections,
                locale=payload.locale,
                start_entity=payload.start_entity,
                attachment_ids=payload.attachment_ids,
                input_channel=payload.input_channel,
                input_metadata=payload.input_metadata,
            )
            notifications = result.get("notifications")
            if not isinstance(notifications, list) or not notifications:
                notifications = [
                    {
                        "kind": "plan",
                        "content": (
                            f"Plan ready: {result['goal']}"
                            if payload.locale == "en-US"
                            else f"计划已生成：{result['goal']}"
                        ),
                        "metadata": {},
                    }
                ]
            for notification in notifications:
                if not isinstance(notification, dict):
                    continue
                content = notification.get("content")
                kind = notification.get("kind")
                if not isinstance(content, str) or kind not in {"plan", "status"}:
                    continue
                metadata = notification.get("metadata")
                store.append_message(
                    thread_id,
                    role="assistant",
                    kind=kind,
                    content=content,
                    metadata=(
                        {**result, **metadata}
                        if kind == "plan" and isinstance(metadata, dict)
                        else metadata
                        if isinstance(metadata, dict)
                        else {}
                    ),
                )
            store.set_thread_state(thread_id, "awaiting_confirmation")
            return result
        except KeyError as error:
            raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/custom-models/discover", dependencies=[local])
    def discover_custom_models(payload: CustomModelDiscoverRequest) -> dict[str, object]:
        try:
            return custom_models.discover(base_url=payload.base_url, api_key=payload.api_key)
        except Exception as error:
            raise HTTPException(
                status_code=422, detail=f"CUSTOM_MODEL_DISCOVERY_FAILED:{type(error).__name__}"
            ) from error

    @app.post("/v1/custom-models", dependencies=[local], status_code=201)
    def create_custom_model(payload: CustomModelCreateRequest) -> dict[str, object]:
        try:
            return custom_models.create(**payload.model_dump())
        except (KeyError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/custom-models/{profile_id}/test", dependencies=[local])
    def test_custom_model(profile_id: str) -> dict[str, object]:
        try:
            return custom_models.test(profile_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="CUSTOM_MODEL_NOT_FOUND") from error
        except Exception as error:
            raise HTTPException(
                status_code=422, detail=f"CUSTOM_MODEL_TEST_FAILED:{type(error).__name__}"
            ) from error

    @app.post("/v1/custom-models/{profile_id}/grants", dependencies=[local])
    def issue_custom_model_grant(profile_id: str, thread_id: str) -> dict[str, object]:
        try:
            store.get_thread(thread_id)
            return custom_models.issue_grant(profile_id, thread_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404, detail="CUSTOM_MODEL_OR_THREAD_NOT_FOUND"
            ) from error

    @app.delete("/v1/custom-models/{profile_id}", dependencies=[local])
    def delete_custom_model(profile_id: str) -> dict[str, object]:
        try:
            custom_models.delete(profile_id)
            return {"deleted": True, "profile_id": profile_id}
        except KeyError as error:
            raise HTTPException(status_code=404, detail="CUSTOM_MODEL_NOT_FOUND") from error

    @app.get("/v1/plugins", dependencies=[local])
    def plugins() -> list[dict[str, object]]:
        return plugin_manager.list_plugins()

    @app.get("/v1/plugin-governance", dependencies=[local])
    def plugin_governance() -> dict[str, object]:
        return {
            "policy": plugin_manager.governance_policy().model_dump(mode="json"),
            "decisions": store.list_plugin_governance_decisions(limit=200),
        }

    @app.put("/v1/plugin-governance", dependencies=[local])
    def replace_plugin_governance(policy: PluginGovernancePolicy) -> dict[str, object]:
        try:
            return plugin_manager.set_governance_policy(policy)
        except PluginManagerError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/plugin-usage", dependencies=[local])
    def plugin_usage(limit: int = 200) -> list[dict[str, object]]:
        return store.list_plugin_usage(limit=limit)

    @app.get("/v1/plugin-marketplace", dependencies=[local])
    def plugin_marketplace_catalog() -> dict[str, object]:
        return plugin_marketplace.catalog()

    @app.put("/v1/plugin-marketplace/sources", dependencies=[local])
    def replace_plugin_marketplace_sources(
        sources: list[PluginMarketplaceSource],
    ) -> list[dict[str, object]]:
        try:
            return plugin_marketplace.replace_sources(sources)
        except PluginMarketplaceError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/plugin-marketplace/install", dependencies=[local])
    def install_marketplace_plugin(
        payload: PluginMarketplaceInstallRequest,
    ) -> dict[str, object]:
        try:
            return plugin_marketplace.install(**payload.model_dump())
        except PluginMarketplaceError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except PluginManagerError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/plugins/{plugin_id}", dependencies=[local])
    def plugin(plugin_id: str) -> dict[str, object]:
        try:
            return plugin_manager.get_plugin(plugin_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="PLUGIN_NOT_FOUND") from error

    @app.get("/v1/plugins/{plugin_id}/panel", dependencies=[local])
    def plugin_panel(plugin_id: str, thread_id: str | None = None) -> dict[str, object]:
        try:
            data_sources: dict[str, object] = {"runtime": runtime_manager.status()}
            if thread_id:
                thread = store.get_thread(thread_id)
                mission_root = store.missions_root / thread_id
                evidence: list[dict[str, object]] = []
                if mission_root.is_dir():
                    for path in sorted(mission_root.glob("plan-*/*.json"), reverse=True)[:100]:
                        evidence.append(
                            {
                                "name": path.name,
                                "plan": path.parent.name,
                                "byte_size": path.stat().st_size,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            }
                        )
                data_sources.update(
                    {
                        "task": thread,
                        "evidence": {"items": evidence},
                    }
                )
            return plugin_manager.ui_panel_document(plugin_id, data_sources=data_sources)
        except (KeyError, PluginManagerError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/v1/plugins/import", dependencies=[local], status_code=201)
    async def import_plugin(bundle: Annotated[UploadFile, File()]) -> dict[str, object]:
        suffix = Path(bundle.filename or "plugin.zip").suffix
        descriptor, temporary_name = tempfile.mkstemp(prefix="dd-plugin-", suffix=suffix)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            size = 0
            with temporary.open("wb") as output:
                while chunk := await bundle.read(1024 * 1024):
                    size += len(chunk)
                    if size > 512 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="PLUGIN_UPLOAD_TOO_LARGE")
                    output.write(chunk)
            return plugin_manager.import_bundle(temporary)
        except PluginManagerError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        finally:
            temporary.unlink(missing_ok=True)

    def plugin_action(plugin_id: str, action: str) -> dict[str, object]:
        try:
            if action == "enable":
                return plugin_manager.enable(plugin_id)
            if action == "disable":
                return plugin_manager.disable(plugin_id)
            return plugin_manager.healthcheck(plugin_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="PLUGIN_NOT_FOUND") from error
        except PluginManagerError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/plugins/{plugin_id}/enable", dependencies=[local])
    def enable_plugin(plugin_id: str) -> dict[str, object]:
        return plugin_action(plugin_id, "enable")

    @app.post("/v1/plugins/{plugin_id}/trust-local-package", dependencies=[local])
    def trust_local_plugin_package(plugin_id: str) -> dict[str, object]:
        try:
            return plugin_manager.approve_local_package(plugin_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="PLUGIN_NOT_FOUND") from error
        except PluginManagerError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/v1/plugins/{plugin_id}/versions/{version}/trust-local-package",
        dependencies=[local],
    )
    def trust_local_plugin_version(plugin_id: str, version: str) -> dict[str, object]:
        try:
            return plugin_manager.approve_local_version(plugin_id, version)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="PLUGIN_VERSION_NOT_FOUND") from error
        except PluginManagerError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/plugins/{plugin_id}/revoke-package", dependencies=[local])
    def revoke_plugin_package(plugin_id: str) -> dict[str, object]:
        try:
            return plugin_manager.revoke_package(plugin_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="PLUGIN_NOT_FOUND") from error
        except PluginManagerError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/plugin-publishers", dependencies=[local], status_code=201)
    def add_plugin_publisher(payload: TrustedPublisherRequest) -> dict[str, object]:
        try:
            return plugin_manager.add_trusted_publisher(**payload.model_dump())
        except PluginManagerError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/plugins/{plugin_id}/disable", dependencies=[local])
    def disable_plugin(plugin_id: str) -> dict[str, object]:
        return plugin_action(plugin_id, "disable")

    @app.post("/v1/plugins/{plugin_id}/healthcheck", dependencies=[local])
    def healthcheck_plugin(plugin_id: str) -> dict[str, object]:
        return plugin_action(plugin_id, "healthcheck")

    @app.post("/v1/plugins/{plugin_id}/apply-profile", dependencies=[local])
    def apply_plugin_profile(plugin_id: str) -> dict[str, object]:
        try:
            return plugin_manager.apply_profile(plugin_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="PLUGIN_NOT_FOUND") from error
        except PluginManagerError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.patch("/v1/plugins/{plugin_id}/configuration", dependencies=[local])
    def configure_plugin(plugin_id: str, payload: PluginConfigurationRequest) -> dict[str, object]:
        try:
            return plugin_manager.configure(plugin_id, payload.configuration)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="PLUGIN_NOT_FOUND") from error
        except (PluginManagerError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/plugins/{plugin_id}/rollback", dependencies=[local])
    def rollback_plugin(plugin_id: str, payload: PluginRollbackRequest) -> dict[str, object]:
        try:
            return plugin_manager.rollback(plugin_id, payload.version)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="PLUGIN_VERSION_NOT_FOUND") from error
        except PluginManagerError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/plugins/{plugin_id}/activate", dependencies=[local])
    def activate_plugin_version(
        plugin_id: str, payload: PluginRollbackRequest
    ) -> dict[str, object]:
        try:
            return plugin_manager.activate_version(plugin_id, payload.version)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="PLUGIN_VERSION_NOT_FOUND") from error
        except PluginManagerError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/v1/plugins/{plugin_id}/promote", dependencies=[local])
    def promote_plugin_version(plugin_id: str, payload: PluginRollbackRequest) -> dict[str, object]:
        try:
            return plugin_manager.promote_version(plugin_id, payload.version)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="PLUGIN_VERSION_NOT_FOUND") from error
        except PluginManagerError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.delete("/v1/plugins/{plugin_id}", dependencies=[local])
    def uninstall_plugin(plugin_id: str) -> dict[str, object]:
        try:
            return plugin_manager.uninstall(plugin_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="PLUGIN_NOT_FOUND") from error
        except PluginManagerError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.patch("/v1/settings", dependencies=[local])
    def patch_settings(payload: SettingsPatch) -> dict[str, object]:
        return store.patch_settings(payload.model_dump(exclude_unset=True))

    @app.get("/v1/runtime/status", dependencies=[local])
    def runtime_status() -> dict[str, object]:
        return runtime_manager.status()

    @app.post("/v1/runtime/provision", dependencies=[local])
    def provision_runtime() -> dict[str, object]:
        try:
            return runtime_manager.provision()
        except RuntimeBridgeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/runtime/setup", dependencies=[local])
    def runtime_setup_progress() -> dict[str, object]:
        return runtime_manager.setup_progress()

    @app.post("/v1/runtime/setup", dependencies=[local], status_code=202)
    def start_runtime_setup() -> dict[str, object]:
        return runtime_manager.start_setup()

    @app.post("/v1/threads/{thread_id}/execute", dependencies=[local], status_code=202)
    def execute_mission(thread_id: str, payload: MissionExecuteRequest) -> dict[str, object]:
        try:
            if payload.model_grant.startswith("ddc_"):
                connection = custom_models.consume_grant(
                    payload.model_grant, thread_id, payload.model_id
                )
            else:
                if payload.gateway_base_url is None:
                    raise ValueError("MODEL_GATEWAY_REQUIRED")
                provider, _plugin_id, capability_id = plugin_manager.model_binding_for_model(
                    payload.model_id
                )
                connection = ModelConnection(
                    selection_id=payload.model_id,
                    provider=provider,
                    model_id=payload.model_id,
                    api_key=payload.model_grant,
                    base_url=_validate_gateway(str(payload.gateway_base_url)),
                    api_style="chat-completions",
                    capability_id=capability_id,
                    source="default",
                )
            return runtime_manager.execute(
                thread_id=thread_id,
                connection=connection,
            )
        except (KeyError, ValueError, RuntimeBridgeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/v1/threads/{thread_id}/live-sources", dependencies=[local])
    def live_sources(thread_id: str) -> dict[str, object]:
        return runtime_manager.live_sources(thread_id)

    @app.get("/v1/threads/{thread_id}/live-frame", dependencies=[local])
    def live_frame(thread_id: str) -> Response:
        path = runtime_manager.live_frame(thread_id)
        if path is None:
            raise HTTPException(status_code=404, detail="LIVE_FRAME_NOT_READY")
        try:
            body = path.read_bytes()
        except OSError as error:
            raise HTTPException(status_code=404, detail="LIVE_FRAME_NOT_READY") from error
        return Response(
            content=body,
            media_type="image/png",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.get("/v1/threads/{thread_id}/live-telemetry", dependencies=[local])
    def live_telemetry(thread_id: str) -> dict[str, object]:
        value = runtime_manager.live_telemetry(thread_id)
        if value is None:
            raise HTTPException(status_code=404, detail="LIVE_TELEMETRY_NOT_READY")
        return value

    @app.post("/v1/threads/{thread_id}/runtime-message", dependencies=[local], status_code=202)
    def runtime_message(thread_id: str, payload: RuntimeMessageRequest) -> dict[str, object]:
        try:
            return runtime_manager.submit_message(thread_id, payload.text)
        except (KeyError, RuntimeBridgeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/v1/threads/{thread_id}/operator-takeover-grant",
        dependencies=[local],
        status_code=201,
    )
    def operator_takeover_grant(
        thread_id: str, payload: OperatorTakeoverGrantRequest
    ) -> dict[str, object]:
        try:
            return runtime_manager.issue_takeover_grant(
                thread_id,
                message_id=payload.message_id,
                operator_id=payload.operator_id,
                duration_seconds=payload.duration_seconds,
            )
        except (KeyError, RuntimeBridgeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/v1/threads/{thread_id}/operator-control",
        dependencies=[local],
        status_code=202,
    )
    def operator_control(thread_id: str, payload: OperatorControlRequest) -> dict[str, object]:
        try:
            return runtime_manager.submit_operator_control(
                thread_id,
                message_id=payload.message_id,
                grant_token=payload.grant_token,
                action=payload.action,
                north_mps=payload.north_mps,
                east_mps=payload.east_mps,
                down_mps=payload.down_mps,
                yaw_rate_dps=payload.yaw_rate_dps,
                duration_seconds=payload.duration_seconds,
            )
        except (KeyError, RuntimeBridgeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    return app


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--resource-root", type=Path)
    parser.add_argument("--plugin-isolator", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.host != "127.0.0.1" or len(args.token) < 32:
        raise SystemExit(64)
    os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
    store = AppStore(args.data_root)
    if args.resource_root is not None:
        store.seed_bundled_assets(args.resource_root / "default-assets")
    uvicorn.run(
        create_app(
            store=store,
            token=args.token,
            resource_root=args.resource_root,
            plugin_isolator_path=args.plugin_isolator,
        ),
        host=args.host,
        port=args.port,
        access_log=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
