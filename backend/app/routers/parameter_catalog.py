"""Read-only PX4 parameter catalog and search-space validation API."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, HTTPException, Query
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StrictFloat, StrictInt

from app.parameters import (
    CATALOG_SOURCE,
    CATALOG_VERSION,
    CATALOG_VERSION_ALIASES,
    GROUPS,
    SUPPORTED_AIRFRAME_FAMILIES,
    SUPPORTED_PX4_VERSIONS,
    SUPPORTED_VEHICLE_TYPES,
    WORKFLOW_PRECONDITIONS,
    ParameterValueValidationError,
    SelectionValidationResult,
    ValidationIssue,
    catalog_payload,
    classify_airframe,
    get_parameter,
    normalize_px4_version,
    normalize_vehicle_type,
    preset_payload,
    resolve_catalog_version,
    validate_parameter_values,
    validate_search_selections,
)
from app.parameters.models import ParameterRisk
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

    px4_version: str = Field(default="main", min_length=1, max_length=64)
    catalog_version: str = Field(default=CATALOG_VERSION, min_length=1, max_length=128)
    vehicle_type: str = Field(default="multicopter", min_length=1, max_length=64)
    airframe: str = Field(default="x500", min_length=1, max_length=128)
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
    vehicle_type: str = Query(default="multicopter"),
    airframe: str = Query(default="x500"),
    group: str | None = Query(default=None),
    control_loop: str | None = Query(default=None),
    axis: str | None = Query(default=None),
    risk: str | None = Query(default=None),
) -> dict[str, object]:
    """List the versioned multicopter catalog, optionally filtered by group."""

    try:
        payload = catalog_payload(
            px4_version=px4_version,
            vehicle_type=vehicle_type,
            airframe=airframe,
            group=group,
            control_loop=control_loop,
            axis=axis,
            risk=cast(ParameterRisk | None, risk),
        )
    except ValueError as exc:
        raise _bad_catalog_request(exc) from exc
    return ok(payload)


@router.get("/groups")
def read_parameter_groups(
    px4_version: str = Query(default="main"),
    vehicle_type: str = Query(default="multicopter"),
    airframe: str = Query(default="x500"),
) -> dict[str, object]:
    """Return UI group metadata and recommended inside-out tuning order."""

    try:
        normalized_version = normalize_px4_version(px4_version)
        normalized_vehicle = normalize_vehicle_type(vehicle_type)
        family = classify_airframe(airframe)
    except ValueError as exc:
        raise _bad_catalog_request(exc) from exc
    return ok(
        {
            "catalog_version": CATALOG_VERSION,
            "source": CATALOG_SOURCE,
            "source_url": (
                "https://docs.px4.io/"
                f"{normalized_version}/en/advanced_config/parameter_reference"
            ),
            "px4_version": normalized_version,
            "supported_px4_versions": list(SUPPORTED_PX4_VERSIONS),
            "vehicle_type": normalized_vehicle,
            "supported_vehicle_types": list(SUPPORTED_VEHICLE_TYPES),
            "airframe": airframe,
            "airframe_family": family,
            "supported_airframe_families": list(SUPPORTED_AIRFRAME_FAMILIES),
            "catalog_version_aliases": list(CATALOG_VERSION_ALIASES),
            "tuning_order": [
                "angular_rate",
                "attitude",
                "thrust_and_authority",
                "filters",
                "xy_position_velocity",
                "z_position_velocity",
                "motion_limits",
            ],
            "preconditions": list(WORKFLOW_PRECONDITIONS),
            "groups": list(GROUPS),
        }
    )


@router.get("/presets")
def read_tuning_presets(
    px4_version: str = Query(default="main"),
    vehicle_type: str = Query(default="multicopter"),
    airframe: str = Query(default="x500"),
) -> dict[str, object]:
    """Return ordered, catalog-compatible starting points for guided tuning."""

    try:
        payload = preset_payload(
            px4_version=px4_version,
            vehicle_type=vehicle_type,
            airframe=airframe,
        )
    except ValueError as exc:
        raise _bad_catalog_request(exc) from exc
    return ok(payload)


@router.post("/validate")
def validate_parameter_search_space(
    request: SearchValidationRequest,
) -> dict[str, object]:
    """Validate selected names, hard/safe bounds, duplicates, and couplings."""

    try:
        normalized_version = normalize_px4_version(request.px4_version)
        resolve_catalog_version(
            request.catalog_version,
            px4_version=normalized_version,
        )
        normalized_vehicle = normalize_vehicle_type(request.vehicle_type)
        family = classify_airframe(request.airframe)
        active = [
            selection
            for selection in request.selections
            if selection.enabled and not selection.locked
        ]
        result = validate_search_selections(
            (selection.model_dump() for selection in active),
            px4_version=normalized_version,
            catalog_version=request.catalog_version,
            vehicle_type=normalized_vehicle,
            airframe=request.airframe,
            enforce_safe_bounds=request.enforce_safe_bounds,
        )
        normalized_names = [selection.name.strip().upper() for selection in request.selections]
        enabled_names = {
            selection.name.strip().upper()
            for selection in request.selections
            if selection.enabled
        }
        enabled_selection_by_name = {
            selection.name.strip().upper(): selection
            for selection in request.selections
            if selection.enabled
        }
        coupling_errors: list[ValidationIssue] = []
        coupling_warnings: list[ValidationIssue] = []
        error_keys = {
            (issue.code, issue.parameter, issue.field, issue.related_parameter)
            for issue in result.errors
        }
        warning_keys = {
            (issue.code, issue.parameter, issue.field, issue.related_parameter)
            for issue in result.warnings
        }

        def add_coupling_error(issue: ValidationIssue) -> None:
            key = (issue.code, issue.parameter, issue.field, issue.related_parameter)
            if key not in error_keys:
                error_keys.add(key)
                coupling_errors.append(issue)

        def add_coupling_warning(issue: ValidationIssue) -> None:
            key = (issue.code, issue.parameter, issue.field, issue.related_parameter)
            if key not in warning_keys:
                warning_keys.add(key)
                coupling_warnings.append(issue)

        for name in set(normalized_names):
            if normalized_names.count(name) > 1:
                add_coupling_error(
                    ValidationIssue(
                        "DUPLICATE_PARAMETER",
                        f"{name} was selected more than once",
                        name,
                    )
                )

        for selection in request.selections:
            name = selection.name.strip().upper()
            definition = get_parameter(
                name,
                px4_version=normalized_version,
                vehicle_type=normalized_vehicle,
                airframe=request.airframe,
            )
            if definition is None:
                add_coupling_error(
                    ValidationIssue(
                        "UNKNOWN_PARAMETER",
                        f"{name} is not in the DroneDream PX4 catalog",
                        name,
                    )
                )
                continue
            if not selection.enabled:
                continue
            if selection.locked and selection.initial_value is None:
                add_coupling_error(
                    ValidationIssue(
                        "LOCKED_VALUE_REQUIRED",
                        f"{name} requires an initial_value when it is locked",
                        name,
                        "initial_value",
                    )
                )
            for dependency in definition.dependencies:
                if (
                    dependency.kind != "recommended_with"
                    and dependency.parameter not in enabled_names
                ):
                    add_coupling_error(
                        ValidationIssue(
                            "CONSTRAINT_PARAMETER_NOT_SELECTED",
                            (
                                f"{name} requires coupled parameter "
                                f"{dependency.parameter} to be enabled or locked"
                            ),
                            name,
                            related_parameter=dependency.parameter,
                        )
                    )
                    continue
                if dependency.kind == "recommended_with":
                    continue
                counterpart = enabled_selection_by_name[dependency.parameter]
                if selection.locked == counterpart.locked:
                    continue
                locked_selection = selection if selection.locked else counterpart
                if locked_selection.initial_value is None:
                    continue
                selection_min = (
                    selection.initial_value if selection.locked else selection.search_min
                )
                selection_max = (
                    selection.initial_value if selection.locked else selection.search_max
                )
                counterpart_min = (
                    counterpart.initial_value if counterpart.locked else counterpart.search_min
                )
                counterpart_max = (
                    counterpart.initial_value if counterpart.locked else counterpart.search_max
                )
                assert selection_min is not None
                assert selection_max is not None
                assert counterpart_min is not None
                assert counterpart_max is not None
                less_equal = dependency.kind == "less_than_or_equal"
                impossible = (less_equal and selection_min > counterpart_max) or (
                    not less_equal and selection_max < counterpart_min
                )
                may_violate = (less_equal and selection_max > counterpart_min) or (
                    not less_equal and selection_min < counterpart_max
                )
                operator = "<=" if less_equal else ">="
                if impossible:
                    add_coupling_error(
                        ValidationIssue(
                            "DEPENDENCY_RANGE_VIOLATION",
                            (
                                f"{name} can never satisfy {operator} "
                                f"{dependency.parameter} within the selected intervals"
                            ),
                            name,
                            "search_bounds",
                            related_parameter=dependency.parameter,
                        )
                    )
                elif may_violate:
                    add_coupling_warning(
                        ValidationIssue(
                            "DEPENDENCY_RANGE_MAY_VIOLATE",
                            (
                                f"Some combinations can violate {name} {operator} "
                                f"{dependency.parameter}; candidate generation will reject them"
                            ),
                            name,
                            "search_bounds",
                            related_parameter=dependency.parameter,
                        )
                    )

        enabled_baselines = {
            selection.name.strip().upper(): selection.initial_value
            for selection in request.selections
            if selection.enabled and selection.initial_value is not None
        }
        try:
            validate_parameter_values(
                enabled_baselines,
                px4_version=normalized_version,
                catalog_version=request.catalog_version,
                vehicle_type=normalized_vehicle,
                airframe=request.airframe,
                enforce_safe_bounds=request.enforce_safe_bounds,
            )
        except ParameterValueValidationError as exc:
            for issue in exc.issues:
                if issue.code == "DEPENDENCY_VIOLATION":
                    issue = ValidationIssue(
                        "DEPENDENCY_BASELINE_VIOLATION",
                        issue.message.replace(" must be ", " baseline must be ", 1),
                        issue.parameter,
                        "initial_value",
                        related_parameter=issue.related_parameter,
                    )
                add_coupling_error(issue)

        errors = (*result.errors, *coupling_errors)
        result = SelectionValidationResult(
            valid=not errors,
            normalized=result.normalized,
            errors=errors,
            warnings=(
                *(
                    warning
                    for warning in result.warnings
                    if warning.code != "CONSTRAINT_PARAMETER_NOT_SELECTED"
                    and not (
                        warning.code == "RECOMMENDED_PARAMETER_NOT_SELECTED"
                        and warning.related_parameter in enabled_names
                    )
                ),
                *coupling_warnings,
            ),
        )
    except ValueError as exc:
        raise _bad_catalog_request(exc) from exc
    return ok(
        {
            "catalog_version": CATALOG_VERSION,
            "requested_catalog_version": request.catalog_version,
            "px4_version": normalized_version,
            "vehicle_type": normalized_vehicle,
            "airframe": request.airframe,
            "airframe_family": family,
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
    vehicle_type: str = Query(default="multicopter"),
    airframe: str = Query(default="x500"),
) -> dict[str, object]:
    """Read one catalog entry by its real PX4 parameter name."""

    try:
        normalized_version = normalize_px4_version(px4_version)
        normalized_vehicle = normalize_vehicle_type(vehicle_type)
        family = classify_airframe(airframe)
        parameter = get_parameter(
            parameter_name,
            px4_version=normalized_version,
            vehicle_type=normalized_vehicle,
            airframe=airframe,
        )
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
            "vehicle_type": normalized_vehicle,
            "airframe": airframe,
            "airframe_family": family,
            "parameter": parameter.to_dict(),
        }
    )
