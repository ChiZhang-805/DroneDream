from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.autonomy.asset_connectors import AutonomyAssetConnector, get_asset_connector_catalog


def test_catalog_covers_mainstream_modeling_and_simulation_sources() -> None:
    catalog = get_asset_connector_catalog()
    by_id = {item.connector_id: item for item in catalog.items}

    assert catalog.imported_code_execution is False
    assert catalog.normalized_format == "ddpkg-v1"
    assert {
        "dronedream.ddpkg",
        "gazebo.sdf",
        "ros2.urdf",
        "ros2.xacro",
        "blender.phobos",
        "solidworks.urdf",
        "autodesk.fusion",
        "onshape.translation",
        "freecad.robotics",
        "gis.gdal",
    } <= set(by_id)
    assert by_id["gazebo.sdf"].enabled is True
    assert by_id["blender.phobos"].execution_boundary == "isolated_local_companion"
    assert by_id["solidworks.urdf"].execution_boundary == "isolated_plugin"


def test_optional_connector_cannot_claim_core_parser_or_enabled_state() -> None:
    payload = {
        "connector_id": "example.native",
        "name": "Example",
        "source_application": "Example CAD",
        "source_formats": ["example"],
        "asset_kinds": ["vehicle"],
        "availability": "plugin_required",
        "execution_boundary": "declarative_parser",
        "enabled": False,
        "maximum_import_maturity": "visual_only",
    }
    with pytest.raises(ValidationError, match="only built-in connectors"):
        AutonomyAssetConnector.model_validate(payload)

    payload["execution_boundary"] = "isolated_plugin"
    payload["enabled"] = True
    with pytest.raises(ValidationError, match="healthy installed companion or plugin"):
        AutonomyAssetConnector.model_validate(payload)


def test_connector_endpoint_uses_standard_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/autonomy/asset-connectors")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["imported_code_execution"] is False
    assert any(item["connector_id"] == "blender.phobos" for item in body["data"]["items"])
