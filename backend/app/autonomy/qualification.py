"""Bounded Vehicle Pack validation and map-asset admission.

The admission registry intentionally stores receipts, not user file bytes. Geometry
assets are structurally inspected and hashed; a separate audited reconstruction job
must still generate collision geometry, free space and ESDF evidence before a custom
Map Pack can be used by the mission compiler.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections import OrderedDict
from collections.abc import AsyncIterable
from datetime import datetime, timezone
from pathlib import PurePath
from threading import RLock
from typing import Literal

from pydantic import Field, model_validator

from app.autonomy.catalog import get_bundled_map_manifest, get_scene
from app.autonomy.models import StrictModel, Vector3

MAX_MAP_ASSET_BYTES = 25 * 1024 * 1024
MAX_ASSET_RECEIPTS = 512
SUPPORTED_MAP_FORMATS = {"glb", "gltf", "geojson", "json", "ply", "pcd"}
MapLayer = Literal["mesh", "point-cloud", "semantic", "georeference"]
MapRepresentation = Literal["hybrid-3d", "mesh", "point-cloud", "occupancy", "terrain"]
MapCoordinateFrame = Literal["ENU", "NED", "WGS84", "building-local"]
MapSemanticLayer = Literal[
    "free-space",
    "stairs",
    "doors",
    "gates",
    "people",
    "pickup-zones",
    "launch-zones",
    "rooms",
    "corridors",
    "roads",
    "vegetation",
    "street-furniture",
]
MapPlanningLayer = Literal[
    "collision-geometry",
    "occupancy",
    "esdf",
    "dynamic-overlay",
    "confidence",
]


class SensorCalibration(StrictModel):
    sensor_id: str = Field(min_length=1, max_length=80)
    kind: Literal["rgb", "depth", "stereo", "thermal", "lidar", "gps", "vio"]
    calibrated: bool
    calibration_status: Literal["unverified", "verified", "expired", "failed"] | None = None
    position_m: Vector3
    roll_pitch_yaw_deg: Vector3
    rate_hz: float = Field(gt=0.0, le=1000.0)
    calibration_age_days: float = Field(ge=0.0, le=3650.0)

    @model_validator(mode="after")
    def validate_calibration_state(self) -> SensorCalibration:
        if self.calibration_status is None:
            object.__setattr__(
                self,
                "calibration_status",
                "verified" if self.calibrated else "unverified",
            )
        if self.calibrated != (self.calibration_status == "verified"):
            raise ValueError("calibrated must be true exactly when calibration_status is verified")
        return self


class VehiclePackQualificationRequest(StrictModel):
    pack_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    version: int = Field(ge=1, le=1_000_000)
    autopilot: Literal["px4", "ardupilot", "custom"] | None = None
    firmware: str = Field(min_length=1, max_length=120)
    flight_controller: str = Field(min_length=1, max_length=120)
    control_interface: Literal["px4-ros2", "mavsdk", "mavlink", "simulation-only"]
    dry_mass_kg: float = Field(gt=0.1, le=50.0)
    max_takeoff_mass_kg: float = Field(gt=0.1, le=70.0)
    max_total_thrust_n: float = Field(gt=1.0, le=5000.0)
    body_size_m: Vector3
    rotor_radius_m: float = Field(ge=0.01, le=3.0)
    center_of_gravity_m: Vector3
    inertia_kg_m2: Vector3
    battery_energy_wh: float = Field(gt=1.0, le=1_000_000.0)
    reserve_battery_percent: float = Field(ge=10.0, le=90.0)
    maximum_pickup_payload_kg: float = Field(ge=0.0, le=20.0)
    maximum_speed_mps: float = Field(ge=0.2, le=20.0)
    maximum_acceleration_mps2: float = Field(ge=0.2, le=30.0)
    maximum_climb_mps: float = Field(ge=0.1, le=15.0)
    maximum_descent_mps: float = Field(ge=0.1, le=10.0)
    command_link_latency_ms: float = Field(ge=0.0, le=60_000.0)
    command_link_bandwidth_mbps: float = Field(gt=0.0, le=100_000.0)
    sensors: list[SensorCalibration] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_dimensions(self) -> VehiclePackQualificationRequest:
        if self.autopilot is None:
            inferred_autopilot = (
                "px4"
                if self.control_interface == "px4-ros2"
                else "ardupilot"
                if "ardu" in self.firmware.lower()
                else "px4"
            )
            object.__setattr__(self, "autopilot", inferred_autopilot)
        if min(self.body_size_m.x, self.body_size_m.y, self.body_size_m.z) <= 0:
            raise ValueError("body_size_m must be positive")
        if min(self.inertia_kg_m2.x, self.inertia_kg_m2.y, self.inertia_kg_m2.z) <= 0:
            raise ValueError("inertia_kg_m2 must be positive")
        if self.autopilot != "px4" and self.control_interface == "px4-ros2":
            raise ValueError("px4-ros2 control_interface requires the PX4 autopilot")
        return self


class QualificationIssue(StrictModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str


class VehiclePackQualificationReceipt(StrictModel):
    schema_version: Literal["dronedream.autonomy.vehicle-pack-receipt.v1"] = (
        "dronedream.autonomy.vehicle-pack-receipt.v1"
    )
    receipt_id: str
    pack_id: str
    version: int
    status: Literal["blocked", "validated_unsigned"]
    content_sha256: str
    planning_radius_m: float
    maximum_loaded_mass_kg: float
    loaded_thrust_to_weight: float
    issues: list[QualificationIssue]
    created_at: datetime
    hardware_authority: Literal[False] = False


class MapAssetAdmissionReceipt(StrictModel):
    schema_version: Literal["dronedream.autonomy.map-asset-receipt.v1"] = (
        "dronedream.autonomy.map-asset-receipt.v1"
    )
    receipt_id: str
    filename: str
    format: str
    byte_size: int
    content_sha256: str
    parser: str
    status: Literal["admitted", "rejected"]
    layers: list[MapLayer]
    issues: list[QualificationIssue]
    created_at: datetime
    planning_qualified: Literal[False] = False


class MapOrigin(StrictModel):
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    altitude_m: float | None = Field(default=None, ge=-20_000.0, le=100_000.0)

    @model_validator(mode="after")
    def validate_geographic_pair(self) -> MapOrigin:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("origin latitude and longitude must be supplied together")
        return self


class MapPackQualificationRequest(StrictModel):
    schema_version: Literal["dronedream.autonomy.map-pack-qualification.v1"] = (
        "dronedream.autonomy.map-pack-qualification.v1"
    )
    name: str = Field(min_length=1, max_length=160)
    pack_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    version: int = Field(ge=1, le=1_000_000)
    compiler_scene_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    representation: MapRepresentation
    coordinate_frame: MapCoordinateFrame
    resolution_m: float = Field(ge=0.005, le=5.0)
    floor_count: int = Field(ge=1, le=500)
    bounds_m: Vector3
    origin: MapOrigin = Field(default_factory=MapOrigin)
    live_updates: Literal["vision-slam", "depth-fusion", "lidar-fusion", "fixed"]
    calibrated: bool
    confidence_percent: float = Field(ge=0.0, le=100.0)
    semantic_layers: list[MapSemanticLayer] = Field(max_length=16)
    planning_layers: list[MapPlanningLayer] = Field(max_length=16)
    source_asset_receipt_ids: list[str] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def validate_bounds(self) -> MapPackQualificationRequest:
        if min(self.bounds_m.x, self.bounds_m.y, self.bounds_m.z) <= 0:
            raise ValueError("bounds_m must be positive")
        if len(self.semantic_layers) != len(set(self.semantic_layers)):
            raise ValueError("semantic_layers contains duplicates")
        if len(self.planning_layers) != len(set(self.planning_layers)):
            raise ValueError("planning_layers contains duplicates")
        return self


class MapPackQualificationReceipt(StrictModel):
    schema_version: Literal["dronedream.autonomy.map-pack-receipt.v1"] = (
        "dronedream.autonomy.map-pack-receipt.v1"
    )
    receipt_id: str
    pack_id: str
    version: int
    status: Literal["blocked", "qualified"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiler_scene_id: str
    coordinate_frame: MapCoordinateFrame
    resolution_m: float
    semantic_layers: list[MapSemanticLayer]
    planning_layers: list[MapPlanningLayer]
    issues: list[QualificationIssue]
    created_at: datetime
    hardware_authority: Literal[False] = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


GEOJSON_GEOMETRY_TYPES = {
    "Point",
    "LineString",
    "Polygon",
    "MultiPoint",
    "MultiLineString",
    "MultiPolygon",
}


def _valid_geojson(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    geo_type = value.get("type")
    if geo_type == "FeatureCollection":
        features = value.get("features")
        return isinstance(features, list) and all(
            isinstance(feature, dict)
            and feature.get("type") == "Feature"
            and _valid_geojson(feature)
            for feature in features
        )
    if geo_type == "Feature":
        geometry = value.get("geometry")
        properties = value.get("properties")
        return (geometry is None or _valid_geojson(geometry)) and (
            properties is None or isinstance(properties, dict)
        )
    if geo_type == "GeometryCollection":
        geometries = value.get("geometries")
        return isinstance(geometries, list) and all(
            _valid_geojson(geometry) for geometry in geometries
        )
    if geo_type in GEOJSON_GEOMETRY_TYPES:
        return isinstance(value.get("coordinates"), list)
    return False


def qualify_vehicle_pack(
    request: VehiclePackQualificationRequest,
) -> VehiclePackQualificationReceipt:
    issues: list[QualificationIssue] = []
    loaded_mass = request.dry_mass_kg + request.maximum_pickup_payload_kg
    thrust_to_weight = request.max_total_thrust_n / (loaded_mass * 9.80665)
    planning_radius = (
        math.hypot(request.body_size_m.x, request.body_size_m.y) / 2 + request.rotor_radius_m
    )
    if loaded_mass > request.max_takeoff_mass_kg:
        issues.append(
            QualificationIssue(
                code="vehicle.loaded-mass-exceeds-mtom",
                severity="error",
                message="Dry mass plus maximum pickup payload exceeds MTOM.",
            )
        )
    if thrust_to_weight < 1.35:
        issues.append(
            QualificationIssue(
                code="vehicle.loaded-thrust-margin-insufficient",
                severity="error",
                message="Loaded thrust-to-weight must remain at least 1.35.",
            )
        )
    half_extents = (
        request.body_size_m.x / 2,
        request.body_size_m.y / 2,
        request.body_size_m.z / 2,
    )
    cog = request.center_of_gravity_m
    if any(
        abs(value) > extent
        for value, extent in zip((cog.x, cog.y, cog.z), half_extents, strict=True)
    ):
        issues.append(
            QualificationIssue(
                code="vehicle.center-of-gravity-outside-body",
                severity="error",
                message="The configured center of gravity lies outside the body envelope.",
            )
        )
    if request.command_link_latency_ms > 250:
        issues.append(
            QualificationIssue(
                code="vehicle.command-link-high-latency",
                severity="warning",
                message=(
                    "Command-link latency exceeds 250 ms; cloud control must not enter a fast loop."
                ),
            )
        )
    if not request.sensors:
        issues.append(
            QualificationIssue(
                code="vehicle.no-sensors",
                severity="error",
                message="At least one calibrated localization or perception sensor is required.",
            )
        )
    if not any(sensor.kind in {"gps", "vio"} and sensor.calibrated for sensor in request.sensors):
        issues.append(
            QualificationIssue(
                code="vehicle.localization-sensor-unqualified",
                severity="error",
                message="No calibrated GPS or VIO source is available.",
            )
        )
    for sensor in request.sensors:
        if not sensor.calibrated:
            issues.append(
                QualificationIssue(
                    code=f"vehicle.sensor-{sensor.sensor_id}-uncalibrated",
                    severity="warning",
                    message=f"Sensor {sensor.sensor_id} is present but not calibrated.",
                )
            )
    canonical = request.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    blocked = any(issue.severity == "error" for issue in issues)
    return VehiclePackQualificationReceipt(
        receipt_id=f"vehicle-receipt-{digest[:24]}",
        pack_id=request.pack_id,
        version=request.version,
        status="blocked" if blocked else "validated_unsigned",
        content_sha256=digest,
        planning_radius_m=round(planning_radius, 4),
        maximum_loaded_mass_kg=round(loaded_mass, 4),
        loaded_thrust_to_weight=round(thrust_to_weight, 4),
        issues=issues,
        created_at=_now(),
    )


def qualify_map_pack(
    request: MapPackQualificationRequest,
) -> MapPackQualificationReceipt:
    """Qualify only an exact bundled planning scene.

    Imported assets remain admission-only until a future reconstruction service
    produces collision, occupancy and coordinate-frame evidence. This function
    therefore cannot turn a user-supplied mesh or point cloud into a qualified map.
    """

    issues: list[QualificationIssue] = []
    scene = get_scene(request.compiler_scene_id)
    manifest = get_bundled_map_manifest(request.compiler_scene_id)
    if scene is None or manifest is None:
        issues.append(
            QualificationIssue(
                code="map.compiler-scene.unknown",
                severity="error",
                message="The requested compiled scene is not registered.",
            )
        )
    if request.source_asset_receipt_ids:
        issues.append(
            QualificationIssue(
                code="map.imported-assets.require-reconstruction",
                severity="error",
                message=(
                    "Imported assets are admitted but require an audited geometry "
                    "reconstruction job before planning qualification."
                ),
            )
        )
    if not request.calibrated:
        issues.append(
            QualificationIssue(
                code="map.scale-frame.not-confirmed",
                severity="error",
                message="The bundled map scale and coordinate frame were not confirmed.",
            )
        )
    if request.coordinate_frame != "ENU":
        issues.append(
            QualificationIssue(
                code="map.coordinate-frame.unsupported-for-bundled-scene",
                severity="error",
                message="Bundled planning scenes currently use the ENU coordinate frame.",
            )
        )
    if request.resolution_m > 0.20:
        issues.append(
            QualificationIssue(
                code="map.resolution.insufficient",
                severity="error",
                message="Planning resolution must be 0.20 m or finer.",
            )
        )
    if request.confidence_percent < 95.0:
        issues.append(
            QualificationIssue(
                code="map.confidence.insufficient",
                severity="error",
                message="Bundled-scene confidence must be at least 95 percent.",
            )
        )
    required_planning_layers = {"collision-geometry", "occupancy"}
    if not required_planning_layers.issubset(set(request.planning_layers)):
        issues.append(
            QualificationIssue(
                code="map.collision-layers.missing",
                severity="error",
                message="Collision geometry and occupancy layers are required.",
            )
        )
    if "free-space" not in request.semantic_layers:
        issues.append(
            QualificationIssue(
                code="map.free-space-layer.missing",
                severity="error",
                message="A semantic free-space layer is required.",
            )
        )
    if scene is not None and manifest is not None:
        expected_bounds = scene.bounds_m
        if any(
            abs(actual - expected) > 1e-6
            for actual, expected in zip(
                (request.bounds_m.x, request.bounds_m.y, request.bounds_m.z),
                (expected_bounds.x, expected_bounds.y, expected_bounds.z),
                strict=True,
            )
        ):
            issues.append(
                QualificationIssue(
                    code="map.bounds.scene-mismatch",
                    severity="error",
                    message="The configured bounds do not match the bundled scene manifest.",
                )
            )
        if request.floor_count != scene.floors:
            issues.append(
                QualificationIssue(
                    code="map.floor-count.scene-mismatch",
                    severity="error",
                    message="The floor count does not match the bundled scene manifest.",
                )
            )
        exact_checks: tuple[tuple[bool, str, str], ...] = (
            (
                request.representation == manifest["representation"],
                "map.representation.scene-mismatch",
                "The 3D representation does not match the bundled scene manifest.",
            ),
            (
                request.coordinate_frame == manifest["coordinate_frame"],
                "map.coordinate-frame.scene-mismatch",
                "The coordinate frame does not match the bundled scene manifest.",
            ),
            (
                math.isclose(
                    request.resolution_m,
                    float(manifest["resolution_m"]),
                    rel_tol=0.0,
                    abs_tol=1e-9,
                ),
                "map.resolution.scene-mismatch",
                "The resolution does not match the bundled scene manifest.",
            ),
            (
                math.isclose(
                    request.confidence_percent,
                    float(manifest["confidence_percent"]),
                    rel_tol=0.0,
                    abs_tol=1e-9,
                ),
                "map.confidence.scene-mismatch",
                "The confidence value does not match the bundled scene manifest.",
            ),
            (
                set(request.semantic_layers) == set(manifest["semantic_layers"]),
                "map.semantic-layers.scene-mismatch",
                "The semantic layers do not match the bundled scene manifest.",
            ),
            (
                set(request.planning_layers) == set(manifest["planning_layers"]),
                "map.planning-layers.scene-mismatch",
                "The planning layers do not match the bundled scene manifest.",
            ),
        )
        for matches, code, message in exact_checks:
            if not matches:
                issues.append(QualificationIssue(code=code, severity="error", message=message))
        gazebo_artifact = manifest.get("gazebo_artifact")
        if gazebo_artifact is not None and not gazebo_artifact.get(
            "simulation_execution_ready", False
        ):
            issues.append(
                QualificationIssue(
                    code="map.gazebo-runtime.not-verified",
                    severity="info",
                    message=(
                        "The content-addressed SDF and collision/semantic contract are "
                        "generated, but real Gazebo/PX4 smoke evidence is not yet bound."
                    ),
                )
            )
    canonical_request = request.model_dump(mode="json")
    canonical_request["semantic_layers"] = sorted(request.semantic_layers)
    canonical_request["planning_layers"] = sorted(request.planning_layers)
    canonical = {
        "request": canonical_request,
        "bundled_manifest": manifest,
        "qualifier": "dronedream.autonomy.map-pack-qualifier.v1",
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    blocked = any(issue.severity == "error" for issue in issues)
    return MapPackQualificationReceipt(
        receipt_id=f"map-receipt-{digest[:24]}",
        pack_id=request.pack_id,
        version=request.version,
        status="blocked" if blocked else "qualified",
        content_sha256=digest,
        manifest_sha256=(str(manifest["manifest_sha256"]) if manifest is not None else "0" * 64),
        compiler_scene_id=request.compiler_scene_id,
        coordinate_frame=request.coordinate_frame,
        resolution_m=request.resolution_m,
        semantic_layers=request.semantic_layers,
        planning_layers=request.planning_layers,
        issues=issues,
        created_at=_now(),
    )


def _json_asset(
    data: bytes, extension: str
) -> tuple[str, list[MapLayer], list[QualificationIssue]]:
    issues: list[QualificationIssue] = []
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return (
            "json",
            [],
            [
                QualificationIssue(
                    code="map.asset-json-invalid", severity="error", message=str(exc)[:200]
                )
            ],
        )
    if extension == "gltf":
        asset = payload.get("asset") if isinstance(payload, dict) else None
        version = str(asset.get("version", "")) if isinstance(asset, dict) else ""
        if not version.startswith("2"):
            issues.append(
                QualificationIssue(
                    code="map.gltf-version-unsupported",
                    severity="error",
                    message="Only glTF 2.x assets are admitted.",
                )
            )
        meshes = payload.get("meshes") if isinstance(payload, dict) else None
        if not isinstance(meshes, list) or not meshes:
            issues.append(
                QualificationIssue(
                    code="map.gltf-meshes-missing",
                    severity="error",
                    message="glTF JSON must declare a mesh collection.",
                )
            )
        return "gltf-2-json", [] if issues else ["mesh"], issues
    geo_type = payload.get("type") if isinstance(payload, dict) else None
    if extension == "geojson" or geo_type in {
        *GEOJSON_GEOMETRY_TYPES,
        "FeatureCollection",
        "Feature",
        "GeometryCollection",
    }:
        if not _valid_geojson(payload):
            return (
                "geojson-rfc7946",
                [],
                [
                    QualificationIssue(
                        code="map.geojson-structure-invalid",
                        severity="error",
                        message="GeoJSON type and required members are invalid.",
                    )
                ],
            )
        return "geojson-rfc7946", ["semantic", "georeference"], issues
    issues.append(
        QualificationIssue(
            code="map.json-purpose-unknown",
            severity="warning",
            message="JSON was admitted as metadata only; no geometry layer was inferred.",
        )
    )
    return "json-metadata", [], issues


def _inspect_map_asset(
    data: bytes, extension: str
) -> tuple[str, list[MapLayer], list[QualificationIssue]]:
    if extension == "glb":
        if len(data) < 12 or data[:4] != b"glTF":
            return (
                "glb-2",
                [],
                [
                    QualificationIssue(
                        code="map.glb-header-invalid",
                        severity="error",
                        message="GLB magic header is invalid.",
                    )
                ],
            )
        version, declared_length = struct.unpack("<II", data[4:12])
        issues = []
        if version != 2:
            issues.append(
                QualificationIssue(
                    code="map.glb-version-unsupported",
                    severity="error",
                    message="Only GLB version 2 is admitted.",
                )
            )
        if declared_length != len(data):
            issues.append(
                QualificationIssue(
                    code="map.glb-length-mismatch",
                    severity="error",
                    message="GLB declared length does not match upload size.",
                )
            )
        if len(data) < 20:
            issues.append(
                QualificationIssue(
                    code="map.glb-json-chunk-missing",
                    severity="error",
                    message="GLB must contain a first JSON chunk.",
                )
            )
            return "glb-2-binary", [], issues
        json_length, json_type = struct.unpack("<I4s", data[12:20])
        json_end = 20 + json_length
        if json_type != b"JSON" or json_end > len(data):
            issues.append(
                QualificationIssue(
                    code="map.glb-json-chunk-invalid",
                    severity="error",
                    message="GLB first chunk must be a bounded JSON chunk.",
                )
            )
            return "glb-2-binary", [], issues
        try:
            manifest = json.loads(data[20:json_end].rstrip(b" \x00").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            issues.append(
                QualificationIssue(
                    code="map.glb-json-invalid",
                    severity="error",
                    message=str(exc)[:200],
                )
            )
            return "glb-2-binary", [], issues
        asset = manifest.get("asset") if isinstance(manifest, dict) else None
        if not isinstance(asset, dict) or not str(asset.get("version", "")).startswith("2"):
            issues.append(
                QualificationIssue(
                    code="map.glb-manifest-invalid",
                    severity="error",
                    message="GLB JSON must declare a glTF 2.x asset.",
                )
            )
        meshes = manifest.get("meshes") if isinstance(manifest, dict) else None
        if not isinstance(meshes, list) or not meshes:
            issues.append(
                QualificationIssue(
                    code="map.glb-meshes-missing",
                    severity="error",
                    message="GLB JSON must declare a mesh collection.",
                )
            )
        return "glb-2-binary", [] if issues else ["mesh"], issues
    if extension in {"gltf", "geojson", "json"}:
        return _json_asset(data, extension)
    header = data[:65_536]
    if extension == "ply":
        normalized = header.replace(b"\r\n", b"\n")
        issues = []
        if not normalized.startswith(b"ply\n") or b"end_header\n" not in normalized:
            issues.append(
                QualificationIssue(
                    code="map.ply-header-invalid",
                    severity="error",
                    message="PLY header or end_header marker is missing.",
                )
            )
        return "ply-header-v1", ["point-cloud", "mesh"], issues
    if extension == "pcd":
        upper = header.upper()
        required = [b"FIELDS", b"SIZE", b"TYPE", b"WIDTH", b"HEIGHT", b"POINTS", b"DATA"]
        missing = [token.decode() for token in required if token not in upper]
        issues = []
        if missing:
            issues.append(
                QualificationIssue(
                    code="map.pcd-header-invalid",
                    severity="error",
                    message=f"PCD header is missing: {', '.join(missing)}.",
                )
            )
        return "pcd-header-v0.7", ["point-cloud"], issues
    return (
        "unsupported",
        [],
        [
            QualificationIssue(
                code="map.asset-format-unsupported",
                severity="error",
                message="Map asset format is not supported.",
            )
        ],
    )


class MapAssetAdmissionRegistry:
    def __init__(self, *, maximum_receipts: int = MAX_ASSET_RECEIPTS) -> None:
        self._maximum_receipts = maximum_receipts
        self._lock = RLock()
        self._receipts: OrderedDict[tuple[str, str], MapAssetAdmissionReceipt] = OrderedDict()

    async def admit(
        self,
        owner_id: str,
        filename: str,
        chunks: AsyncIterable[bytes],
    ) -> MapAssetAdmissionReceipt:
        filename = PurePath(filename or "unnamed").name[:255]
        extension = PurePath(filename).suffix.casefold().lstrip(".")
        hasher = hashlib.sha256()
        retained_chunks: list[bytes] = []
        byte_size = 0
        async for chunk in chunks:
            if not chunk:
                continue
            byte_size += len(chunk)
            if byte_size > MAX_MAP_ASSET_BYTES:
                raise ValueError("map asset exceeds the 25 MiB admission limit")
            hasher.update(chunk)
            retained_chunks.append(chunk)
        data = b"".join(retained_chunks)
        digest = hasher.hexdigest()
        if extension not in SUPPORTED_MAP_FORMATS:
            parser, layers, issues = _inspect_map_asset(data, "unsupported")
        else:
            parser, layers, issues = _inspect_map_asset(data, extension)
        if byte_size == 0:
            issues.append(
                QualificationIssue(
                    code="map.asset-empty", severity="error", message="Map asset is empty."
                )
            )
        rejected = any(issue.severity == "error" for issue in issues)
        receipt = MapAssetAdmissionReceipt(
            receipt_id=f"map-asset-{digest[:24]}",
            filename=filename,
            format=extension or "unknown",
            byte_size=byte_size,
            content_sha256=digest,
            parser=parser,
            status="rejected" if rejected else "admitted",
            layers=layers,
            issues=issues,
            created_at=_now(),
        )
        with self._lock:
            key = (owner_id, receipt.receipt_id)
            self._receipts[key] = receipt
            self._receipts.move_to_end(key)
            while len(self._receipts) > self._maximum_receipts:
                self._receipts.popitem(last=False)
        return receipt.model_copy(deep=True)


map_asset_admissions = MapAssetAdmissionRegistry()


__all__ = [
    "MapAssetAdmissionReceipt",
    "MapAssetAdmissionRegistry",
    "MapPackQualificationReceipt",
    "MapPackQualificationRequest",
    "VehiclePackQualificationReceipt",
    "VehiclePackQualificationRequest",
    "map_asset_admissions",
    "qualify_map_pack",
    "qualify_vehicle_pack",
]
