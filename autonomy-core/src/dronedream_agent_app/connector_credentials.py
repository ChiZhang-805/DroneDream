"""Opaque, plugin-scoped connector credentials backed by the OS user vault."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol
from uuid import uuid4

from dronedream_agent_core.capability_broker import CapabilityBrokerError, CredentialResolver

from .custom_models import CredentialVault, WindowsCredentialVault
from .storage import AppStore

_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9._-]{2,119}$")


class CredentialMetadataStore(Protocol):
    def list_connector_credentials(self) -> list[dict[str, object]]: ...
    def get_connector_credential(self, reference: str) -> dict[str, object]: ...
    def save_connector_credential(self, value: dict[str, object]) -> dict[str, object]: ...
    def delete_connector_credential(self, reference: str) -> None: ...


class ConnectorCredentialService(CredentialResolver):
    """Own connector secrets while exposing only revocable opaque references."""

    def __init__(
        self,
        store: AppStore,
        vault: CredentialVault | None = None,
    ) -> None:
        self.store = store
        self.vault = vault or WindowsCredentialVault(store.root / "credentials" / "connectors")

    def list(self) -> list[dict[str, object]]:
        return self.store.list_connector_credentials()

    def create(
        self,
        *,
        display_name: str,
        secret: str,
        allowed_plugin_ids: Iterable[str],
    ) -> dict[str, object]:
        name = display_name.strip()
        plugin_ids = sorted(set(allowed_plugin_ids))
        if not name or len(name) > 80:
            raise ValueError("CONNECTOR_CREDENTIAL_NAME_INVALID")
        if not secret or len(secret) > 16_384:
            raise ValueError("CONNECTOR_CREDENTIAL_SECRET_INVALID")
        if (
            not plugin_ids
            or len(plugin_ids) > 32
            or any(not _PLUGIN_ID.fullmatch(plugin_id) for plugin_id in plugin_ids)
        ):
            raise ValueError("CONNECTOR_CREDENTIAL_SCOPE_INVALID")
        installed = {str(item["plugin_id"]) for item in self.store.list_plugins()}
        if any(plugin_id not in installed for plugin_id in plugin_ids):
            raise ValueError("CONNECTOR_CREDENTIAL_PLUGIN_NOT_INSTALLED")
        reference = f"cred-{uuid4().hex[:24]}"
        try:
            self.vault.put(reference, secret)
            return self.store.save_connector_credential(
                {
                    "reference": reference,
                    "display_name": name,
                    "allowed_plugin_ids": plugin_ids,
                }
            )
        except BaseException:
            self.vault.delete(reference)
            raise

    def delete(self, reference: str) -> None:
        self.store.delete_connector_credential(reference)
        self.vault.delete(reference)

    def resolve(self, reference: str, *, plugin_id: str) -> str:
        try:
            metadata = self.store.get_connector_credential(reference)
        except KeyError as error:
            raise CapabilityBrokerError("BROKER_CREDENTIAL_UNAVAILABLE") from error
        allowed = metadata.get("allowed_plugin_ids", [])
        if not isinstance(allowed, list) or plugin_id not in allowed:
            raise CapabilityBrokerError("BROKER_CREDENTIAL_SCOPE_DENIED")
        try:
            return self.vault.get(reference)
        except KeyError as error:
            raise CapabilityBrokerError("BROKER_CREDENTIAL_UNAVAILABLE") from error
