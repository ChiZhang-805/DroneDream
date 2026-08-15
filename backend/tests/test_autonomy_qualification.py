from __future__ import annotations

import asyncio
import json
import struct

from app.autonomy.qualification import (
    MapAssetAdmissionRegistry,
    VehiclePackQualificationRequest,
    qualify_vehicle_pack,
)


def vehicle_payload() -> dict[str, object]:
    return {
        "pack_id": "lab-quad-01",
        "version": 3,
        "autopilot": "px4",
        "firmware": "PX4 v1.16",
        "flight_controller": "Pixhawk 6X",
        "control_interface": "px4-ros2",
        "dry_mass_kg": 1.4,
        "max_takeoff_mass_kg": 2.4,
        "max_total_thrust_n": 48.0,
        "body_size_m": {"x": 0.52, "y": 0.52, "z": 0.22},
        "rotor_radius_m": 0.13,
        "center_of_gravity_m": {"x": 0.0, "y": 0.0, "z": -0.02},
        "inertia_kg_m2": {"x": 0.03, "y": 0.03, "z": 0.05},
        "battery_energy_wh": 110.0,
        "reserve_battery_percent": 25.0,
        "maximum_pickup_payload_kg": 0.35,
        "maximum_speed_mps": 4.0,
        "maximum_acceleration_mps2": 2.0,
        "maximum_climb_mps": 1.5,
        "maximum_descent_mps": 1.0,
        "command_link_latency_ms": 35.0,
        "command_link_bandwidth_mbps": 20.0,
        "sensors": [
            {
                "sensor_id": "vio-front",
                "kind": "vio",
                "calibrated": True,
                "calibration_status": "verified",
                "position_m": {"x": 0.12, "y": 0.0, "z": -0.03},
                "roll_pitch_yaw_deg": {"x": 0.0, "y": -8.0, "z": 0.0},
                "rate_hz": 30.0,
                "calibration_age_days": 3.0,
            }
        ],
    }


def test_vehicle_pack_qualification_is_versioned_and_unsigned() -> None:
    request = VehiclePackQualificationRequest.model_validate(vehicle_payload())
    receipt = qualify_vehicle_pack(request)

    assert receipt.status == "validated_unsigned"
    assert receipt.version == 3
    assert receipt.hardware_authority is False
    assert receipt.loaded_thrust_to_weight > 1.35
    assert len(receipt.content_sha256) == 64


def test_vehicle_pack_receipt_binds_the_autopilot_family() -> None:
    px4_payload = vehicle_payload()
    px4_payload["control_interface"] = "mavlink"
    px4_receipt = qualify_vehicle_pack(VehiclePackQualificationRequest.model_validate(px4_payload))

    ardupilot_payload = {**px4_payload, "autopilot": "ardupilot"}
    ardupilot_receipt = qualify_vehicle_pack(
        VehiclePackQualificationRequest.model_validate(ardupilot_payload)
    )

    assert px4_receipt.content_sha256 != ardupilot_receipt.content_sha256
    assert px4_receipt.receipt_id != ardupilot_receipt.receipt_id


def test_vehicle_pack_receipt_binds_the_full_calibration_state() -> None:
    unverified_payload = vehicle_payload()
    unverified_sensors = unverified_payload["sensors"]
    assert isinstance(unverified_sensors, list)
    rgb_sensor = {
        "sensor_id": "rgb-front",
        "kind": "rgb",
        "calibrated": False,
        "calibration_status": "unverified",
        "position_m": {"x": 0.14, "y": 0.0, "z": -0.02},
        "roll_pitch_yaw_deg": {"x": 0.0, "y": -6.0, "z": 0.0},
        "rate_hz": 30.0,
        "calibration_age_days": 0.0,
    }
    unverified_payload["sensors"] = [*unverified_sensors, rgb_sensor]
    unverified_receipt = qualify_vehicle_pack(
        VehiclePackQualificationRequest.model_validate(unverified_payload)
    )

    failed_payload = vehicle_payload()
    failed_sensors = failed_payload["sensors"]
    assert isinstance(failed_sensors, list)
    failed_payload["sensors"] = [
        *failed_sensors,
        {**rgb_sensor, "calibration_status": "failed"},
    ]
    failed_receipt = qualify_vehicle_pack(
        VehiclePackQualificationRequest.model_validate(failed_payload)
    )

    assert unverified_receipt.content_sha256 != failed_receipt.content_sha256
    assert unverified_receipt.receipt_id != failed_receipt.receipt_id


