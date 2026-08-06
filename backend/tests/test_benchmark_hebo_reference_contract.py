from __future__ import annotations

from typing import Literal

import pytest
from pydantic import ValidationError

from app.benchmarking.adapters import BenchmarkAdapterError
from app.benchmarking.contracts import (
    BenchmarkHistoryItemV2,
    BenchmarkObservationV2,
    BenchmarkOptimizerOutcomeV1,
    canonical_sha256,
)
from app.benchmarking.hebo_reference_contract import (
    HEBO_DISTRIBUTION_LOCK,
    HEBO_DISTRIBUTION_LOCK_SHA256,
    HEBO_POLICY,
    HEBO_POLICY_SHA256,
    HeboPreparedContractV1,
    prepare_hebo_contract,
)
from app.benchmarking.method_inventory import BENCHMARK_METHOD_INVENTORY
from app.benchmarking.registry import create_benchmark_adapter


def _objective_outcome(
    *, loss: float, violation: float, feasible: bool
) -> BenchmarkOptimizerOutcomeV1:
    return BenchmarkOptimizerOutcomeV1(
        role="objective",
        loss=loss,
        objectives={"tracking_error": loss},
        objective_directions={"tracking_error": "minimize"},
        constraint_violations={"safety": violation},
        feasible=feasible,
        failure_rate=0.0 if feasible else 1.0,
        completed=True,
    )


def _failure_outcome(
    role: Literal["constraint_only", "quarantined"],
) -> BenchmarkOptimizerOutcomeV1:
    if role == "constraint_only":
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
    return BenchmarkOptimizerOutcomeV1(
        role="quarantined",
        loss=None,
        objectives={},
        objective_directions={},
        constraint_violations={},
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
            outcome=_objective_outcome(loss=0.4, violation=0.0, feasible=True),
        ),
        BenchmarkHistoryItemV2(
            candidate_ref="candidate-2",
            generation_index=2,
            dispatch_ordinal=2,
            parameters={"kp": 1.1, "kd": 0.25},
            screening_status="failed",
            outcome=_objective_outcome(loss=0.2, violation=0.3, feasible=False),
        ),
        BenchmarkHistoryItemV2(
            candidate_ref="candidate-3",
            generation_index=3,
            dispatch_ordinal=3,
            parameters={"kp": 1.2, "kd": 0.3},
            screening_status="unsafe",
            outcome=_failure_outcome("constraint_only"),
            failure_code="unsafe-flight",
        ),
        BenchmarkHistoryItemV2(
            candidate_ref="candidate-4",
            generation_index=4,
            dispatch_ordinal=4,
            parameters={"kp": 0.9, "kd": 0.15},
            screening_status="indeterminate",
            outcome=_failure_outcome("quarantined"),
            failure_code="telemetry-indeterminate",
        ),
    ]


def _observation(
    *, history: list[BenchmarkHistoryItemV2] | None = None
) -> BenchmarkObservationV2:
    history_items = history or []
    return BenchmarkObservationV2(
        campaign_id="campaign-1",
        run_id="run-1",
        benchmark_arm_id="hebo",
        generation_index=5,
        next_dispatch_ordinal=(history_items[-1].dispatch_ordinal + 1 if history_items else 1),
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
        constraints=[
            {
                "name": "safety",
                "operator": "le",
                "threshold": 0.0,
                "hard": True,
                "penalty": 1.0,
            }
        ],
        history=history_items,
        failure_semantics={"unsafe": "competing_terminal_event"},
        simulator_budget_remaining=32,
        wall_time_remaining_ms=60_000,
    )


def test_hebo_wheel_license_dependencies_and_policy_are_content_addressed() -> None:
    assert HEBO_DISTRIBUTION_LOCK.package_version == "0.3.6"
    assert HEBO_DISTRIBUTION_LOCK.wheel_size_bytes == 114720
    assert HEBO_DISTRIBUTION_LOCK.wheel_sha256 == (
        "f3d46a106205eac5340822e5ad1aeb389109ea302dfe35f17d24e69c7c1d0665"
    )
    assert HEBO_DISTRIBUTION_LOCK.wheel_license_path.endswith("dist-info/LICENSE")
    assert HEBO_DISTRIBUTION_LOCK.license_spdx == "MIT"
    assert "numpy<1.25,>=1.16" in HEBO_DISTRIBUTION_LOCK.requires_dist
    assert "pymoo==0.6.0" in HEBO_DISTRIBUTION_LOCK.requires_dist
    assert canonical_sha256(HEBO_DISTRIBUTION_LOCK) == HEBO_DISTRIBUTION_LOCK_SHA256
    assert HEBO_POLICY.native_constraint_model is False
    assert HEBO_POLICY.sequential_max_in_flight == 1
    assert HEBO_POLICY.sobol_replay_policy == "fast-forward-all-dispatched-candidates"
    assert HEBO_POLICY.failed_observation_mapping.endswith("no-fabricated-loss")
    assert canonical_sha256(HEBO_POLICY) == HEBO_POLICY_SHA256


