"""Typed parameter-domain projection and normalization."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from app.schemas import ParameterSelection


@dataclass(frozen=True)
class ParameterDomain:
    name: str
    baseline: float
    minimum: float
    maximum: float
    step: float | None = None
    scale: str = "linear"
    value_type: str = "float"
    choices: tuple[float, ...] = ()
    enabled: bool = True
    locked: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("parameter domain name must be a non-empty string")
        numeric_fields = {
            "baseline": self.baseline,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }
        if any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
            for value in numeric_fields.values()
        ):
            raise ValueError("parameter domain bounds and baseline must be finite numbers")
        if self.minimum > self.maximum:
            raise ValueError("parameter domain minimum cannot exceed maximum")
        if not self.minimum <= self.baseline <= self.maximum:
            raise ValueError("parameter domain baseline must be inside its bounds")
        if self.step is not None and (
            isinstance(self.step, bool)
            or not isinstance(self.step, int | float)
            or not math.isfinite(float(self.step))
            or self.step <= 0
        ):
            raise ValueError("parameter domain step must be finite and > 0")
        if self.scale not in {"linear", "log"}:
            raise ValueError("parameter domain scale must be linear or log")
        if self.scale == "log" and self.minimum <= 0:
            raise ValueError("log-scaled parameter domains require a positive minimum")
        if self.value_type not in {"float", "integer", "boolean", "enum"}:
            raise ValueError("unsupported parameter domain value_type")
        if any(
            isinstance(choice, bool)
            or not isinstance(choice, int | float)
            or not math.isfinite(float(choice))
            or not self.minimum <= float(choice) <= self.maximum
            for choice in self.choices
        ):
            raise ValueError("parameter choices must be finite and inside the bounds")
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("parameter choices must be unique")

    @classmethod
    def from_schema(cls, value: ParameterSelection) -> ParameterDomain:
        return cls(
            name=value.name,
            baseline=value.baseline,
            minimum=value.minimum,
            maximum=value.maximum,
            step=value.step,
            scale=value.scale,
            value_type=value.value_type,
            choices=tuple(value.choices or ()),
            enabled=value.enabled,
            locked=value.locked,
        )

    @property
    def tunable(self) -> bool:
        return self.enabled and not self.locked and self.minimum < self.maximum

    def from_unit(self, unit_value: float) -> float:
        """Map a value in [0, 1] to the parameter's native domain."""

        if (
            isinstance(unit_value, bool)
            or not isinstance(unit_value, int | float)
            or not math.isfinite(float(unit_value))
        ):
            raise ValueError(f"{self.name} unit coordinate must be finite")
        unit = max(0.0, min(1.0, float(unit_value)))
        if not self.tunable:
            return self.project(self.baseline)
        if self.choices:
            index = min(len(self.choices) - 1, int(unit * len(self.choices)))
            return self.project(self.choices[index])
        if self.scale == "log":
            low = math.log(self.minimum)
            high = math.log(self.maximum)
            return self.project(math.exp(low + unit * (high - low)))
        return self.project(self.minimum + unit * (self.maximum - self.minimum))

    def to_unit(self, raw_value: float) -> float:
        value = self.project(raw_value)
        if self.maximum == self.minimum:
            return 0.0
        if self.choices:
            if len(self.choices) == 1:
                return 0.0
            index = min(
                range(len(self.choices)), key=lambda idx: abs(self.choices[idx] - value)
            )
            return index / (len(self.choices) - 1)
        if self.scale == "log":
            return (math.log(value) - math.log(self.minimum)) / (
                math.log(self.maximum) - math.log(self.minimum)
            )
        return (value - self.minimum) / (self.maximum - self.minimum)

    def project(self, raw_value: float) -> float:
        """Clamp and snap an arbitrary proposal to a firmware-valid value."""

        if (
            isinstance(raw_value, bool)
            or not isinstance(raw_value, int | float)
            or not math.isfinite(float(raw_value))
        ):
            raise ValueError(f"{self.name} must be finite")
        value = max(self.minimum, min(self.maximum, float(raw_value)))
        if self.choices:
            value = min(self.choices, key=lambda choice: (abs(choice - value), choice))
        elif self.step is not None:
            steps = round((value - self.minimum) / self.step)
            value = self.minimum + steps * self.step
            value = max(self.minimum, min(self.maximum, value))
        if self.value_type in {"integer", "boolean", "enum"}:
            value = float(round(value))
        return round(value, 12)


class SearchSpace:
    """Ordered collection of independent numeric PX4 parameter domains."""

    def __init__(
        self,
        domains: Sequence[ParameterDomain],
        *,
        candidate_validator: Callable[[Mapping[str, float]], None] | None = None,
    ) -> None:
        if not domains:
            raise ValueError("search space requires at least one parameter")
        names = [domain.name for domain in domains]
        if len(set(names)) != len(names):
            raise ValueError("parameter names must be unique")
        self.domains = tuple(domains)
        self._by_name = {domain.name: domain for domain in self.domains}
        self._candidate_validator = candidate_validator

    @classmethod
    def from_schema(
        cls,
        parameters: Sequence[ParameterSelection],
        *,
        candidate_validator: Callable[[Mapping[str, float]], None] | None = None,
    ) -> SearchSpace:
        return cls(
            [ParameterDomain.from_schema(parameter) for parameter in parameters],
            candidate_validator=candidate_validator,
        )

    @property
    def tunable(self) -> tuple[ParameterDomain, ...]:
        return tuple(domain for domain in self.domains if domain.tunable)

    def baseline(self) -> dict[str, float]:
        candidate = {
            domain.name: domain.project(domain.baseline) for domain in self.domains
        }
        self._validate(candidate)
        return candidate

    def from_unit_vector(self, values: Sequence[float]) -> dict[str, float]:
        if len(values) != len(self.tunable):
            raise ValueError(
                f"expected {len(self.tunable)} unit values, received {len(values)}"
            )
        candidate = self.baseline()
        for domain, unit_value in zip(self.tunable, values, strict=True):
            candidate[domain.name] = domain.from_unit(unit_value)
        self._validate(candidate)
        return candidate

    def to_unit_vector(self, candidate: Mapping[str, float]) -> tuple[float, ...]:
        return tuple(
            domain.to_unit(candidate.get(domain.name, domain.baseline))
            for domain in self.tunable
        )

    def project(self, candidate: Mapping[str, float]) -> dict[str, float]:
        unknown = set(candidate).difference(self._by_name)
        if unknown:
            raise ValueError(f"unknown parameters: {', '.join(sorted(unknown))}")
        projected = {
            domain.name: domain.project(
                domain.baseline
                if not domain.tunable
                else candidate.get(domain.name, domain.baseline)
            )
            for domain in self.domains
        }
        self._validate(projected)
        return projected

    def _validate(self, candidate: Mapping[str, float]) -> None:
        if self._candidate_validator is not None:
            self._candidate_validator(candidate)

    def normalized_distance(
        self, first: Mapping[str, float], second: Mapping[str, float]
    ) -> float:
        first_vector = self.to_unit_vector(first)
        second_vector = self.to_unit_vector(second)
        if not first_vector:
            return 0.0
        squared = sum(
            (left - right) ** 2
            for left, right in zip(first_vector, second_vector, strict=True)
        )
        return math.sqrt(squared / len(first_vector))


__all__ = ["ParameterDomain", "SearchSpace"]
