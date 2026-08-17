"""Read-only compilation and qualification API for shared mission autonomy."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app import models
from app.auth import get_current_user
from app.autonomy.catalog import get_bundled_map_manifest, list_scenes
from app.autonomy.credentials import (
    QualificationCredentialConflict,
    compile_binding_issues,
    issue_map_credential,
    issue_vehicle_credential,
    verify_harness_credentials,
)
from app.autonomy.harness import inspect_autonomy_harness
from app.autonomy.models import (
    AutonomyCompileRequest,
    AutonomyHarnessInspectRequest,
    RuntimeObservation,
    RuntimeOperatorCommand,
    RuntimeSessionCreateRequest,
)
from app.autonomy.qualification import (
    MapPackQualificationRequest,
    VehiclePackQualificationRequest,
    map_asset_admissions,
    qualify_map_pack,
    qualify_vehicle_pack,
)
from app.autonomy.runtime import AutonomyRuntimeError, runtime_sessions
from app.autonomy.school_map_artifact import get_school_map_gazebo_artifact
from app.autonomy.service import AutonomyCompileError, compile_autonomy_mission
from app.db import get_db
from app.response import ok

router = APIRouter(prefix="/autonomy", tags=["autonomy"])


def _runtime_error(exc: AutonomyRuntimeError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def _credential_conflict(exc: QualificationCredentialConflict) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "AUTONOMY_QUALIFICATION_VERSION_CONFLICT",
            "message": str(exc),
        },
    )


def _authorize_compile_request(
    request: AutonomyCompileRequest,
    current_user: models.User,
    db: Session,
) -> str:
    asset_context = request.asset_context
    if asset_context is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "AUTONOMY_ASSET_GATE_REQUIRED",
                "message": "A verified Vehicle Pack and Map Pack context is required.",
                "details": {
                    "blockers": ["autonomy.compile.asset-context.missing"],
                },
            },
        )
    harness_request = AutonomyHarnessInspectRequest(
        edition=request.edition,
        natural_language=request.natural_language,
        aircraft=asset_context.aircraft,
        map_pack=asset_context.map_pack,
    )
    verification = verify_harness_credentials(db, current_user.id, harness_request)
    inspection = inspect_autonomy_harness(
        harness_request,
        credential_issues=(verification.aircraft_issues, verification.map_issues),
    )
    blockers = list(inspection.blockers)
    if asset_context.harness_context_sha256 != inspection.context_sha256:
        blockers.append("autonomy.compile.harness-context.mismatch")
    blockers.extend(compile_binding_issues(request, verification))
    blockers = sorted(set(blockers))
    if blockers:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "AUTONOMY_ASSET_GATE_BLOCKED",
                "message": "The mission is not bound to current qualified autonomy assets.",
                "details": {"blockers": blockers},
            },
        )
    return inspection.context_sha256


@router.get("/scenes")
def read_autonomy_scenes(
    _current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    return ok(
        {
            "schema_version": "dronedream.autonomy.scene-catalog.v1",
            "items": [
                {
                    **scene.model_dump(mode="json"),
                    "map_pack_manifest": get_bundled_map_manifest(scene.id),
                }
                for scene in list_scenes()
            ],
        }
    )


@router.get("/scenes/{scene_id}/gazebo-artifact")
def read_autonomy_scene_gazebo_artifact(
    scene_id: str,
    _current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Export a content-addressed static SDF plus its semantic contract."""

    if scene_id != "school-campus-v1":
        raise HTTPException(
            status_code=404,
            detail={
                "code": "AUTONOMY_GAZEBO_ARTIFACT_NOT_FOUND",
                "message": "The requested scene has no exported Gazebo artifact.",
            },
        )
    artifact = get_school_map_gazebo_artifact()
    return ok(
        {
            "schema_version": "dronedream.autonomy.gazebo-artifact-export.v1",
            "compiler_scene_id": scene_id,
            "summary": artifact.summary,
            "files": artifact.package_files,
        }
    )


@router.post("/compile")
async def compile_mission(
    request: AutonomyCompileRequest,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Compile and qualify a mission without starting a simulator or vehicle."""

    _authorize_compile_request(request, current_user, db)
    try:
        result = await asyncio.to_thread(compile_autonomy_mission, request)
    except AutonomyCompileError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return ok(result.model_dump(mode="json"))


@router.post("/harness/inspect")
async def inspect_mission_harness(
    request: AutonomyHarnessInspectRequest,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Execute read-only asset gates before any model can draft a mission."""

    verification = verify_harness_credentials(db, current_user.id, request)
    result = inspect_autonomy_harness(
        request,
        credential_issues=(verification.aircraft_issues, verification.map_issues),
    )
    return ok(result.model_dump(mode="json"))


@router.post("/vehicle-packs/qualify")
async def qualify_autonomy_vehicle_pack(
    request: VehiclePackQualificationRequest,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Validate a versioned digital Vehicle Pack without granting hardware authority."""

    result = await asyncio.to_thread(qualify_vehicle_pack, request)
    try:
        result = issue_vehicle_credential(db, current_user.id, request, result)
    except QualificationCredentialConflict as exc:
        raise _credential_conflict(exc) from exc
    return ok(result.model_dump(mode="json"))


@router.post("/map-assets/admit", status_code=201)
async def admit_autonomy_map_asset(
    request: Request,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Hash and structurally inspect one bounded map asset; bytes are not retained."""

    try:
        result = await map_asset_admissions.admit(current_user.id, filename, request.stream())
    except ValueError as exc:
        raise HTTPException(
            status_code=413,
            detail={"code": "AUTONOMY_MAP_ASSET_REJECTED", "message": str(exc)},
        ) from exc
    return ok(result.model_dump(mode="json"))


@router.post("/map-packs/qualify")
async def qualify_autonomy_map_pack(
    request: MapPackQualificationRequest,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Qualify an exact bundled Map Pack; imported assets stay admission-only."""

    result = await asyncio.to_thread(qualify_map_pack, request)
    try:
        result = issue_map_credential(db, current_user.id, request, result)
    except QualificationCredentialConflict as exc:
        raise _credential_conflict(exc) from exc
    return ok(result.model_dump(mode="json"))


@router.get("/runtime/capabilities")
def read_runtime_capabilities(
    _current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Expose runtime boundaries without probing or connecting to a vehicle."""

    return ok(runtime_sessions.capabilities())


@router.post("/runtime/sessions", status_code=201)
async def create_runtime_session(
    request: RuntimeSessionCreateRequest,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Create an idempotent, process-local simulation supervision session."""

    _authorize_compile_request(request.mission, current_user, db)
    try:
        result = await asyncio.to_thread(runtime_sessions.create, current_user.id, request)
    except AutonomyRuntimeError as exc:
        raise _runtime_error(exc) from exc
    return ok(result.model_dump(mode="json"))


@router.get("/runtime/sessions/{session_id}")
def read_runtime_session(
    session_id: str,
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    try:
        result = runtime_sessions.get(current_user.id, session_id)
    except AutonomyRuntimeError as exc:
        raise _runtime_error(exc) from exc
    return ok(result.model_dump(mode="json"))


@router.post("/runtime/sessions/{session_id}/observations")
async def ingest_runtime_observation(
    session_id: str,
    observation: RuntimeObservation,
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Evaluate one ordered observation; this endpoint never emits actuator commands."""

    try:
        result = await asyncio.to_thread(
            runtime_sessions.observe,
            current_user.id,
            session_id,
            observation,
        )
    except AutonomyRuntimeError as exc:
        raise _runtime_error(exc) from exc
    return ok(result.model_dump(mode="json"))


@router.post("/runtime/sessions/{session_id}/operator-commands")
async def apply_runtime_operator_command(
    session_id: str,
    command: RuntimeOperatorCommand,
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Accept only safety-reducing hold or abort commands."""

    try:
        result = await asyncio.to_thread(
            runtime_sessions.command,
            current_user.id,
            session_id,
            command,
        )
    except AutonomyRuntimeError as exc:
        raise _runtime_error(exc) from exc
    return ok(result.model_dump(mode="json"))


__all__ = ["router"]
