"""Safety and search-space validation for PX4 parameter selections."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from app.parameters.catalog import (
    classify_airframe,
    get_parameter,
    normalize_px4_version,
    normalize_vehicle_type,
    resolve_catalog_version,
)
from app.parameters.models import (
    Number,
    ParameterSelection,
    SelectionValidationResult,
    ValidationIssue,
)


class ParameterValueValidationError(ValueError):
    """Raised when a concrete PX4 parameter request is unsafe or malformed."""

    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(f"{issue.code}: {issue.message}" for issue in self.issues))


def _coerce_number(value: Any, *, value_type: str) -> Number:
    if isinstance(value, bool):
        raise ValueError("boolean is not a parameter number")
    number: Number
    if value_type == "int":
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("integer parameter cannot contain a fractional value")
        number = int(value)
    else:
        number = float(value)
    if not math.isfinite(float(number)):
        raise ValueError("parameter value must be finite")
    return number


def validate_parameter_values(
    values: Mapping[str, Any],
    *,
    px4_version: str | None = None,
    catalog_version: str | None = None,
    vehicle_type: str | None = None,
    airframe: str | None = None,
    enforce_safe_bounds: bool = True,
) -> dict[str, Number]:
    """Validate one concrete PX4 parameter set and return normalized values."""

    normalized_version = normalize_px4_version(px4_version)
    resolve_catalog_version(catalog_version, px4_version=normalized_version)
    normalized_vehicle = normalize_vehicle_type(vehicle_type)
    classify_airframe(airframe)
    normalized: dict[str, Number] = {}
    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for raw_name, raw_value in values.items():
        name = str(raw_name).strip().upper()
        if name in seen:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_PARAMETER",
                    message=f"{name} was provided more than once after normalization",
                    parameter=name,
                )
            )
            continue
        seen.add(name)
        definition = get_parameter(
            name,
            px4_version=normalized_version,
            vehicle_type=normalized_vehicle,
            airframe=airframe,
        )
        if definition is None:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_PARAMETER",
                    message=f"{name} is not in the DroneDream PX4 catalog",
                    parameter=name,
                )
            )
            continue
        try:
            value = _coerce_number(raw_value, value_type=definition.value_type)
        except (TypeError, ValueError) as exc:
            issues.append(
                ValidationIssue(
                    code="INVALID_VALUE",
                    message=f"{name}: {exc}",
                    parameter=name,
                    field="value",
                )
            )
            continue
        bounds = definition.safe_bounds if enforce_safe_bounds else definition.hard_bounds
        if not bounds.contains(value):
            bound_name = "safe" if enforce_safe_bounds else "hard"
            issues.append(
                ValidationIssue(
                    code=f"OUTSIDE_{bound_name.upper()}_BOUNDS",
                    message=(
                        f"{name}={value} is outside {bound_name} bounds "
                        f"[{bounds.minimum}, {bounds.maximum}]"
                    ),
                    parameter=name,
                    field="value",
                )
            )
            continue
        allowed_values = {choice.value for choice in definition.choices}
        if allowed_values and value not in allowed_values:
            issues.append(
                ValidationIssue(
                    code="INVALID_CHOICE",
                    message=f"{name}={value} is not one of {sorted(allowed_values)}",
                    parameter=name,
                    field="value",
                )
            )
            continue
        normalized[name] = value

    for name, value in normalized.items():
        definition = get_parameter(
            name,
            px4_version=normalized_version,
            vehicle_type=normalized_vehicle,
            airframe=airframe,
        )
        assert definition is not None
        for dependency in definition.dependencies:
            other = normalized.get(dependency.parameter)
            if other is None or dependency.kind == "recommended_with":
                continue
            violates = (dependency.kind == "less_than_or_equal" and value > other) or (
                dependency.kind == "greater_than_or_equal" and value < other
            )
            if violates:
                operator = "<=" if dependency.kind == "less_than_or_equal" else ">="
                issues.append(
                    ValidationIssue(
                        code="DEPENDENCY_VIOLATION",
                        message=f"{name} must be {operator} {dependency.parameter}",
                        parameter=name,
                        field="value",
                        related_parameter=dependency.parameter,
                    )
                )
    if issues:
        raise ParameterValueValidationError(issues)
    return normalized


def validate_search_selections(
    selections: Iterable[Mapping[str, Any]],
    *,
    px4_version: str | None = None,
    catalog_version: str | None = None,
    vehicle_type: str | None = None,
    airframe: str | None = None,
    enforce_safe_bounds: bool = True,
) -> SelectionValidationResult:
    """Validate selected parameters and their optimizer search intervals."""

    normalized_version = normalize_px4_version(px4_version)
    resolve_catalog_version(catalog_version, px4_version=normalized_version)
    normalized_vehicle = normalize_vehicle_type(vehicle_type)
    classify_airframe(airframe)
    normalized: list[ParameterSelection] = []
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    seen: set[str] = set()

    for raw in selections:
        name = str(raw.get("name", "")).strip().upper()
        if not name:
            errors.append(
                ValidationIssue("MISSING_NAME", "Parameter name is required", field="name")
            )
            continue
        if name in seen:
            errors.append(
                ValidationIssue("DUPLICATE_PARAMETER", f"{name} was selected more than once", name)
            )
            continue
        seen.add(name)
        definition = get_parameter(
            name,
            px4_version=normalized_version,
            vehicle_type=normalized_vehicle,
            airframe=airframe,
        )
        if definition is None:
            errors.append(
                ValidationIssue(
                    "UNKNOWN_PARAMETER",
                    f"{name} is not in the DroneDream PX4 catalog",
                    name,
                )
            )
            continue
        try:
            search_min = _coerce_number(raw.get("search_min"), value_type=definition.value_type)
            search_max = _coerce_number(raw.get("search_max"), value_type=definition.value_type)
            initial_raw = raw.get("initial_value")
            initial = (
                None
                if initial_raw is None
                else _coerce_number(initial_raw, value_type=definition.value_type)
            )
        except (TypeError, ValueError) as exc:
            errors.append(
                ValidationIssue("INVALID_NUMBER", f"{name}: {exc}", name, "search_bounds")
            )
            continue
        declared_type = raw.get("value_type")
        normalized_declared_type = (
            "int" if str(declared_type).lower() == "integer" else str(declared_type).lower()
        )
        if declared_type is not None and normalized_declared_type != definition.value_type:
            errors.append(
                ValidationIssue(
                    "TYPE_MISMATCH",
                    (f"{name} is a {definition.value_type} parameter, not {declared_type}"),
                    name,
                    "value_type",
                )
            )
            continue
        if search_min >= search_max:
            errors.append(
                ValidationIssue(
                    "INVALID_RANGE",
                    f"{name} search_min must be less than search_max",
                    name,
                    "search_bounds",
                )
            )
            continue
        scale = str(raw.get("scale") or "linear").lower()
        if scale not in {"linear", "log"}:
            errors.append(
                ValidationIssue(
                    "INVALID_SCALE",
                    f"{name} scale must be linear or log",
                    name,
                    "scale",
                )
            )
            continue
        if scale == "log" and search_min <= 0:
            errors.append(
                ValidationIssue(
                    "INVALID_LOG_RANGE",
                    f"{name} log search requires a positive minimum",
                    name,
                    "search_min",
                )
            )
            continue
        step_raw = raw.get("step")
        if step_raw is not None:
            try:
                selected_step = float(step_raw)
            except (TypeError, ValueError):
                errors.append(
                    ValidationIssue(
                        "INVALID_STEP",
                        f"{name} step must be numeric",
                        name,
                        "step",
                    )
                )
                continue
            if not math.isfinite(selected_step) or selected_step <= 0:
                errors.append(
                    ValidationIssue(
                        "INVALID_STEP",
                        f"{name} step must be finite and greater than zero",
                        name,
                        "step",
                    )
                )
                continue
            if selected_step > float(search_max) - float(search_min):
                errors.append(
                    ValidationIssue(
                        "STEP_EXCEEDS_RANGE",
                        f"{name} step exceeds the search interval",
                        name,
                        "step",
                    )
                )
                continue
            catalog_step = float(definition.step)
            ratio = selected_step / catalog_step
            if ratio < 1.0 - 1e-9 or not math.isclose(
                ratio, round(ratio), rel_tol=0.0, abs_tol=1e-8
            ):
                errors.append(
                    ValidationIssue(
                        "INVALID_STEP_INCREMENT",
                        (
                            f"{name} step must be a positive integer multiple "
                            f"of catalog step {catalog_step:g}"
                        ),
                        name,
                        "step",
                    )
                )
                continue
        if not definition.hard_bounds.contains(search_min) or not definition.hard_bounds.contains(
            search_max
        ):
            errors.append(
                ValidationIssue(
                    "OUTSIDE_HARD_BOUNDS",
                    (
                        f"{name} search bounds must stay within "
                        f"[{definition.hard_bounds.minimum}, {definition.hard_bounds.maximum}]"
                    ),
                    name,
                    "search_bounds",
                )
            )
            continue
        outside_safe = not definition.safe_bounds.contains(
            search_min
        ) or not definition.safe_bounds.contains(search_max)
        if outside_safe:
            issue = ValidationIssue(
                "OUTSIDE_SAFE_BOUNDS",
                (
                    f"{name} search bounds exceed the conservative interval "
                    f"[{definition.safe_bounds.minimum}, {definition.safe_bounds.maximum}]"
                ),
                name,
                "search_bounds",
            )
            if enforce_safe_bounds:
                errors.append(issue)
                continue
            warnings.append(issue)
        if initial is not None and not search_min <= initial <= search_max:
            errors.append(
                ValidationIssue(
                    "INITIAL_OUTSIDE_SEARCH_BOUNDS",
                    f"{name} initial_value must be inside its search interval",
                    name,
                    "initial_value",
                )
            )
            continue
        catalog_choices = {choice.value for choice in definition.choices}
        if catalog_choices and (
            search_min not in catalog_choices
            or search_max not in catalog_choices
            or (initial is not None and initial not in catalog_choices)
        ):
            errors.append(
                ValidationIssue(
                    "INVALID_CATALOG_CHOICE",
                    f"{name} bounds and initial value must use catalog choices",
                    name,
                    "choices",
                )
            )
            continue
        choices_raw = raw.get("choices")
        if choices_raw is not None:
            if not isinstance(choices_raw, list) or not choices_raw:
                errors.append(
                    ValidationIssue(
                        "INVALID_CHOICES",
                        f"{name} choices must be a non-empty list",
                        name,
                        "choices",
                    )
                )
                continue
            try:
                choices = [
                    _coerce_number(choice, value_type=definition.value_type)
                    for choice in choices_raw
                ]
            except (TypeError, ValueError) as exc:
                errors.append(ValidationIssue("INVALID_CHOICES", f"{name}: {exc}", name, "choices"))
                continue
            if len(set(choices)) != len(choices):
                errors.append(
                    ValidationIssue(
                        "DUPLICATE_CHOICES",
                        f"{name} choices must be unique",
                        name,
                        "choices",
                    )
                )
                continue
            if any(choice < search_min or choice > search_max for choice in choices):
                errors.append(
                    ValidationIssue(
                        "CHOICE_OUTSIDE_SEARCH_BOUNDS",
                        f"{name} choices must stay inside its search interval",
                        name,
                        "choices",
                    )
                )
                continue
            if initial is not None and initial not in choices:
                errors.append(
                    ValidationIssue(
                        "INITIAL_NOT_IN_CHOICES",
                        f"{name} initial_value must be one of choices",
                        name,
                        "initial_value",
                    )
                )
                continue
            if catalog_choices and not set(choices).issubset(catalog_choices):
                errors.append(
                    ValidationIssue(
                        "UNKNOWN_CATALOG_CHOICE",
                        f"{name} choices contain values not defined by the catalog",
                        name,
                        "choices",
                    )
                )
                continue
        normalized.append(ParameterSelection(name, search_min, search_max, initial))

    if not normalized and not errors:
        errors.append(
            ValidationIssue(
                "NO_TUNABLE_PARAMETERS",
                "At least one valid tunable parameter is required",
                field="selections",
            )
        )

    selected = {selection.name: selection for selection in normalized}
    selected_names = set(selected)
    for selection in normalized:
        definition = get_parameter(
            selection.name,
            px4_version=normalized_version,
            vehicle_type=normalized_vehicle,
            airframe=airframe,
        )
        assert definition is not None
        for dependency in definition.dependencies:
            if dependency.kind == "recommended_with" and dependency.parameter not in selected_names:
                warnings.append(
                    ValidationIssue(
                        "RECOMMENDED_PARAMETER_NOT_SELECTED",
                        f"{selection.name} is normally validated with {dependency.parameter}",
                        selection.name,
                        related_parameter=dependency.parameter,
                    )
                )
                continue
            if dependency.kind == "recommended_with":
                continue
            counterpart = selected.get(dependency.parameter)
            if counterpart is None:
                warnings.append(
                    ValidationIssue(
                        "CONSTRAINT_PARAMETER_NOT_SELECTED",
                        (
                            f"{selection.name} has a {dependency.kind} constraint on "
                            f"{dependency.parameter}; its fixed runtime value must also be checked"
                        ),
                        selection.name,
                        related_parameter=dependency.parameter,
                    )
                )
                continue
            less_equal = dependency.kind == "less_than_or_equal"
            impossible = (less_equal and selection.search_min > counterpart.search_max) or (
                not less_equal and selection.search_max < counterpart.search_min
            )
            may_violate = (less_equal and selection.search_max > counterpart.search_min) or (
                not less_equal and selection.search_min < counterpart.search_max
            )
            baseline_violation = (
                selection.initial_value is not None
                and counterpart.initial_value is not None
                and (
                    (less_equal and selection.initial_value > counterpart.initial_value)
                    or (not less_equal and selection.initial_value < counterpart.initial_value)
                )
            )
            operator = "<=" if less_equal else ">="
            if impossible:
                errors.append(
                    ValidationIssue(
                        "DEPENDENCY_RANGE_VIOLATION",
                        (
                            f"{selection.name} can never satisfy {operator} "
                            f"{dependency.parameter} within the selected intervals"
                        ),
                        selection.name,
                        "search_bounds",
                        related_parameter=dependency.parameter,
                    )
                )
            elif baseline_violation:
                errors.append(
                    ValidationIssue(
                        "DEPENDENCY_BASELINE_VIOLATION",
                        f"{selection.name} baseline must be {operator} {dependency.parameter}",
                        selection.name,
                        "initial_value",
                        related_parameter=dependency.parameter,
                    )
                )
            elif may_violate:
                warnings.append(
                    ValidationIssue(
                        "DEPENDENCY_RANGE_MAY_VIOLATE",
                        (
                            f"Some combinations can violate {selection.name} {operator} "
                            f"{dependency.parameter}; candidate application will reject them"
                        ),
                        selection.name,
                        "search_bounds",
                        related_parameter=dependency.parameter,
                    )
                )

    return SelectionValidationResult(
        valid=not errors,
        normalized=tuple(normalized),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )
