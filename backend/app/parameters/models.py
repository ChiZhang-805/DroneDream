"""Domain models for the versioned PX4 parameter catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Number = int | float
ParameterValueType = Literal["float", "int"]
ParameterRisk = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class LocalizedText:
    """English and Simplified Chinese copy shipped to API clients."""

    en: str
    zh_cn: str

    def to_dict(self) -> dict[str, str]:
        return {"en": self.en, "zh-CN": self.zh_cn}


@dataclass(frozen=True)
class Bounds:
    """Inclusive numeric bounds."""

    minimum: Number
    maximum: Number

    def contains(self, value: Number) -> bool:
        return self.minimum <= value <= self.maximum

    def to_dict(self) -> dict[str, Number]:
        return {"min": self.minimum, "max": self.maximum}


@dataclass(frozen=True)
class ParameterDependency:
    """A coupling or ordering rule involving another PX4 parameter."""

    kind: Literal["recommended_with", "less_than_or_equal"]
    parameter: str
    description: LocalizedText

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "parameter": self.parameter,
            "description": self.description.to_dict(),
        }


@dataclass(frozen=True)
class ParameterDefinition:
    """One tunable, real PX4 parameter and DroneDream's safety envelope."""

    name: str
    value_type: ParameterValueType
    unit: str
    hard_bounds: Bounds
    safe_bounds: Bounds
    step: Number
    default: Number
    group: str
    risk: ParameterRisk
    requires_reboot: bool
    label: LocalizedText
    description: LocalizedText
    dependencies: tuple[ParameterDependency, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "type": self.value_type,
            "unit": self.unit,
            "hard_bounds": self.hard_bounds.to_dict(),
            "safe_bounds": self.safe_bounds.to_dict(),
            "step": self.step,
            "default": self.default,
            "group": self.group,
            "risk": self.risk,
            "requires_reboot": self.requires_reboot,
            "label": self.label.to_dict(),
            "description": self.description.to_dict(),
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
        }


@dataclass(frozen=True)
class ValidationIssue:
    """Machine-readable validation feedback suitable for a form UI."""

    code: str
    message: str
    parameter: str | None = None
    field: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "parameter": self.parameter,
            "field": self.field,
        }


@dataclass(frozen=True)
class ParameterSelection:
    """User-selected search interval for one parameter."""

    name: str
    search_min: Number
    search_max: Number
    initial_value: Number | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "search_min": self.search_min,
            "search_max": self.search_max,
            "initial_value": self.initial_value,
        }


@dataclass(frozen=True)
class SelectionValidationResult:
    """Validated selections plus errors and non-blocking safety warnings."""

    valid: bool
    normalized: tuple[ParameterSelection, ...]
    errors: tuple[ValidationIssue, ...]
    warnings: tuple[ValidationIssue, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "normalized": [item.to_dict() for item in self.normalized],
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
        }
