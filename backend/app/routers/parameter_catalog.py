"""Read-only PX4 parameter catalog and search-space validation API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StrictFloat, StrictInt

from app.parameters import (
    CATALOG_SOURCE,
    CATALOG_VERSION,
    GROUPS,
    SUPPORTED_PX4_VERSIONS,
    catalog_payload,
    get_parameter,
    normalize_px4_version,
    validate_search_selections,
)
from app.response import ok

router = APIRouter(prefix="/parameter-catalog", tags=["parameter-catalog"])
NumberInput = StrictInt | StrictFloat


class SearchSelectionInput(BaseModel):
    """One parameter interval selected by a user for optimization."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1, max_length=32)
    search_min: NumberInput = Field(validation_alias=AliasChoices("search_min", "minimum"))
    search_max: NumberInput = Field(validation_alias=AliasChoices("search_max", "maximum"))
    initial_value: NumberInput | None = Field(
        default=None,
        validation_alias=AliasChoices("initial_value", "baseline"),
    )
    # Compatibility with the Job.parameter_space contract. These fields are
    # preserved for UI round-tripping while the catalog owns type and safety.
    step: NumberInput | None = None
    scale: str | None = None
    value_type: str | None = None
    choices: list[str | NumberInput] | None = None
    enabled: bool = True
    locked: bool = False


class SearchValidationRequest(BaseModel):
    """A complete optimizer search-space validation request."""

    model_config = ConfigDict(extra="forbid")

    px4_version: str = "main"
    enforce_safe_bounds: bool = True
    selections: list[SearchSelectionInput] = Field(min_length=1, max_length=64)


def _bad_catalog_request(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "code": "INVALID_PARAMETER_CATALOG_REQUEST",
            "message": str(exc),
        },
    )


@router.get("")
def read_parameter_catalog(
    px4_version: str = Query(default="main"),
    group: str | None = Query(default=None),
) -> dict[str, object]:
    """List the versioned multicopter catalog, optionally filtered by group."""

    try:
        payload = catalog_payload(px4_version=px4_version, group=group)
    except ValueError as exc:
        raise _bad_catalog_request(exc) from exc
    return ok(payload)


@router.get("/groups")
def read_parameter_groups(px4_version: str = Query(default="main")) -> dict[str, object]:
    """Return UI group metadata and recommended inside-out tuning order."""

    try:
        normalized_version = normalize_px4_version(px4_version)
    except ValueError as exc:
        raise _bad_catalog_request(exc) from exc
    return ok(
        {
            "catalog_version": CATALOG_VERSION,
            "source": CATALOG_SOURCE,
            "px4_version": normalized_version,
            "supported_px4_versions": list(SUPPORTED_PX4_VERSIONS),
            "tuning_order": [
                "angular_rate",
                "attitude",
                "filters",
                "xy_position_velocity",
                "z_position_velocity",
                "motion_limits",
            ],
            "groups": list(GROUPS),
        }
    )


@router.post("/validate")
def validate_parameter_search_space(
    request: SearchValidationRequest,
) -> dict[str, object]:
    """Validate selected names, hard/safe bounds, duplicates, and couplings."""

    try:
        normalized_version = normalize_px4_version(request.px4_version)
        active = [
            selection
            for selection in request.selections
            if selection.enabled and not selection.locked
        ]
        result = validate_search_selections(
            (selection.model_dump() for selection in active),
            px4_version=normalized_version,
            enforce_safe_bounds=request.enforce_safe_bounds,
        )
    except ValueError as exc:
        raise _bad_catalog_request(exc) from exc
    return ok(
        {
            "catalog_version": CATALOG_VERSION,
            "px4_version": normalized_version,
            "ignored": [
                {
                    "name": selection.name,
                    "reason": "disabled" if not selection.enabled else "locked",
                }
                for selection in request.selections
                if not selection.enabled or selection.locked
            ],
            **result.to_dict(),
        }
    )


@router.get("/{parameter_name}")
def read_parameter(
    parameter_name: str,
    px4_version: str = Query(default="main"),
) -> dict[str, object]:
    """Read one catalog entry by its real PX4 parameter name."""

    try:
        normalized_version = normalize_px4_version(px4_version)
        parameter = get_parameter(parameter_name, px4_version=normalized_version)
    except ValueError as exc:
        raise _bad_catalog_request(exc) from exc
    if parameter is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PARAMETER_NOT_FOUND",
                "message": f"Unknown PX4 parameter: {parameter_name}",
            },
        )
    return ok(
        {
            "catalog_version": CATALOG_VERSION,
            "px4_version": normalized_version,
            "parameter": parameter.to_dict(),
        }
    )