def test_vehicle_pack_qualification_migrates_legacy_v1_requests() -> None:
    legacy_payload = vehicle_payload()
    legacy_payload.pop("autopilot")
    legacy_sensors = legacy_payload["sensors"]
    assert isinstance(legacy_sensors, list)
    for sensor in legacy_sensors:
        assert isinstance(sensor, dict)
        sensor.pop("calibration_status")

    request = VehiclePackQualificationRequest.model_validate(legacy_payload)
    receipt = qualify_vehicle_pack(request)

    assert request.autopilot == "px4"
    assert request.sensors[0].calibration_status == "verified"
    assert receipt.status == "validated_unsigned"


def test_vehicle_pack_blocks_an_unqualified_localization_stack() -> None:
    payload = vehicle_payload()
    payload["sensors"] = []
    receipt = qualify_vehicle_pack(VehiclePackQualificationRequest.model_validate(payload))

    assert receipt.status == "blocked"
    assert {issue.code for issue in receipt.issues} >= {
        "vehicle.no-sensors",
        "vehicle.localization-sensor-unqualified",
    }


def test_map_asset_admission_checks_structure_without_retaining_bytes() -> None:
    registry = MapAssetAdmissionRegistry(maximum_receipts=2)
    manifest = json.dumps(
        {"asset": {"version": "2.0"}, "meshes": [{"primitives": []}]},
        separators=(",", ":"),
    ).encode()
    manifest += b" " * (-len(manifest) % 4)
    glb = (
        b"glTF"
        + struct.pack("<II", 2, 20 + len(manifest))
        + struct.pack("<I4s", len(manifest), b"JSON")
        + manifest
    )

    async def chunks():
        yield glb[:5]
        yield glb[5:]

    receipt = asyncio.run(registry.admit("user-a", "office.glb", chunks()))

    assert receipt.status == "admitted"
    assert receipt.layers == ["mesh"]
    assert receipt.planning_qualified is False
    assert receipt.byte_size == len(glb)


def test_map_asset_admission_rejects_a_malformed_glb() -> None:
    registry = MapAssetAdmissionRegistry(maximum_receipts=2)

    async def chunks():
        yield b"not-a-glb"

    receipt = asyncio.run(registry.admit("user-a", "broken.glb", chunks()))

    assert receipt.status == "rejected"
    assert receipt.issues[0].code == "map.glb-header-invalid"


def test_map_asset_admission_rejects_header_only_glb_and_empty_geojson() -> None:
    registry = MapAssetAdmissionRegistry(maximum_receipts=4)

    async def header_only():
        yield b"glTF" + struct.pack("<II", 2, 12)

    async def empty_geojson():
        yield b"{}"

    glb = asyncio.run(registry.admit("user-a", "header-only.glb", header_only()))
    geojson = asyncio.run(registry.admit("user-a", "empty.geojson", empty_geojson()))

    assert glb.status == "rejected"
    assert "map.glb-json-chunk-missing" in {issue.code for issue in glb.issues}
    assert geojson.status == "rejected"
    assert geojson.issues[0].code == "map.geojson-structure-invalid"


def test_map_asset_admission_rejects_a_malformed_gltf_asset_member() -> None:
    registry = MapAssetAdmissionRegistry(maximum_receipts=4)

    async def malformed_gltf():
        yield b'{"asset":[],"meshes":[{}]}'

    async def empty_gltf():
        yield b'{"asset":{"version":"2.0"}}'

    receipt = asyncio.run(registry.admit("user-a", "malformed.gltf", malformed_gltf()))
    empty_receipt = asyncio.run(registry.admit("user-a", "empty.gltf", empty_gltf()))

    assert receipt.status == "rejected"
    assert receipt.issues[0].code == "map.gltf-version-unsupported"
    assert empty_receipt.status == "rejected"
    assert empty_receipt.issues[0].code == "map.gltf-meshes-missing"


def test_map_asset_admission_rejects_a_malformed_glb_asset_member() -> None:
    registry = MapAssetAdmissionRegistry(maximum_receipts=2)
    manifest = b'{"asset":null,"meshes":[{}]}'
    manifest += b" " * (-len(manifest) % 4)
    glb = (
        b"glTF"
        + struct.pack("<II", 2, 20 + len(manifest))
        + struct.pack("<I4s", len(manifest), b"JSON")
        + manifest
    )

    async def malformed_glb():
        yield glb

    receipt = asyncio.run(registry.admit("user-a", "malformed.glb", malformed_glb()))

    assert receipt.status == "rejected"
    assert receipt.issues[0].code == "map.glb-manifest-invalid"