def test_prepared_contract_observes_only_real_feasible_losses() -> None:
    observation = _observation(history=_history())
    first = prepare_hebo_contract(observation)
    second = prepare_hebo_contract(observation)

    assert first == second
    assert first.status == "contract_only"
    assert first.execution_authorized is False
    assert first.observation_sha256 == canonical_sha256(observation)
    assert first.feasible_objective_observations == 1
    assert first.infeasible_objective_outcomes == 1
    assert first.nonobjective_outcomes == 2
    assert first.sobol_draws_consumed == 4
    assert first.next_trial_number == 4
    assert first.maximum_new_trials == 32
    assert canonical_sha256(first.model_dump(mode="json", exclude={"binding_sha256"})) == (
        first.binding_sha256
    )


def test_pending_noncontiguous_or_out_of_domain_history_fails_closed() -> None:
    pending = BenchmarkHistoryItemV2(
        candidate_ref="pending-candidate",
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
    with pytest.raises(BenchmarkAdapterError, match="while pending"):
        prepare_hebo_contract(_observation(history=[pending]))

    with pytest.raises(BenchmarkAdapterError, match="ascending dispatch"):
        prepare_hebo_contract(_observation(history=list(reversed(_history()))))

    payload = _observation(history=_history()).model_dump(mode="json")
    payload["history"][0]["parameters"]["kp"] = 9.0
    with pytest.raises(BenchmarkAdapterError, match="already satisfy the domain"):
        prepare_hebo_contract(BenchmarkObservationV2.model_validate(payload))


def test_schema_or_binding_tamper_fails_closed() -> None:
    payload = _observation(history=_history()).model_dump(mode="json")
    payload["history"][0]["outcome"]["constraint_violations"] = {"different": 0.0}
    with pytest.raises(BenchmarkAdapterError, match="constraint names differ"):
        prepare_hebo_contract(BenchmarkObservationV2.model_validate(payload))

    wrong_objective = _observation(history=_history()).model_dump(mode="json")
    wrong_objective["history"][0]["outcome"]["objectives"] = {"wrong": 0.4}
    wrong_objective["history"][0]["outcome"]["objective_directions"] = {
        "wrong": "minimize"
    }
    with pytest.raises(BenchmarkAdapterError, match="objective names differ"):
        prepare_hebo_contract(BenchmarkObservationV2.model_validate(wrong_objective))

    wrong_direction = _observation(history=_history()).model_dump(mode="json")
    wrong_direction["history"][0]["outcome"]["objective_directions"] = {
        "tracking_error": "maximize"
    }
    with pytest.raises(BenchmarkAdapterError, match="objective directions differ"):
        prepare_hebo_contract(BenchmarkObservationV2.model_validate(wrong_direction))

    prepared = prepare_hebo_contract(_observation(history=_history()))
    tampered = prepared.model_dump(mode="python")
    tampered["feasible_objective_observations"] += 1
    with pytest.raises(ValidationError, match="replay counts|binding hash"):
        HeboPreparedContractV1.model_validate(tampered)


def test_inventory_is_now_source_and_license_bound_but_execution_stays_blocked() -> None:
    inventory = BENCHMARK_METHOD_INVENTORY["hebo/v1"]
    assert inventory.execution_readiness == "blocked"
    assert inventory.implementation_label == "hebo-0.3.6-sequential-scalar-contract"
    assert inventory.blocker_codes == (
        "adapter_not_implemented",
        "compatibility_unverified",
        "isolated_environment_missing",
    )
    assert "license_unverified" not in inventory.blocker_codes
    assert "source_archive_hash_pending" not in inventory.blocker_codes
    assert "version_unresolved" not in inventory.blocker_codes
    source = inventory.sources[0]
    assert source.version_candidate == "0.3.6"
    assert source.distribution_sha256 == HEBO_DISTRIBUTION_LOCK.wheel_sha256
    assert source.license_status == "verified"
    assert source.license_spdx == "MIT"
    with pytest.raises(ValueError, match="not implemented"):
        create_benchmark_adapter("hebo/v1")
