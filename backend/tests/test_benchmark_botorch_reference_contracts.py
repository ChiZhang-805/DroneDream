from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.benchmarking.adapters import BenchmarkAdapterError
from app.benchmarking.botorch_reference_contracts import (
    BOTORCH_DISTRIBUTION_LOCK,
    BOTORCH_DISTRIBUTION_LOCK_SHA256,
    BOTORCH_SCBO_POLICY,
    BOTORCH_SCBO_POLICY_SHA256,
    BOTORCH_TURBO_POLICY,
    BOTORCH_TURBO_POLICY_SHA256,
    BoTorchPreparedReferenceContractV1,
    prepare_botorch_reference_contract,
)
from app.benchmarking.contracts import (
    BenchmarkHistoryItemV2,
    BenchmarkObservationV2,
    BenchmarkOptimizerOutcomeV1,
    canonical_sha256,
)
from app.benchmarking.method_inventory import BENCHMARK_METHOD_INVENTORY
from app.benchmarking.registry import create_benchmark_adapter


def _objective(*, loss: float, feasible: bool) -> BenchmarkOptimizerOutcomeV1:
    return BenchmarkOptimizerOutcomeV1(
        role="objective",
        loss=loss,
        objectives={"tracking_error": loss},
        objective_directions={"tracking_error": "minimize"},
        constraint_violations={"safety": 0.0 if feasible else 0.3},
        feasible=feasible,
        failure_rate=0.0 if feasible else 1.0,
        completed=True,
    )


def _unsafe() -> BenchmarkOptimizerOutcomeV1:
    return BenchmarkOptimizerOutcomeV1(
        role="constraint_only",
        loss=None,
        objectives={},
        objective_directions={},
        constraint_violations={"safety": 1.0},
        feasible=False,
        failure_rate=1.0,
        completed=True,
    )


def _history() -> list[BenchmarkHistoryItemV2]:
    return [
        BenchmarkHistoryItemV2(
            candidate_ref="candidate-1",
            generation_index=1,
            dispatch_ordinal=1,
            parameters={"kp": 1.0, "kd": 0.2},
            screening_status="passed",
            outcome=_objective(loss=0.4, feasible=True),
        ),
        BenchmarkHistoryItemV2(
            candidate_ref="candidate-2",
            generation_index=2,
            dispatch_ordinal=2,
            parameters={"kp": 1.2, "kd": 0.3},
            screening_status="unsafe",
            outcome=_unsafe(),
            failure_code="unsafe-flight",
        ),
    ]


def _observation(
    *,
    history: list[BenchmarkHistoryItemV2] | None = None,
    constraints: bool = True,
) -> BenchmarkObservationV2:
    items = history or []
    return BenchmarkObservationV2(
        campaign_id="campaign-1",
        run_id="run-1",
        benchmark_arm_id="botorch-reference",
        generation_index=3,
        next_dispatch_ordinal=(items[-1].dispatch_ordinal + 1 if items else 1),
        algorithm_seed=20260805,
        simulator_seed_block_id="crn-1",
        parameter_domain=[
            {"name": "kp", "baseline": 1.0, "minimum": 0.5, "maximum": 2.0},
            {
                "name": "kd",
                "baseline": 0.2,
                "minimum": 0.05,
                "maximum": 0.5,
                "scale": "log",
            },
        ],
        objectives=[
            {
                "name": "tracking_error",
                "direction": "minimize",
                "weight": 1.0,
                "normalization": 1.0,
                "target": None,
            }
        ],
        constraints=(
            [
                {
                    "name": "safety",
                    "operator": "le",
                    "threshold": 0.0,
                    "hard": True,
                    "penalty": 1.0,
                }
            ]
            if constraints
            else []
        ),
        history=items,
        failure_semantics={"unsafe": "competing_terminal_event"},
        simulator_budget_remaining=32,
        wall_time_remaining_ms=60_000,
    )


def test_botorch_distribution_and_tutorial_policies_are_content_addressed() -> None:
    assert BOTORCH_DISTRIBUTION_LOCK.package_version == "0.17.0"
    assert BOTORCH_DISTRIBUTION_LOCK.upstream_commit == ("1855320f0bbef1766b5a010ebaad6253e8cf072b")
    assert BOTORCH_DISTRIBUTION_LOCK.wheel_sha256 == (
        "fb8610cbf43a48746aa5935141b12063723abf0f8c353132cfcd9757703d02c2"
    )
    assert BOTORCH_DISTRIBUTION_LOCK.sdist_sha256 == (
        "32e5c3ee99504b909d3a495e35c0b193566a5851e6a50e761b67338d11086749"
    )
    assert BOTORCH_DISTRIBUTION_LOCK.transitive_dependency_lock_complete is False
    assert canonical_sha256(BOTORCH_DISTRIBUTION_LOCK) == BOTORCH_DISTRIBUTION_LOCK_SHA256
    assert BOTORCH_TURBO_POLICY.recipe_name == "TuRBO-1"
    assert BOTORCH_TURBO_POLICY.initial_design_policy == "2*dimension"
    assert BOTORCH_TURBO_POLICY.constraints_modelled is False
    assert BOTORCH_SCBO_POLICY.recipe_name == "SCBO"
    assert BOTORCH_SCBO_POLICY.initial_design_policy == "tutorial-fixed-10-for-10d"
    assert BOTORCH_SCBO_POLICY.constraints_modelled is True
    assert BOTORCH_SCBO_POLICY.constraint_sign_convention == "violation<=0-feasible"
    assert BOTORCH_TURBO_POLICY.tutorial_batch_size == 4
    assert BOTORCH_TURBO_POLICY.product_proposal_batch_size == 1
    assert BOTORCH_TURBO_POLICY.batch_semantics_resolved is False
    assert canonical_sha256(BOTORCH_TURBO_POLICY) == BOTORCH_TURBO_POLICY_SHA256
    assert canonical_sha256(BOTORCH_SCBO_POLICY) == BOTORCH_SCBO_POLICY_SHA256


@pytest.mark.parametrize("adapter_id", ("reference_turbo/v1", "reference_scbo/v1"))
def test_prepared_contract_keeps_real_observations_and_excludes_failures(
    adapter_id: str,
) -> None:
    observation = _observation(history=_history())
    first = prepare_botorch_reference_contract(observation, adapter_id)  # type: ignore[arg-type]
    second = prepare_botorch_reference_contract(observation, adapter_id)  # type: ignore[arg-type]

    assert first == second
    assert first.status == "contract_only"
    assert first.execution_authorized is False
    assert first.observation_sha256 == canonical_sha256(observation)
    assert first.completed_objective_observations == 1
    assert first.infeasible_objective_observations == 0
    assert first.excluded_without_objective_observations == 1
    assert first.terminal_history_observations == 2
    assert first.tutorial_batch_size == 4
    assert first.product_proposal_batch_size == 1
    assert first.batch_semantics_resolved is False
    assert first.blocker_codes == (
        "isolated-environment-missing",
        "reference-adapter-missing",
        "sequential-batch-semantics-unresolved",
        "transitive-dependency-lock-missing",
    )
    assert canonical_sha256(first.model_dump(mode="json", exclude={"binding_sha256"})) == (
        first.binding_sha256
    )


def test_scbo_requires_constraints_and_never_fabricates_unsafe_objectives() -> None:
    with pytest.raises(BenchmarkAdapterError, match="requires at least one"):
        prepare_botorch_reference_contract(
            _observation(history=[], constraints=False), "reference_scbo/v1"
        )

    prepared = prepare_botorch_reference_contract(
        _observation(history=_history()), "reference_scbo/v1"
    )
    assert prepared.completed_objective_observations == 1
    assert prepared.excluded_without_objective_observations == 1


def test_pending_history_domain_drift_and_schema_drift_fail_closed() -> None:
    pending = BenchmarkHistoryItemV2(
        candidate_ref="pending",
        generation_index=1,
        dispatch_ordinal=1,
        parameters={"kp": 1.0, "kd": 0.2},
        screening_status="pending",
        outcome=BenchmarkOptimizerOutcomeV1(
            role="pending_reservation",
            loss=None,
            objectives={},
            objective_directions={},
            constraint_violations={},
            feasible=False,
            failure_rate=0.0,
            completed=False,
        ),
    )
    with pytest.raises(BenchmarkAdapterError, match="rejects pending"):
        prepare_botorch_reference_contract(_observation(history=[pending]), "reference_turbo/v1")

    payload = _observation(history=_history()).model_dump(mode="json")
    payload["history"][0]["parameters"]["kp"] = 9.0
    with pytest.raises(BenchmarkAdapterError, match="satisfy the domain"):
        prepare_botorch_reference_contract(
            BenchmarkObservationV2.model_validate(payload), "reference_turbo/v1"
        )

    payload = _observation(history=_history()).model_dump(mode="json")
    payload["history"][0]["outcome"]["constraint_violations"] = {"other": 0.0}
    with pytest.raises(BenchmarkAdapterError, match="constraint values differ"):
        prepare_botorch_reference_contract(
            BenchmarkObservationV2.model_validate(payload), "reference_scbo/v1"
        )


def test_contract_tamper_and_unimplemented_runtime_fail_closed() -> None:
    prepared = prepare_botorch_reference_contract(
        _observation(history=_history()), "reference_scbo/v1"
    )
    tampered = prepared.model_dump(mode="python")
    tampered["maximum_new_trials"] += 1
    with pytest.raises(ValidationError, match="binding hash"):
        BoTorchPreparedReferenceContractV1.model_validate(tampered)

    substituted = prepared.model_dump(mode="python")
    substituted["required_runtime_symbols"] = (
        "botorch.models.SingleTaskGP",
        "unreviewed.runtime.symbol",
    )
    substituted["binding_sha256"] = canonical_sha256(
        {key: value for key, value in substituted.items() if key != "binding_sha256"}
    )
    with pytest.raises(ValidationError, match="runtime symbols"):
        BoTorchPreparedReferenceContractV1.model_validate(substituted)

    for adapter_id in ("reference_turbo/v1", "reference_scbo/v1"):
        inventory = BENCHMARK_METHOD_INVENTORY[adapter_id]
        assert inventory.execution_readiness == "blocked"
        assert "source_archive_hash_pending" not in inventory.blocker_codes
        assert "compatibility_unverified" in inventory.blocker_codes
        packages = [
            source for source in inventory.sources if source.source_kind == "python_package"
        ]
        assert len(packages) == 2
        assert all(source.distribution_sha256 for source in packages)
        with pytest.raises(ValueError, match="not implemented"):
            create_benchmark_adapter(adapter_id)
