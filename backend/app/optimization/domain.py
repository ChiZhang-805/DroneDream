"""Typed parameter-domain projection and normalization."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
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

        if not math.isfinite(raw_value):
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

    def __init__(self, domains: Sequence[ParameterDomain]) -> None:
        if not domains:
            raise ValueError("search space requires at least one parameter")
        names = [domain.name for domain in domains]
        if len(set(names)) != len(names):
            raise ValueError("parameter names must be unique")
        self.domains = tuple(domains)
        self._by_name = {domain.name: domain for domain in self.domains}

    @classmethod
    def from_schema(cls, parameters: Sequence[ParameterSelection]) -> SearchSpace:
        return cls([ParameterDomain.from_schema(parameter) for parameter in parameters])

    @property
    def tunable(self) -> tuple[ParameterDomain, ...]:
        return tuple(domain for domain in self.domains if domain.tunable)

    def baseline(self) -> dict[str, float]:
        return {domain.name: domain.project(domain.baseline) for domain in self.domains}

    def from_unit_vector(self, values: Sequence[float]) -> dict[str, float]:
        if len(values) != len(self.tunable):
            raise ValueError(
                f"expected {len(self.tunable)} unit values, received {len(values)}"
            )
        candidate = self.baseline()
        for domain, unit_value in zip(self.tunable, values, strict=True):
            candidate[domain.name] = domain.from_unit(unit_value)
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
        return {
            domain.name: domain.project(
                domain.baseline
                if not domain.tunable
                else candidate.get(domain.name, domain.baseline)
            )
            for domain in self.domains
        }

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
