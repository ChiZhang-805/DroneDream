"""Safety and search-space validation for PX4 parameter selections."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from app.parameters.catalog import get_parameter, normalize_px4_version
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
    enforce_safe_bounds: bool = True,
) -> dict[str, Number]:
    """Validate one concrete PX4 parameter set and return normalized values."""

    normalized_version = normalize_px4_version(px4_version)
    normalized: dict[str, Number] = {}
    issues: list[ValidationIssue] = []
    for raw_name, raw_value in values.items():
        name = str(raw_name).strip().upper()
        definition = get_parameter(name, px4_version=normalized_version)
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
        normalized[name] = value

    if (
        "MPC_ACC_HOR" in normalized
        and "MPC_ACC_HOR_MAX" in normalized
        and normalized["MPC_ACC_HOR"] > normalized["MPC_ACC_HOR_MAX"]
    ):
        issues.append(
            ValidationIssue(
                code="DEPENDENCY_VIOLATION",
                message="MPC_ACC_HOR must be less than or equal to MPC_ACC_HOR_MAX",
                parameter="MPC_ACC_HOR",
                field="value",
            )
        )
    if issues:
        raise ParameterValueValidationError(issues)
    return normalized


def validate_search_selections(
    selections: Iterable[Mapping[str, Any]],
    *,
    px4_version: str | None = None,
    enforce_safe_bounds: bool = True,
) -> SelectionValidationResult:
    """Validate selected parameters and their optimizer search intervals."""

    normalized_version = normalize_px4_version(px4_version)
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
        definition = get_parameter(name, px4_version=normalized_version)
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
        if declared_type is not None and str(declared_type) != definition.value_type:
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
        normalized.append(ParameterSelection(name, search_min, search_max, initial))

    selected_names = {selection.name for selection in normalized}
    for selection in normalized:
        definition = get_parameter(selection.name, px4_version=normalized_version)
        assert definition is not None
        for dependency in definition.dependencies:
            if dependency.kind == "recommended_with" and dependency.parameter not in selected_names:
                warnings.append(
                    ValidationIssue(
                        "RECOMMENDED_PARAMETER_NOT_SELECTED",
                        f"{selection.name} is normally validated with {dependency.parameter}",
                        selection.name,
                    )
                )

    return SelectionValidationResult(
        valid=not errors,
        normalized=tuple(normalized),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )
