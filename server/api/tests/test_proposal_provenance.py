"""Regression coverage for content-addressed optimizer source ownership."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.optimization.bayesian_optimizers import (
    _is_turbo_observation,
    _turbo_radius,
)
from app.optimization.cma_optimizers import _strategy_matches
from app.optimization.domain import SearchSpace
from app.optimization.experimental_types import OptimizerObservation
from app.optimization.proposal_provenance import (
    OPTIMIZER_SOURCE_EVIDENCE_FIELD,
    OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD,
    OPTIMIZER_SOURCE_EVIDENCE_SCHEMA,
    PORTFOLIO_SOURCES_V2_SCHEMA,
    classify_optimizer_source_role,
    compile_optimizer_source_evidence,
    optimizer_search_space_sha256,
    verified_observation_source_membership,
    verify_optimizer_source_evidence,
)
from app.schemas import ParameterSelection

_SEARCH_SPACE_SHA256 = "sha256:" + "1" * 64


def test_search_space_fingerprint_binds_bounds_types_and_order() -> None:
    first = SearchSpace.from_schema(
        [
            ParameterSelection(
                name="MPC_XY_P",
                baseline=0.95,
                minimum=0.6,
                maximum=1.3,
                step=0.1,
            ),
            ParameterSelection(
                name="MPC_Z_P",
                baseline=1.0,
                minimum=0.5,
                maximum=1.5,
                value_type="float",
            ),
        ]
    )
    changed_bound = SearchSpace.from_schema(
        [
            ParameterSelection(
                name="MPC_XY_P",
                baseline=0.95,
                minimum=0.6,
                maximum=1.4,
                step=0.1,
            ),
            ParameterSelection(
                name="MPC_Z_P",
                baseline=1.0,
                minimum=0.5,
                maximum=1.5,
                value_type="float",
            ),
        ]
    )
    reversed_order = SearchSpace(tuple(reversed(first.domains)))

    assert optimizer_search_space_sha256(first).startswith("sha256:")
    assert optimizer_search_space_sha256(first) != (optimizer_search_space_sha256(changed_bound))
    assert optimizer_search_space_sha256(first) != (optimizer_search_space_sha256(reversed_order))
    validator_context = {
        "schema_id": "dronedream.px4-candidate-validator/v1",
        "px4_version": "main",
        "parameter_catalog_version": "px4-main-v1",
        "vehicle_type": "multicopter",
        "airframe": "x500",
        "enforce_safe_bounds": True,
    }
    assert optimizer_search_space_sha256(
        first,
        validator_contract=validator_context,
    ) != optimizer_search_space_sha256(
        first,
        validator_contract={**validator_context, "airframe": "plane"},
    )


def test_direct_source_evidence_binds_strategy_generation_and_parameters() -> None:
    parameters = {"MPC_XY_P": 0.95, "MPC_Z_P": 1.0}
    evidence = compile_optimizer_source_evidence(
        strategy="turbo",
        generation_index=3,
        parameters=parameters,
        search_space_sha256=_SEARCH_SPACE_SHA256,
        metadata={
            "optimizer_generated_by": "turbo",
            "requested_fidelity": 0.5,
            "effective_fidelity": 0.75,
        },
    )

    assert evidence.schema_id == OPTIMIZER_SOURCE_EVIDENCE_SCHEMA
    assert evidence.sources[0].source_role == "native_optimizer"
    assert evidence.sources[0].reward_eligible
    assert evidence.learning_owner == "turbo"
    assert evidence.reward_credits[0].child_strategy == "turbo"
    assert evidence.reward_credits[0].share == pytest.approx(1.0)
    assert (
        verify_optimizer_source_evidence(
            evidence.model_dump(mode="json"),
            strategy="turbo",
            generation_index=3,
            parameters=parameters,
            search_space_sha256=_SEARCH_SPACE_SHA256,
            requested_fidelity=0.5,
            effective_fidelity=0.75,
        )
        == evidence
    )
    assert (
        verify_optimizer_source_evidence(
            evidence.model_dump(mode="json"),
            strategy="turbo",
            generation_index=4,
            parameters=parameters,
            search_space_sha256=_SEARCH_SPACE_SHA256,
        )
        is None
    )
    assert (
        verify_optimizer_source_evidence(
            evidence.model_dump(mode="json"),
            strategy="turbo",
            generation_index=3,
            parameters=parameters,
            search_space_sha256="sha256:" + "2" * 64,
        )
        is None
    )
    assert (
        verify_optimizer_source_evidence(
            evidence.model_dump(mode="json"),
            strategy="turbo",
            generation_index=3,
            parameters=parameters,
            search_space_sha256=_SEARCH_SPACE_SHA256,
            requested_fidelity=1.0,
            effective_fidelity=0.75,
        )
        is None
    )
    assert (
        verify_optimizer_source_evidence(
            evidence.model_dump(mode="json"),
            strategy="turbo",
            generation_index=3,
            parameters={**parameters, "MPC_Z_P": 1.1},
            search_space_sha256=_SEARCH_SPACE_SHA256,
        )
        is None
    )


def test_fallback_role_is_closed_and_cannot_receive_reward_credit() -> None:
    evidence = compile_optimizer_source_evidence(
        strategy="saasbo",
        generation_index=1,
        parameters={"MPC_XY_P": 0.9},
        search_space_sha256=_SEARCH_SPACE_SHA256,
        metadata={
            "optimizer_generated_by": "halton_fallback",
            "fidelity": 1.0,
        },
    )

    assert classify_optimizer_source_role("saasbo", "halton_fallback") == ("emergency_fallback")
    assert evidence.sources[0].source_role == "emergency_fallback"
    assert not evidence.sources[0].reward_eligible
    assert evidence.learning_owner is None
    assert evidence.reward_credits == ()

    tampered = evidence.model_dump(mode="json")
    tampered["sources"][0]["source_role"] = "native_optimizer"
    assert (
        verify_optimizer_source_evidence(
            tampered,
            strategy="saasbo",
            generation_index=1,
            parameters={"MPC_XY_P": 0.9},
            search_space_sha256=_SEARCH_SPACE_SHA256,
        )
        is None
    )


def test_valid_fallback_envelopes_never_update_turbo_radius() -> None:
    observations: list[OptimizerObservation] = []
    for generation_index, loss in enumerate((0.5, 0.4, 0.3, 0.2), start=1):
        parameters = {"MPC_XY_P": 0.8 + generation_index * 0.01}
        evidence = compile_optimizer_source_evidence(
            strategy="turbo",
            generation_index=generation_index,
            parameters=parameters,
            search_space_sha256=_SEARCH_SPACE_SHA256,
            metadata={
                "optimizer_generated_by": "halton_fallback",
                "fidelity": 1.0,
            },
        )
        observations.append(
            OptimizerObservation(
                candidate_id=f"fallback-{generation_index}",
                generation_index=generation_index,
                parameters=parameters,
                unit_vector=(generation_index / 10.0,),
                loss=loss,
                optimizer_strategy="turbo",
                optimizer_metadata={
                    "strategy": "turbo",
                    OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD: True,
                    OPTIMIZER_SOURCE_EVIDENCE_FIELD: evidence.model_dump(mode="json"),
                },
            )
        )

    assert all(
        verified_observation_source_membership(observation, "turbo") is False
        for observation in observations
    )
    assert all(not _is_turbo_observation(observation) for observation in observations)
    assert _turbo_radius(observations) == pytest.approx(0.5)


def test_portfolio_collision_credits_only_closed_native_sources_equally() -> None:
    metadata = {
        "child_strategy": "constrained_mobo",
        "portfolio_sources_schema": PORTFOLIO_SOURCES_V2_SCHEMA,
        "portfolio_sources": [
            {
                "child_strategy": "constrained_mobo",
                "source_role": "native_optimizer",
                "generated_by": "constrained_mobo",
                "planned_slot_role": "exploit",
                "effective_fidelity": 1.0,
                "requested_fidelity": 1.0,
                "materialized": True,
                "reward_eligible": True,
                "exclusion_reason": None,
            },
            {
                "child_strategy": "turbo",
                "source_role": "native_optimizer",
                "generated_by": "turbo",
                "planned_slot_role": "exploration",
                "effective_fidelity": 1.0,
                "requested_fidelity": 1.0,
                "materialized": True,
                "reward_eligible": True,
                "exclusion_reason": None,
            },
            {
                "child_strategy": "saasbo",
                "source_role": "emergency_fallback",
                "generated_by": "seeded_random_fallback",
                "planned_slot_role": "coverage",
                "effective_fidelity": 1.0,
                "requested_fidelity": 1.0,
                "materialized": True,
                "reward_eligible": False,
                "exclusion_reason": None,
            },
        ],
    }
    parameters = {"MPC_XY_P": 0.85}
    evidence = compile_optimizer_source_evidence(
        strategy="optimizer_portfolio",
        generation_index=7,
        parameters=parameters,
        search_space_sha256=_SEARCH_SPACE_SHA256,
        metadata=metadata,
    )

    assert [credit.child_strategy for credit in evidence.reward_credits] == [
        "constrained_mobo",
        "turbo",
    ]
    assert evidence.learning_owner == "constrained_mobo"
    assert all(credit.share == pytest.approx(0.5) for credit in evidence.reward_credits)

    forged = deepcopy(evidence.model_dump(mode="json"))
    forged["reward_credits"].append({"child_strategy": "saasbo", "share": 0.5})
    assert (
        verify_optimizer_source_evidence(
            forged,
            strategy="optimizer_portfolio",
            generation_index=7,
            parameters=parameters,
            search_space_sha256=_SEARCH_SPACE_SHA256,
        )
        is None
    )


def test_portfolio_source_schema_v1_fails_closed_for_new_evidence() -> None:
    with pytest.raises(ValueError, match="schema v2"):
        compile_optimizer_source_evidence(
            strategy="optimizer_portfolio",
            generation_index=1,
            parameters={"MPC_XY_P": 0.95},
            search_space_sha256=_SEARCH_SPACE_SHA256,
            metadata={
                "portfolio_sources_schema": "dronedream.portfolio-sources/v1",
                "portfolio_sources": [],
            },
        )


def test_verified_learning_owner_replaces_ambiguous_strategy_strings() -> None:
    parameters = {"MPC_XY_P": 0.85}
    source_evidence = compile_optimizer_source_evidence(
        strategy="optimizer_portfolio",
        generation_index=7,
        parameters=parameters,
        search_space_sha256=_SEARCH_SPACE_SHA256,
        metadata={
            "child_strategy": "turbo",
            "portfolio_sources_schema": PORTFOLIO_SOURCES_V2_SCHEMA,
            "portfolio_sources": [
                {
                    "child_strategy": strategy,
                    "source_role": "native_optimizer",
                    "generated_by": strategy,
                    "planned_slot_role": "exploit",
                    "effective_fidelity": 1.0,
                    "requested_fidelity": 1.0,
                    "materialized": True,
                    "reward_eligible": True,
                    "exclusion_reason": None,
                }
                for strategy in ("turbo", "surrogate_cma_es")
            ],
        },
    )
    metadata = {
        "strategy": "optimizer_portfolio",
        OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD: True,
        OPTIMIZER_SOURCE_EVIDENCE_FIELD: source_evidence.model_dump(mode="json"),
    }
    observation = OptimizerObservation(
        candidate_id="candidate-multi-source",
        generation_index=7,
        parameters=parameters,
        unit_vector=(0.5,),
        loss=0.25,
        optimizer_strategy="optimizer_portfolio",
        optimizer_metadata=metadata,
    )

    assert verified_observation_source_membership(observation, "turbo") is True
    assert _is_turbo_observation(observation)
    assert not _strategy_matches(observation, "surrogate_cma_es")
    assert (
        verified_observation_source_membership(
            observation,
            "surrogate_cma_es",
        )
        is False
    )
    assert (
        verified_observation_source_membership(
            observation,
            "constrained_mobo",
        )
        is False
    )
    fidelity_drift = OptimizerObservation(
        candidate_id="candidate-fidelity-drift",
        generation_index=7,
        parameters=parameters,
        unit_vector=(0.5,),
        loss=0.25,
        fidelity=0.5,
        requested_fidelity=1.0,
        optimizer_strategy="optimizer_portfolio",
        optimizer_metadata=metadata,
    )
    assert (
        verified_observation_source_membership(
            fidelity_drift,
            "turbo",
        )
        is False
    )

    tampered_metadata = deepcopy(metadata)
    tampered_metadata[OPTIMIZER_SOURCE_EVIDENCE_FIELD]["sources"][0]["generated_by"] = (
        "halton_fallback"
    )
    tampered = OptimizerObservation(
        candidate_id="candidate-tampered-source",
        generation_index=7,
        parameters=parameters,
        unit_vector=(0.5,),
        loss=0.25,
        optimizer_strategy="turbo",
        optimizer_metadata=tampered_metadata,
    )
    assert verified_observation_source_membership(tampered, "turbo") is False
    assert not _is_turbo_observation(tampered)

    legacy = OptimizerObservation(
        candidate_id="candidate-legacy-source",
        generation_index=7,
        parameters=parameters,
        unit_vector=(0.5,),
        loss=0.25,
        optimizer_strategy="turbo",
    )
    assert verified_observation_source_membership(legacy, "turbo") is None
