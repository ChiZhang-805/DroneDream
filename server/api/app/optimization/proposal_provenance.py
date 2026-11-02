"""Content-addressed provenance for optimizer proposal ownership and reward.

The numerical optimizer metadata is useful diagnostic state, but mutable string
fields must not decide which portfolio child receives credit.  This module
compiles the authoritative orchestration strategy, projected parameter vector,
fidelity, and closed generator role into one verifiable evidence envelope.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.optimization.domain import SearchSpace
from app.optimization.experimental_types import (
    EXPERIMENTAL_OPTIMIZER_STRATEGIES,
    ExperimentalOptimizerStrategy,
    OptimizerObservation,
)

OPTIMIZER_SOURCE_EVIDENCE_SCHEMA: Literal["dronedream.optimizer-source-evidence/v2"] = (
    "dronedream.optimizer-source-evidence/v2"
)
PORTFOLIO_SOURCES_V2_SCHEMA: Literal["dronedream.portfolio-sources/v2"] = (
    "dronedream.portfolio-sources/v2"
)
OPTIMIZER_SOURCE_EVIDENCE_FIELD = "optimizer_source_evidence"
OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD = "optimizer_source_evidence_required"

OptimizerSourceRole = Literal[
    "native_optimizer",
    "emergency_fallback",
    "projected_baseline",
    "unsupported_generator",
]
Sha256Id = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
PositiveUnitFloat = Annotated[float, Field(gt=0.0, le=1.0)]
NonnegativeInt = Annotated[int, Field(ge=0)]

_CHILD_STRATEGIES = frozenset(
    strategy for strategy in EXPERIMENTAL_OPTIMIZER_STRATEGIES if strategy != "optimizer_portfolio"
)
_EMERGENCY_GENERATORS = frozenset({"halton_fallback", "seeded_random_fallback"})


class OptimizerSourceEntryV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    child_strategy: Literal[
        "constrained_mobo",
        "multi_fidelity_mobo",
        "turbo",
        "saasbo",
        "surrogate_cma_es",
        "bipop_cma_es",
    ]
    source_role: OptimizerSourceRole
    generated_by: str = Field(min_length=1, max_length=96)
    planned_slot_role: str = Field(min_length=1, max_length=64)
    effective_fidelity: PositiveUnitFloat
    requested_fidelity: PositiveUnitFloat
    materialized: bool
    exclusion_reason: str | None = Field(default=None, min_length=1, max_length=96)

    @model_validator(mode="after")
    def _validate_role_and_materialization(self) -> OptimizerSourceEntryV1:
        expected_role = classify_optimizer_source_role(
            self.child_strategy,
            self.generated_by,
        )
        if self.source_role != expected_role:
            raise ValueError("optimizer source role does not match its generator")
        if self.materialized == (self.exclusion_reason is not None):
            raise ValueError("materialized optimizer sources alone have no exclusion reason")
        return self

    @property
    def reward_eligible(self) -> bool:
        return (
            self.materialized
            and self.exclusion_reason is None
            and self.source_role == "native_optimizer"
        )


class OptimizerSourceCreditV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    child_strategy: Literal[
        "constrained_mobo",
        "multi_fidelity_mobo",
        "turbo",
        "saasbo",
        "surrogate_cma_es",
        "bipop_cma_es",
    ]
    share: PositiveUnitFloat


class OptimizerSourceEvidenceV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_id: Literal["dronedream.optimizer-source-evidence/v2"] = (
        "dronedream.optimizer-source-evidence/v2"
    )
    evidence_id: Sha256Id
    strategy: ExperimentalOptimizerStrategy
    generation_index: NonnegativeInt
    parameter_sha256: Sha256Id
    search_space_sha256: Sha256Id
    sources: tuple[OptimizerSourceEntryV1, ...] = Field(min_length=1)
    learning_owner: (
        Literal[
            "constrained_mobo",
            "multi_fidelity_mobo",
            "turbo",
            "saasbo",
            "surrogate_cma_es",
            "bipop_cma_es",
        ]
        | None
    )
    reward_credits: tuple[OptimizerSourceCreditV1, ...]

    @model_validator(mode="after")
    def _validate_sources_and_credits(self) -> OptimizerSourceEvidenceV2:
        strategies = [source.child_strategy for source in self.sources]
        if len(strategies) != len(set(strategies)):
            raise ValueError("optimizer source strategies must be unique")
        if self.strategy != "optimizer_portfolio" and (
            len(self.sources) != 1 or self.sources[0].child_strategy != self.strategy
        ):
            raise ValueError("direct optimizer evidence must contain its one authoritative source")
        expected = [source.child_strategy for source in self.sources if source.reward_eligible]
        credited = [credit.child_strategy for credit in self.reward_credits]
        if credited != expected:
            raise ValueError(
                "optimizer reward credits must exactly match eligible materialized sources"
            )
        if expected:
            expected_share = 1.0 / len(expected)
            if any(
                not math.isclose(
                    credit.share,
                    expected_share,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                for credit in self.reward_credits
            ):
                raise ValueError("optimizer reward credit shares must be equal")
        elif self.reward_credits:
            raise ValueError("ineligible optimizer sources cannot receive reward")
        if expected and self.learning_owner not in expected:
            raise ValueError("optimizer learning owner must identify one eligible native source")
        if not expected and self.learning_owner is not None:
            raise ValueError("ineligible optimizer sources cannot own local learning state")
        return self


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_id(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def optimizer_search_space_sha256(
    search_space: SearchSpace,
    *,
    validator_contract: Mapping[str, Any] | None = None,
) -> str:
    """Freeze parameter domains plus the validator context used by a proposal."""

    return _sha256_id(
        {
            "schema_id": "dronedream.optimizer-search-space/v2",
            "validator_contract": dict(validator_contract or {}),
            "domains": [
                {
                    "ordinal": ordinal,
                    "name": domain.name,
                    "baseline": domain.baseline,
                    "minimum": domain.minimum,
                    "maximum": domain.maximum,
                    "step": domain.step,
                    "scale": domain.scale,
                    "value_type": domain.value_type,
                    "choices": list(domain.choices),
                    "enabled": domain.enabled,
                    "locked": domain.locked,
                    "tunable": domain.tunable,
                }
                for ordinal, domain in enumerate(search_space.domains)
            ],
        }
    )


def classify_optimizer_source_role(
    child_strategy: str,
    generated_by: str,
) -> OptimizerSourceRole:
    """Map a generator to one closed, reward-authoritative source role."""

    if generated_by == child_strategy:
        return "native_optimizer"
    if generated_by in _EMERGENCY_GENERATORS:
        return "emergency_fallback"
    if generated_by == "projected_baseline":
        return "projected_baseline"
    return "unsupported_generator"


def _finite_fidelity(value: object, *, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or not 0.0 < float(value) <= 1.0
    ):
        raise ValueError(f"{field_name} must be finite and inside (0, 1]")
    return float(value)


def _portfolio_sources(metadata: Mapping[str, Any]) -> tuple[OptimizerSourceEntryV1, ...]:
    if metadata.get("portfolio_sources_schema") != PORTFOLIO_SOURCES_V2_SCHEMA:
        raise ValueError("portfolio source evidence requires schema v2")
    raw_sources = metadata.get("portfolio_sources")
    if not isinstance(raw_sources, list | tuple) or not raw_sources:
        raise ValueError("portfolio source evidence requires source rows")
    sources: list[OptimizerSourceEntryV1] = []
    for raw in raw_sources:
        if not isinstance(raw, Mapping):
            raise ValueError("portfolio source rows must be mappings")
        sources.append(
            OptimizerSourceEntryV1.model_validate(
                {
                    "child_strategy": raw.get("child_strategy"),
                    "source_role": raw.get("source_role"),
                    "generated_by": raw.get("generated_by"),
                    "planned_slot_role": raw.get("planned_slot_role"),
                    "effective_fidelity": raw.get("effective_fidelity"),
                    "requested_fidelity": raw.get("requested_fidelity"),
                    "materialized": raw.get("materialized"),
                    "exclusion_reason": raw.get("exclusion_reason"),
                }
            )
        )
    return tuple(sources)


def _direct_source(
    *,
    strategy: ExperimentalOptimizerStrategy,
    metadata: Mapping[str, Any],
) -> tuple[OptimizerSourceEntryV1, ...]:
    if strategy == "optimizer_portfolio":
        raise ValueError("portfolio proposals require explicit source rows")
    generated_by = str(metadata.get("optimizer_generated_by", strategy))
    effective_fidelity = _finite_fidelity(
        metadata.get("effective_fidelity", metadata.get("fidelity", 1.0)),
        field_name="effective_fidelity",
    )
    requested_fidelity = _finite_fidelity(
        metadata.get("requested_fidelity", metadata.get("fidelity", 1.0)),
        field_name="requested_fidelity",
    )
    return (
        OptimizerSourceEntryV1(
            child_strategy=cast(Any, strategy),
            source_role=classify_optimizer_source_role(strategy, generated_by),
            generated_by=generated_by,
            planned_slot_role="direct",
            effective_fidelity=effective_fidelity,
            requested_fidelity=requested_fidelity,
            materialized=True,
            exclusion_reason=None,
        ),
    )


def compile_optimizer_source_evidence(
    *,
    strategy: ExperimentalOptimizerStrategy,
    generation_index: int,
    parameters: Mapping[str, float],
    search_space_sha256: str,
    metadata: Mapping[str, Any],
) -> OptimizerSourceEvidenceV2:
    """Compile the exact proposal ownership contract persisted on a Candidate."""

    sources = (
        _portfolio_sources(metadata)
        if strategy == "optimizer_portfolio"
        else _direct_source(strategy=strategy, metadata=metadata)
    )
    eligible = [source.child_strategy for source in sources if source.reward_eligible]
    share = 1.0 / len(eligible) if eligible else 0.0
    raw_learning_owner = (
        metadata.get("child_strategy")
        if strategy == "optimizer_portfolio"
        else sources[0].child_strategy
    )
    learning_owner = raw_learning_owner if raw_learning_owner in eligible else None
    payload: dict[str, Any] = {
        "schema_id": OPTIMIZER_SOURCE_EVIDENCE_SCHEMA,
        "strategy": strategy,
        "generation_index": generation_index,
        "parameter_sha256": _sha256_id(parameters),
        "search_space_sha256": search_space_sha256,
        "sources": [source.model_dump(mode="json") for source in sources],
        "learning_owner": learning_owner,
        "reward_credits": [
            {"child_strategy": child_strategy, "share": share} for child_strategy in eligible
        ],
    }
    return OptimizerSourceEvidenceV2.model_validate({"evidence_id": _sha256_id(payload), **payload})


def verify_optimizer_source_evidence(
    value: object,
    *,
    strategy: ExperimentalOptimizerStrategy,
    generation_index: int,
    parameters: Mapping[str, float],
    search_space_sha256: str | None = None,
    requested_fidelity: float | None = None,
    effective_fidelity: float | None = None,
) -> OptimizerSourceEvidenceV2 | None:
    """Verify content identity plus Candidate-bound proposal context."""

    try:
        evidence = OptimizerSourceEvidenceV2.model_validate(value)
    except ValidationError:
        return None
    payload = evidence.model_dump(mode="json")
    evidence_id = payload.pop("evidence_id")
    if (
        evidence_id != _sha256_id(payload)
        or evidence.strategy != strategy
        or evidence.generation_index != generation_index
        or evidence.parameter_sha256 != _sha256_id(parameters)
        or (search_space_sha256 is not None and evidence.search_space_sha256 != search_space_sha256)
    ):
        return None
    for expected, field_name in (
        (requested_fidelity, "requested_fidelity"),
        (effective_fidelity, "effective_fidelity"),
    ):
        if expected is None:
            continue
        try:
            expected_value = _finite_fidelity(
                expected,
                field_name=field_name,
            )
        except ValueError:
            return None
        if any(
            source.materialized
            and not math.isclose(
                getattr(source, field_name),
                expected_value,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for source in evidence.sources
        ):
            return None
    return evidence


def verified_observation_source_evidence(
    observation: OptimizerObservation,
) -> OptimizerSourceEvidenceV2 | None:
    metadata = observation.optimizer_metadata
    if (
        not isinstance(metadata, Mapping)
        or metadata.get(OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD) is not True
    ):
        return None
    raw_strategy = metadata.get("strategy")
    if raw_strategy not in EXPERIMENTAL_OPTIMIZER_STRATEGIES:
        return None
    return verify_optimizer_source_evidence(
        metadata.get(OPTIMIZER_SOURCE_EVIDENCE_FIELD),
        strategy=cast(ExperimentalOptimizerStrategy, raw_strategy),
        generation_index=observation.generation_index,
        parameters=observation.parameters,
        requested_fidelity=observation.requested_fidelity,
        effective_fidelity=observation.fidelity,
    )


def verified_observation_source_membership(
    observation: OptimizerObservation,
    child_strategy: str,
) -> bool | None:
    """Return verified child-local learning ownership, or ``None`` for legacy."""

    metadata = observation.optimizer_metadata
    if (
        not isinstance(metadata, Mapping)
        or metadata.get(OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD) is not True
    ):
        return None
    evidence = verified_observation_source_evidence(observation)
    if evidence is None:
        return False
    return evidence.learning_owner == child_strategy


__all__ = [
    "OPTIMIZER_SOURCE_EVIDENCE_FIELD",
    "OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD",
    "OPTIMIZER_SOURCE_EVIDENCE_SCHEMA",
    "PORTFOLIO_SOURCES_V2_SCHEMA",
    "OptimizerSourceCreditV1",
    "OptimizerSourceEntryV1",
    "OptimizerSourceEvidenceV2",
    "OptimizerSourceRole",
    "classify_optimizer_source_role",
    "compile_optimizer_source_evidence",
    "optimizer_search_space_sha256",
    "verified_observation_source_evidence",
    "verified_observation_source_membership",
    "verify_optimizer_source_evidence",
]
