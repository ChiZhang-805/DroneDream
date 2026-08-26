from __future__ import annotations

import pytest

from dronedream_agent_app.connector_credentials import ConnectorCredentialService
from dronedream_agent_app.plugin_manager import PluginManager
from dronedream_agent_app.storage import AppStore
from dronedream_agent_core.capability_broker import CapabilityBrokerError


class MemoryVault:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def put(self, name: str, secret: str) -> None:
        self.values[name] = secret

    def get(self, name: str) -> str:
        return self.values[name]

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def test_connector_credential_is_opaque_and_plugin_scoped(tmp_path):
    store = AppStore(tmp_path)
    manager = PluginManager(store)
    vault = MemoryVault()
    service = ConnectorCredentialService(store, vault)

    value = service.create(
        display_name="PagerDuty production",
        secret="never-return-this-secret",
        allowed_plugin_ids=["connector.alerts.pagerduty"],
    )

    reference = str(value["reference"])
    assert reference.startswith("cred-")
    assert "never-return-this-secret" not in str(value)
    assert "never-return-this-secret" not in str(service.list())
    assert service.resolve(reference, plugin_id="connector.alerts.pagerduty") == (
        "never-return-this-secret"
    )
    with pytest.raises(CapabilityBrokerError, match="BROKER_CREDENTIAL_SCOPE_DENIED"):
        service.resolve(reference, plugin_id="connector.erp.notion")

    service.delete(reference)
    assert reference not in vault.values
    with pytest.raises(CapabilityBrokerError, match="BROKER_CREDENTIAL_UNAVAILABLE"):
        service.resolve(reference, plugin_id="connector.alerts.pagerduty")
    manager.close()


def test_connector_credential_rejects_uninstalled_scope(tmp_path):
    service = ConnectorCredentialService(AppStore(tmp_path), MemoryVault())
    with pytest.raises(ValueError, match="CONNECTOR_CREDENTIAL_PLUGIN_NOT_INSTALLED"):
        service.create(
            display_name="unknown",
            secret="secret",
            allowed_plugin_ids=["unknown.connector"],
        )
