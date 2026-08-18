"""Persistent, owner-scoped qualification credentials for autonomy assets."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as orm_models
from app.autonomy.catalog import get_bundled_map_manifest
from app.autonomy.models import (
    AutonomyCompileRequest,
    AutonomyHarnessAsset,
    AutonomyHarnessInspectRequest,
)
from app.autonomy.qualification import (
    MapPackQualificationReceipt,
    MapPackQualificationRequest,
    VehiclePackQualificationReceipt,
    VehiclePackQualificationRequest,
    qualify_map_pack,
    qualify_vehicle_pack,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _receipt_id(prefix: str, owner_id: str, content_sha256: str) -> str:
    owner_binding = hashlib.sha256(f"{owner_id}:{content_sha256}".encode()).hexdigest()
    return f"{prefix}-receipt-{owner_binding[:32]}"


class QualificationCredentialConflict(ValueError):
    """Raised when an asset version would violate immutable credential history."""


@dataclass(frozen=True)
class VerifiedAutonomyAssetReceipt:
    """Server-only binding to the qualification rows used for one runtime session."""

    owner_id: str
    aircraft_receipt_id: str
    aircraft_content_sha256: str
    aircraft_fixed_adapter_identity_sha256: str
    map_receipt_id: str
    map_content_sha256: str


def fixed_adapter_vehicle_identity_sha256(request: VehiclePackQualificationRequest) -> str:
    """Hash every fixed-adapter field except the two supported motion-limit overrides."""

    canonical = request.model_dump(mode="json")
    canonical.pop("maximum_speed_mps")
    canonical.pop("maximum_acceleration_mps2")
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _store(
    db: Session,
    *,
    owner_id: str,
    asset_kind: str,
    asset_id: str,
    asset_version: int,
    status: str,
    content_sha256: str,
    manifest_sha256: str | None,
    request_json: dict[str, object],
    receipt_json: dict[str, object],
    receipt_id: str,
) -> None:
    now = _now()
    history = db.scalars(
        select(orm_models.AutonomyQualificationCredential).where(
            orm_models.AutonomyQualificationCredential.user_id == owner_id,
            orm_models.AutonomyQualificationCredential.asset_kind == asset_kind,
            orm_models.AutonomyQualificationCredential.asset_id == asset_id,
        )
    ).all()
    same_version = next(
        (item for item in history if item.asset_version == asset_version),
        None,
    )
    if same_version is not None and same_version.content_sha256 != content_sha256:
        raise QualificationCredentialConflict(
            "An autonomy asset version is immutable after qualification."
        )
    if any(item.asset_version > asset_version for item in history):
        raise QualificationCredentialConflict(
            "An older autonomy asset version cannot replace a newer qualification."
        )
    if same_version is not None and same_version.revoked_at is not None:
        raise QualificationCredentialConflict(
            "A revoked autonomy asset version cannot be reactivated."
        )
    active = [item for item in history if item.revoked_at is None]
    for active_credential in active:
        if active_credential.receipt_id != receipt_id:
            active_credential.revoked_at = now
    stored = db.get(orm_models.AutonomyQualificationCredential, receipt_id)
    if stored is None:
        stored = orm_models.AutonomyQualificationCredential(receipt_id=receipt_id)
        db.add(stored)
    stored.user_id = owner_id
    stored.asset_kind = asset_kind
    stored.asset_id = asset_id
    stored.asset_version = asset_version
    stored.status = status
    stored.content_sha256 = content_sha256
    stored.manifest_sha256 = manifest_sha256
    stored.request_json = request_json
    stored.receipt_json = receipt_json
    stored.created_at = now
    stored.revoked_at = None
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        winner = db.scalar(
            select(orm_models.AutonomyQualificationCredential).where(
                orm_models.AutonomyQualificationCredential.user_id == owner_id,
                orm_models.AutonomyQualificationCredential.asset_kind == asset_kind,
                orm_models.AutonomyQualificationCredential.asset_id == asset_id,
                orm_models.AutonomyQualificationCredential.revoked_at.is_(None),
            )
        )
        if (
            winner is not None
            and winner.asset_version == asset_version
            and winner.content_sha256 == content_sha256
            and winner.receipt_id == receipt_id
        ):
            return
        raise QualificationCredentialConflict(
            "Another qualification replaced this autonomy asset version."
        ) from exc


def issue_vehicle_credential(
    db: Session,
    owner_id: str,
    request: VehiclePackQualificationRequest,
    receipt: VehiclePackQualificationReceipt,
) -> VehiclePackQualificationReceipt:
    if receipt.status != "validated_unsigned":
        return receipt
    bound = receipt.model_copy(
        update={"receipt_id": _receipt_id("vehicle", owner_id, receipt.content_sha256)}
    )
    _store(
        db,
        owner_id=owner_id,
        asset_kind="aircraft",
        asset_id=request.pack_id,
        asset_version=request.version,
        status=bound.status,
        content_sha256=bound.content_sha256,
        manifest_sha256=None,
        request_json=request.model_dump(mode="json"),
        receipt_json=bound.model_dump(mode="json"),
        receipt_id=bound.receipt_id,
    )
    return bound


def issue_map_credential(
    db: Session,
    owner_id: str,
    request: MapPackQualificationRequest,
    receipt: MapPackQualificationReceipt,
) -> MapPackQualificationReceipt:
    if receipt.status != "qualified":
        return receipt
    bound = receipt.model_copy(
        update={"receipt_id": _receipt_id("map", owner_id, receipt.content_sha256)}
    )
    _store(
        db,
        owner_id=owner_id,
        asset_kind="map",
        asset_id=request.pack_id,
        asset_version=request.version,
        status=bound.status,
        content_sha256=bound.content_sha256,
        manifest_sha256=bound.manifest_sha256,
        request_json=request.model_dump(mode="json"),
        receipt_json=bound.model_dump(mode="json"),
        receipt_id=bound.receipt_id,
    )
    return bound


@dataclass(frozen=True)
class CredentialVerification:
    aircraft_issues: list[str]
    map_issues: list[str]
    aircraft: orm_models.AutonomyQualificationCredential | None
    map_pack: orm_models.AutonomyQualificationCredential | None


def verified_asset_receipt(
    owner_id: str,
    verification: CredentialVerification,
) -> VerifiedAutonomyAssetReceipt:
    """Materialize an immutable server-only receipt after the credential gates pass."""

    aircraft = verification.aircraft
    map_pack = verification.map_pack
    if (
        verification.aircraft_issues
        or verification.map_issues
        or aircraft is None
        or map_pack is None
        or aircraft.user_id != owner_id
        or map_pack.user_id != owner_id
    ):
        raise ValueError("verified autonomy asset credentials are required")
    aircraft_request = VehiclePackQualificationRequest.model_validate(aircraft.request_json)
    return VerifiedAutonomyAssetReceipt(
        owner_id=owner_id,
        aircraft_receipt_id=aircraft.receipt_id,
        aircraft_content_sha256=aircraft.content_sha256,
        aircraft_fixed_adapter_identity_sha256=fixed_adapter_vehicle_identity_sha256(
            aircraft_request
        ),
        map_receipt_id=map_pack.receipt_id,
        map_content_sha256=map_pack.content_sha256,
    )


def _credential(
    db: Session,
    owner_id: str,
    asset: AutonomyHarnessAsset,
) -> orm_models.AutonomyQualificationCredential | None:
    if not asset.qualification_receipt_id:
        return None
    return db.scalar(
        select(orm_models.AutonomyQualificationCredential).where(
            orm_models.AutonomyQualificationCredential.receipt_id == asset.qualification_receipt_id,
            orm_models.AutonomyQualificationCredential.user_id == owner_id,
            orm_models.AutonomyQualificationCredential.asset_kind == asset.kind,
        )
    )


def _same_number(actual: object, expected: float, *, tolerance: float = 1e-6) -> bool:
    return (
        isinstance(actual, (int, float))
        and not isinstance(actual, bool)
        and math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=tolerance)
    )


def _string_list(value: object) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return value


def _common_issues(
    asset: AutonomyHarnessAsset,
    credential: orm_models.AutonomyQualificationCredential | None,
) -> list[str]:
    prefix = "aircraft" if asset.kind == "aircraft" else "map"
    if credential is None:
        return [f"{prefix}.qualification-receipt.invalid"]
    issues: list[str] = []
    if credential.revoked_at is not None:
        issues.append(f"{prefix}.qualification-receipt.revoked")
    if credential.asset_id != asset.asset_id or credential.asset_version != asset.version:
        issues.append(f"{prefix}.qualification-receipt.binding-mismatch")
    if asset.content_hash != credential.content_sha256:
        issues.append(f"{prefix}.qualification-receipt.content-mismatch")
    return issues


def _aircraft_binding_issues(
    asset: AutonomyHarnessAsset,
    credential: orm_models.AutonomyQualificationCredential | None,
) -> list[str]:
    issues = _common_issues(asset, credential)
    if credential is None:
        return issues
    try:
        request = VehiclePackQualificationRequest.model_validate(credential.request_json)
        receipt = VehiclePackQualificationReceipt.model_validate_json(
            json.dumps(credential.receipt_json, separators=(",", ":"))
        )
    except ValidationError:
        return [*issues, "aircraft.qualification-receipt.corrupt"]
    requalified = qualify_vehicle_pack(request)
    if (
        credential.status != "validated_unsigned"
        or receipt.status != "validated_unsigned"
        or requalified.status != "validated_unsigned"
        or receipt.pack_id != credential.asset_id
        or receipt.version != credential.asset_version
        or receipt.content_sha256 != credential.content_sha256
        or requalified.content_sha256 != credential.content_sha256
    ):
        issues.append("aircraft.qualification-receipt.integrity-mismatch")
    expected_localization = sorted(
        sensor.kind
        for sensor in request.sensors
        if sensor.kind in {"gps", "vio"} and sensor.calibrated
    )
    caps = asset.capabilities
    comparisons = (
        _same_number(caps.get("body_radius_m"), receipt.planning_radius_m, tolerance=1e-4),
        _same_number(caps.get("dry_mass_kg"), request.dry_mass_kg),
        _same_number(caps.get("maximum_takeoff_mass_kg"), request.max_takeoff_mass_kg),
        _same_number(caps.get("maximum_thrust_n"), request.max_total_thrust_n),
        _same_number(caps.get("maximum_speed_mps"), request.maximum_speed_mps),
        _same_number(caps.get("maximum_acceleration_mps2"), request.maximum_acceleration_mps2),
        _same_number(caps.get("maximum_pickup_payload_kg"), request.maximum_pickup_payload_kg),
        _same_number(caps.get("reserve_battery_percent"), request.reserve_battery_percent),
        (
            (localization := _string_list(caps.get("localization_sources"))) is not None
            and sorted(localization) == expected_localization
        ),
    )
    if not all(comparisons):
        issues.append("aircraft.qualification-receipt.capability-mismatch")
    return issues


def _map_binding_issues(
    asset: AutonomyHarnessAsset,
    credential: orm_models.AutonomyQualificationCredential | None,
) -> list[str]:
    issues = _common_issues(asset, credential)
    if credential is None:
        return issues
    try:
        request = MapPackQualificationRequest.model_validate(credential.request_json)
        receipt = MapPackQualificationReceipt.model_validate_json(
            json.dumps(credential.receipt_json, separators=(",", ":"))
        )
    except ValidationError:
        return [*issues, "map.qualification-receipt.corrupt"]
    requalified = qualify_map_pack(request)
    if (
        credential.status != "qualified"
        or receipt.status != "qualified"
        or requalified.status != "qualified"
        or receipt.pack_id != credential.asset_id
        or receipt.version != credential.asset_version
        or receipt.content_sha256 != credential.content_sha256
        or requalified.content_sha256 != credential.content_sha256
    ):
        issues.append("map.qualification-receipt.integrity-mismatch")
    manifest = get_bundled_map_manifest(request.compiler_scene_id)
    if (
        manifest is None
        or credential.manifest_sha256 != manifest["manifest_sha256"]
        or receipt.manifest_sha256 != manifest["manifest_sha256"]
    ):
        issues.append("map.qualification-receipt.manifest-stale")
    caps = asset.capabilities
    expected_origin = request.origin
    comparisons = (
        caps.get("representation") == request.representation,
        caps.get("coordinate_frame") == request.coordinate_frame,
        _same_number(caps.get("resolution_m"), request.resolution_m),
        caps.get("floor_count") == request.floor_count,
        _same_number(caps.get("bounds_x_m"), request.bounds_m.x),
        _same_number(caps.get("bounds_y_m"), request.bounds_m.y),
        _same_number(caps.get("bounds_z_m"), request.bounds_m.z),
        _same_number(caps.get("confidence_percent"), request.confidence_percent),
        caps.get("live_updates") == request.live_updates,
        caps.get("origin_latitude") == expected_origin.latitude,
        caps.get("origin_longitude") == expected_origin.longitude,
        caps.get("origin_altitude_m") == expected_origin.altitude_m,
        (
            (semantic := _string_list(caps.get("semantic_layers"))) is not None
            and set(semantic) == set(request.semantic_layers)
        ),
        (
            (planning := _string_list(caps.get("planning_layers"))) is not None
            and set(planning) == set(request.planning_layers)
        ),
        caps.get("compiler_scene_id") == request.compiler_scene_id,
    )
    if not all(comparisons):
        issues.append("map.qualification-receipt.capability-mismatch")
    return issues


def verify_harness_credentials(
    db: Session,
    owner_id: str,
    request: AutonomyHarnessInspectRequest,
) -> CredentialVerification:
    aircraft = _credential(db, owner_id, request.aircraft)
    map_pack = _credential(db, owner_id, request.map_pack)
    return CredentialVerification(
        aircraft_issues=_aircraft_binding_issues(request.aircraft, aircraft),
        map_issues=_map_binding_issues(request.map_pack, map_pack),
        aircraft=aircraft,
        map_pack=map_pack,
    )


def compile_binding_issues(
    request: AutonomyCompileRequest,
    verification: CredentialVerification,
) -> list[str]:
    issues: list[str] = []
    if request.asset_context is None:
        return ["autonomy.compile.asset-context.missing"]
    aircraft = verification.aircraft
    map_pack = verification.map_pack
    if aircraft is None or map_pack is None:
        return ["autonomy.compile.qualification-receipt.invalid"]
    try:
        aircraft_request = VehiclePackQualificationRequest.model_validate(aircraft.request_json)
        aircraft_receipt = VehiclePackQualificationReceipt.model_validate_json(
            json.dumps(aircraft.receipt_json, separators=(",", ":"))
        )
        map_request = MapPackQualificationRequest.model_validate(map_pack.request_json)
    except ValidationError:
        return ["autonomy.compile.qualification-receipt.corrupt"]
    vehicle = request.vehicle
    if not all(
        (
            _same_number(vehicle.dry_mass_kg, aircraft_request.dry_mass_kg),
            _same_number(vehicle.max_takeoff_mass_kg, aircraft_request.max_takeoff_mass_kg),
            _same_number(vehicle.max_total_thrust_n, aircraft_request.max_total_thrust_n),
            _same_number(vehicle.radius_m, aircraft_receipt.planning_radius_m, tolerance=1e-4),
            _same_number(vehicle.max_speed_mps, aircraft_request.maximum_speed_mps),
            _same_number(
                vehicle.max_acceleration_mps2,
                aircraft_request.maximum_acceleration_mps2,
            ),
            _same_number(
                vehicle.reserve_battery_percent,
                aircraft_request.reserve_battery_percent,
            ),
            vehicle.pickup_payload_kg <= aircraft_request.maximum_pickup_payload_kg,
        )
    ):
        issues.append("autonomy.compile.vehicle-envelope.credential-mismatch")
    if request.scene_id != map_request.compiler_scene_id:
        issues.append("autonomy.compile.scene.credential-mismatch")
    return issues


__all__ = [
    "CredentialVerification",
    "QualificationCredentialConflict",
    "VerifiedAutonomyAssetReceipt",
    "compile_binding_issues",
    "fixed_adapter_vehicle_identity_sha256",
    "issue_map_credential",
    "issue_vehicle_credential",
    "verified_asset_receipt",
    "verify_harness_credentials",
]
