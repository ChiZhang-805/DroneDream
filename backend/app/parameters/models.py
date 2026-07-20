"""Domain models for the versioned PX4 parameter catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Number = int | float
ParameterValueType = Literal["float", "int"]
ParameterRisk = Literal["low", "medium", "high"]
ParameterExpertise = Literal["guided", "advanced", "expert"]
ParameterApplyPolicy = Literal["live", "disarmed", "reboot"]
ParameterDependencyKind = Literal[
    "recommended_with",
    "less_than_or_equal",
    "greater_than_or_equal",
]


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

    kind: ParameterDependencyKind
    parameter: str
    description: LocalizedText

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "parameter": self.parameter,
            "description": self.description.to_dict(),
        }


@dataclass(frozen=True)
class ParameterCompatibility:
    """Firmware and vehicle contexts in which a catalog entry is valid."""

    px4_versions: tuple[str, ...]
    vehicle_types: tuple[str, ...]
    airframe_families: tuple[str, ...]

    def supports(
        self,
        *,
        px4_version: str,
        vehicle_type: str,
        airframe_family: str,
    ) -> bool:
        return (
            px4_version in self.px4_versions
            and vehicle_type in self.vehicle_types
            and airframe_family in self.airframe_families
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "px4_versions": list(self.px4_versions),
            "vehicle_types": list(self.vehicle_types),
            "airframe_families": list(self.airframe_families),
        }


@dataclass(frozen=True)
class ParameterChoice:
    """One labelled discrete value for an integer PX4 parameter."""

    value: Number
    label: LocalizedText

    def to_dict(self) -> dict[str, object]:
        return {"value": self.value, "label": self.label.to_dict()}


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
    control_loop: str = "other"
    axes: tuple[str, ...] = field(default_factory=tuple)
    tuning_stage: int = 100
    expertise: ParameterExpertise = "advanced"
    apply_policy: ParameterApplyPolicy = "live"
    compatibility: ParameterCompatibility = field(
        default_factory=lambda: ParameterCompatibility(
            px4_versions=("v1.16", "v1.17", "main"),
            vehicle_types=("multicopter",),
            airframe_families=(
                "quadrotor",
                "hexarotor",
                "octocopter",
                "custom_multicopter",
            ),
        )
    )
    application_interfaces: tuple[str, ...] = ("mavsdk", "px4_startup_env")
    recommended_metrics: tuple[str, ...] = field(default_factory=tuple)
    evidence_signals: tuple[str, ...] = field(default_factory=tuple)
    flight_modes: tuple[str, ...] = field(default_factory=tuple)
    preconditions: tuple[str, ...] = field(default_factory=tuple)
    risk_note: LocalizedText | None = None
    source_url: str | None = None
    bounds_source: Literal["px4", "px4_and_dronedream_guardrail"] = "px4"
    choices: tuple[ParameterChoice, ...] = field(default_factory=tuple)

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
            "control_loop": self.control_loop,
            "axes": list(self.axes),
            "tuning_stage": self.tuning_stage,
            "expertise": self.expertise,
            "apply_policy": self.apply_policy,
            "compatibility": self.compatibility.to_dict(),
            "application_interfaces": list(self.application_interfaces),
            "recommended_metrics": list(self.recommended_metrics),
            "evidence_signals": list(self.evidence_signals),
            "flight_modes": list(self.flight_modes),
            "preconditions": list(self.preconditions),
            "risk_note": self.risk_note.to_dict() if self.risk_note else None,
            "source_url": self.source_url,
            "bounds_source": self.bounds_source,
            "choices": [choice.to_dict() for choice in self.choices],
        }


@dataclass(frozen=True)
class TuningPreset:
    """A catalog-owned, ordered starting point for a guided tuning workflow."""

    id: str
    order: int
    label: LocalizedText
    description: LocalizedText
    parameter_names: tuple[str, ...]
    prerequisites: tuple[str, ...]
    scenario_types: tuple[str, ...]
    metrics: tuple[str, ...]
    expertise: ParameterExpertise
    recommended_iterations: int
    follows: tuple[str, ...] = field(default_factory=tuple)
    locked_parameters: tuple[str, ...] = field(default_factory=tuple)
    evidence_signals: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "order": self.order,
            "label": self.label.to_dict(),
            "description": self.description.to_dict(),
            "parameter_names": list(self.parameter_names),
            "prerequisites": list(self.prerequisites),
            "scenario_types": list(self.scenario_types),
            "metrics": list(self.metrics),
            "expertise": self.expertise,
            "recommended_iterations": self.recommended_iterations,
            "follows": list(self.follows),
            "locked_parameters": list(self.locked_parameters),
            "evidence_signals": list(self.evidence_signals),
        }


@dataclass(frozen=True)
class ValidationIssue:
    """Machine-readable validation feedback suitable for a form UI."""

    code: str
    message: str
    parameter: str | None = None
    field: str | None = None
    related_parameter: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "parameter": self.parameter,
            "field": self.field,
            "related_parameter": self.related_parameter,
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
