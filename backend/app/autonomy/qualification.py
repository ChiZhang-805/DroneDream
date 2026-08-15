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

from app.autonomy.models import StrictModel, Vector3

MAX_MAP_ASSET_BYTES = 25 * 1024 * 1024
MAX_ASSET_RECEIPTS = 512
SUPPORTED_MAP_FORMATS = {"glb", "gltf", "geojson", "json", "ply", "pcd"}
MapLayer = Literal["mesh", "point-cloud", "semantic", "georeference"]


class SensorCalibration(StrictModel):
    sensor_id: str = Field(min_length=1, max_length=80)
    kind: Literal["rgb", "depth", "stereo", "thermal", "lidar", "gps", "vio"]
    calibrated: bool
    position_m: Vector3
    roll_pitch_yaw_deg: Vector3
    rate_hz: float = Field(gt=0.0, le=1000.0)
    calibration_age_days: float = Field(ge=0.0, le=3650.0)


class VehiclePackQualificationRequest(StrictModel):
    pack_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    version: int = Field(ge=1, le=1_000_000)
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
        if min(self.body_size_m.x, self.body_size_m.y, self.body_size_m.z) <= 0:
            raise ValueError("body_size_m must be positive")
        if min(self.inertia_kg_m2.x, self.inertia_kg_m2.y, self.inertia_kg_m2.z) <= 0:
            raise ValueError("inertia_kg_m2 must be positive")
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
        version = (
            str(payload.get("asset", {}).get("version", "")) if isinstance(payload, dict) else ""
        )
        if not version.startswith("2"):
            issues.append(
                QualificationIssue(
                    code="map.gltf-version-unsupported",
                    severity="error",
                    message="Only glTF 2.x assets are admitted.",
                )
            )
        return "gltf-2-json", ["mesh"], issues
    geo_type = payload.get("type") if isinstance(payload, dict) else None
    if extension == "geojson" or geo_type in {
        "FeatureCollection",
        "Feature",
        "Point",
        "LineString",
        "Polygon",
        "MultiPoint",
        "MultiLineString",
        "MultiPolygon",
        "GeometryCollection",
    }:
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
        return "glb-2-binary", ["mesh"], issues
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
    "VehiclePackQualificationReceipt",
    "VehiclePackQualificationRequest",
    "map_asset_admissions",
    "qualify_vehicle_pack",
]
