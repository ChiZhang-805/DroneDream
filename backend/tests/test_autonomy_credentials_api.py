from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from tests.test_autonomy_qualification import map_pack_payload, vehicle_payload

INTENT = "Fly from the office to the coffee pickup point and return."


def _qualified_assets(
    client: TestClient,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    compact_vehicle = vehicle_payload()
    compact_vehicle["body_size_m"] = {"x": 0.30, "y": 0.30, "z": 0.18}
    compact_vehicle["rotor_radius_m"] = 0.08
    vehicle = client.post(
        "/api/v1/autonomy/vehicle-packs/qualify",
        headers=headers,
        json=compact_vehicle,
    ).json()["data"]
    map_pack = client.post(
        "/api/v1/autonomy/map-packs/qualify",
        headers=headers,
        json=map_pack_payload(),
    ).json()["data"]
    assert vehicle["status"] == "validated_unsigned"
    assert map_pack["status"] == "qualified"
    return vehicle, map_pack


def _harness_payload(
    vehicle: dict[str, object],
    map_pack: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "dronedream.autonomy.harness-inspect.v1",
        "edition": "universal",
        "natural_language": INTENT,
        "aircraft": {
            "kind": "aircraft",
            "asset_id": "lab-quad-01",
            "name": "Lab quad",
            "version": 3,
            "status": "validated-unsigned",
            "content_hash": vehicle["content_sha256"],
            "qualification_receipt_id": vehicle["receipt_id"],
            "capabilities": {
                "body_radius_m": vehicle["planning_radius_m"],
                "dry_mass_kg": 1.4,
                "maximum_takeoff_mass_kg": 2.4,
                "maximum_thrust_n": 48.0,
                "maximum_speed_mps": 4.0,
                "maximum_acceleration_mps2": 2.0,
                "maximum_pickup_payload_kg": 0.35,
                "reserve_battery_percent": 25.0,
                "localization_sources": ["vio"],
            },
        },
        "map_pack": {
            "kind": "map",
            "asset_id": "engineering-building",
            "name": "Engineering building",
            "version": 2,
            "status": "qualified",
            "content_hash": map_pack["content_sha256"],
            "qualification_receipt_id": map_pack["receipt_id"],
            "capabilities": {
                "representation": "hybrid-3d",
                "coordinate_frame": "ENU",
                "resolution_m": 0.1,
                "floor_count": 3,
                "bounds_x_m": 42.0,
                "bounds_y_m": 28.0,
                "bounds_z_m": 11.0,
                "confidence_percent": 100.0,
                "live_updates": "depth-fusion",
                "origin_latitude": None,
                "origin_longitude": None,
                "origin_altitude_m": None,
                "semantic_layers": [
                    "free-space",
                    "stairs",
                    "doors",
                    "people",
                    "pickup-zones",
                ],
                "planning_layers": [
                    "collision-geometry",
                    "occupancy",
                    "esdf",
                    "dynamic-overlay",
                    "confidence",
                ],
                "compiler_scene_id": "stairwell-coffee-return",
            },
        },
    }


def _compile_payload(
    harness: dict[str, object],
    context_sha256: str,
    vehicle: dict[str, object],
) -> dict[str, object]:
    return {
        "edition": "universal",
        "execution_target": "simulation",
        "natural_language": INTENT,
        "scene_id": "stairwell-coffee-return",
        "perception_mode": "fusion",
        "vehicle": {
            "dry_mass_kg": 1.4,
            "launch_payload_kg": 0.0,
            "pickup_payload_kg": 0.35,
            "max_takeoff_mass_kg": 2.4,
            "max_total_thrust_n": 48.0,
            "radius_m": vehicle["planning_radius_m"],
            "max_speed_mps": 4.0,
            "max_acceleration_mps2": 2.0,
            "reserve_battery_percent": 25.0,
        },
        "evidence": {
            "simulation_qualified": False,
            "signed_vehicle_pack_id": None,
            "operator_confirmed": False,
            "localization_ready": False,
            "link_ready": False,
            "geofence_ready": False,
            "battery_ready": False,
        },
        "asset_context": {
            "schema_version": "dronedream.autonomy.compile-assets.v1",
            "harness_context_sha256": context_sha256,
            "aircraft": harness["aircraft"],
            "map_pack": harness["map_pack"],
        },
    }


def test_owner_scoped_credentials_gate_harness_compile_and_runtime(client: TestClient) -> None:
    vehicle, map_pack = _qualified_assets(client)
    harness = _harness_payload(vehicle, map_pack)

    inspected = client.post("/api/v1/autonomy/harness/inspect", json=harness)
    assert inspected.status_code == 200
    inspection = inspected.json()["data"]
    assert inspection["planning_ready"] is True, inspection["blockers"]

    compile_payload = _compile_payload(harness, inspection["context_sha256"], vehicle)
    compiled = client.post("/api/v1/autonomy/compile", json=compile_payload)
    assert compiled.status_code == 200
    assert compiled.json()["data"]["feasible"] is True

    runtime = client.post(
        "/api/v1/autonomy/runtime/sessions",
        json={"mission": compile_payload, "client_request_id": "credential-runtime-001"},
    )
    assert runtime.status_code == 201


def test_compile_rejects_missing_or_forged_qualification_context(client: TestClient) -> None:
    vehicle, map_pack = _qualified_assets(client)
    harness = _harness_payload(vehicle, map_pack)
    inspection = client.post("/api/v1/autonomy/harness/inspect", json=harness).json()["data"]
    compile_payload = _compile_payload(harness, inspection["context_sha256"], vehicle)

    missing = {**compile_payload, "asset_context": None}
    missing_response = client.post("/api/v1/autonomy/compile", json=missing)
    assert missing_response.status_code == 403
    missing_error = missing_response.json()["error"]
    assert missing_error["code"] == "AUTONOMY_ASSET_GATE_REQUIRED", missing_response.json()

    forged = dict(compile_payload)
    forged_context = dict(compile_payload["asset_context"])
    forged_map = dict(forged_context["map_pack"])
    forged_map["content_hash"] = "f" * 64
    forged_context["map_pack"] = forged_map
    forged["asset_context"] = forged_context
    forged_response = client.post("/api/v1/autonomy/compile", json=forged)
    assert forged_response.status_code == 403
    assert (
        "map.qualification-receipt.content-mismatch"
        in forged_response.json()["error"]["details"]["blockers"]
    )


def test_same_version_is_idempotent_but_rejects_changed_content(client: TestClient) -> None:
    vehicle, first_map = _qualified_assets(client)
    old_harness = _harness_payload(vehicle, first_map)
    assert (
        client.post("/api/v1/autonomy/harness/inspect", json=old_harness).json()["data"][
            "planning_ready"
        ]
        is True
    )

    repeated = client.post(
        "/api/v1/autonomy/map-packs/qualify",
        json=map_pack_payload(),
    )
    assert repeated.status_code == 200
    assert repeated.json()["data"]["receipt_id"] == first_map["receipt_id"]

    changed = map_pack_payload()
    changed["origin"] = {
        "latitude": 22.304,
        "longitude": 114.179,
        "altitude_m": 18.5,
    }
    conflict = client.post(
        "/api/v1/autonomy/map-packs/qualify",
        json=changed,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "AUTONOMY_QUALIFICATION_VERSION_CONFLICT"

    unchanged = client.post("/api/v1/autonomy/harness/inspect", json=old_harness).json()["data"]
    assert unchanged["planning_ready"] is True


def test_new_asset_version_revokes_the_previous_version_receipt(client: TestClient) -> None:
    vehicle, first_map = _qualified_assets(client)
    old_harness = _harness_payload(vehicle, first_map)

    changed = map_pack_payload()
    changed["version"] = 3
    second_map = client.post(
        "/api/v1/autonomy/map-packs/qualify",
        json=changed,
    ).json()["data"]
    assert second_map["receipt_id"] != first_map["receipt_id"]

    stale = client.post("/api/v1/autonomy/harness/inspect", json=old_harness).json()["data"]
    assert stale["planning_ready"] is False
    assert "map.qualification-receipt.revoked" in stale["blockers"]

    obsolete = client.post(
        "/api/v1/autonomy/map-packs/qualify",
        json=map_pack_payload(),
    )
    assert obsolete.status_code == 409
    assert obsolete.json()["error"]["code"] == "AUTONOMY_QUALIFICATION_VERSION_CONFLICT"


def test_credentials_are_bound_to_the_authenticated_owner(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo_token")
    monkeypatch.setenv("DEMO_AUTH_TOKENS", "a@example.com:token-a,b@example.com:token-b")
    get_settings.cache_clear()
    owner_a = {"Authorization": "Bearer token-a"}
    owner_b = {"Authorization": "Bearer token-b"}
    vehicle, map_pack = _qualified_assets(client, owner_a)
    harness = _harness_payload(vehicle, map_pack)

    denied = client.post(
        "/api/v1/autonomy/harness/inspect",
        headers=owner_b,
        json=harness,
    )
    assert denied.status_code == 200
    inspection = denied.json()["data"]
    assert inspection["planning_ready"] is False
    assert "aircraft.qualification-receipt.invalid" in inspection["blockers"]
    assert "map.qualification-receipt.invalid" in inspection["blockers"]


def test_harness_requalifies_persisted_credential_payloads(client: TestClient) -> None:
    from app import db, models

    vehicle, map_pack = _qualified_assets(client)
    harness = _harness_payload(vehicle, map_pack)
    with db.SessionLocal() as session:
        credential = session.get(
            models.AutonomyQualificationCredential,
            vehicle["receipt_id"],
        )
        assert credential is not None
        credential.request_json = {
            **credential.request_json,
            "maximum_speed_mps": 3.5,
        }
        session.commit()

    inspected = client.post("/api/v1/autonomy/harness/inspect", json=harness).json()["data"]
    assert inspected["planning_ready"] is False
    assert "aircraft.qualification-receipt.integrity-mismatch" in inspected["blockers"]
