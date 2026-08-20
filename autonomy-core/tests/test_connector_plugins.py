from __future__ import annotations

from dataclasses import dataclass

import pytest

from dronedream_agent_core.capability_broker import BrokerHttpResponse
from dronedream_agent_plugins.connector_plugins import plugin_definitions


@dataclass
class _Environment:
    capability_broker: object
    plugin_configuration: dict[str, object] | None = None


class _RecordingBroker:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return BrokerHttpResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=__import__("json").dumps(self.payload).encode("utf-8"),
        )


def _definition(plugin_id: str):
    return next(item for item in plugin_definitions() if item.manifest.plugin_id == plugin_id)


def test_connector_catalog_is_opt_in_brokered_and_host_scoped():
    definitions = plugin_definitions()
    assert len(definitions) == 6
    for definition in definitions:
        manifest = definition.manifest
        assert manifest.default_enabled is False
        assert manifest.resource_policy.allowed_network_hosts
        assert "network.external" in manifest.permissions
        assert manifest.capabilities[0].metadata["live"] is True
        assert manifest.capabilities[0].metadata["brokered"] is True


def test_open_meteo_connector_normalizes_live_response_shape():
    broker = _RecordingBroker(
        {
            "latitude": 30.27,
            "longitude": 120.15,
            "timezone": "Asia/Shanghai",
            "current": {"wind_speed_10m": 4.2},
            "hourly": {"time": ["2026-08-19T20:00"]},
        }
    )
    definition = _definition("connector.weather.open-meteo")
    assert definition.tool_factory is not None
    tool = definition.tool_factory(_Environment(broker))[0]  # type: ignore[arg-type]
    result = tool.handler({"latitude": 30.27, "longitude": 120.15})
    assert result["source"] == "open-meteo"
    assert result["current"]["wind_speed_10m"] == 4.2
    assert broker.calls[0]["url"].startswith("https://api.open-meteo.com/v1/forecast?")


def test_overpass_connector_rejects_unbounded_queries_before_network():
    broker = _RecordingBroker({"elements": []})
    definition = _definition("connector.gis.overpass")
    assert definition.tool_factory is not None
    tool = definition.tool_factory(_Environment(broker))[0]  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="CONNECTOR_GIS_BOUNDS_INVALID_OR_TOO_LARGE"):
        tool.handler({"south": -10, "west": -10, "north": 10, "east": 10})
    assert broker.calls == []


def test_aftership_connector_uses_only_opaque_credential_reference():
    broker = _RecordingBroker(
        {
            "data": {
                "tracking": {
                    "tag": "InTransit",
                    "expected_delivery": "2026-08-21",
                    "checkpoints": [{"city": "Hangzhou"}],
                }
            }
        }
    )
    definition = _definition("connector.logistics.aftership")
    assert definition.tool_factory is not None
    tool = definition.tool_factory(
        _Environment(broker, {"credential_reference": "aftership-primary"})  # type: ignore[arg-type]
    )[0]
    result = tool.handler({"carrier": "dhl", "tracking_number": "ABC123"})
    assert result["status"] == "InTransit"
    call = broker.calls[0]
    assert call["credential_reference"] == "aftership-primary"
    assert "api_key" not in call
    assert "secret" not in str(call).lower()


def test_notion_connector_requires_configuration_before_registration():
    definition = _definition("connector.erp.notion")
    assert definition.tool_factory is not None
    with pytest.raises(RuntimeError, match="CONNECTOR_NOTION_DATABASE_ID_REQUIRED"):
        definition.tool_factory(_Environment(_RecordingBroker({})))  # type: ignore[arg-type]
