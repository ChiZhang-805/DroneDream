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
from app.benchmarking.method_inventory import BENCHMARK_METHOD_INVENTORY
from app.benchmarking.optuna_tpe_reference_contract import (
    OPTUNA_DISTRIBUTION_LOCK,
    OPTUNA_DISTRIBUTION_LOCK_SHA256,
    OPTUNA_TPE_POLICY,
    OPTUNA_TPE_POLICY_SHA256,
    OptunaTpePreparedContractV1,
    prepare_optuna_tpe_contract,
)
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
    parameters = {"kp": 1.0, "kd": 0.2}
    return [
        BenchmarkHistoryItemV2(
            candidate_ref="candidate-1",
            generation_index=1,
            dispatch_ordinal=1,
            parameters=parameters,
            screening_status="passed",
            outcome=_objective_outcome(loss=0.4, violation=0.0, feasible=True),
        ),
        BenchmarkHistoryItemV2(
            candidate_ref="candidate-2",
            generation_index=2,
            dispatch_ordinal=2,
            parameters={"kp": 1.1, "kd": 0.25},
            screening_status="failed",
            outcome=_objective_outcome(loss=0.7, violation=0.3, feasible=False),
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


def _observation(*, history: list[BenchmarkHistoryItemV2] | None = None) -> BenchmarkObservationV2:
    history_items = history or []
    return BenchmarkObservationV2(
        campaign_id="campaign-1",
        run_id="run-1",
        benchmark_arm_id="optuna-tpe",
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


def test_optuna_source_and_multivariate_policy_are_content_addressed() -> None:
    assert OPTUNA_DISTRIBUTION_LOCK.package_version == "4.9.0"
    assert OPTUNA_DISTRIBUTION_LOCK.upstream_commit == ("4db42e31c24b200e52595df9d4c00e2cdeefea2b")
    assert OPTUNA_DISTRIBUTION_LOCK.wheel_sha256 == (
        "f52f3be6148654850c92a5860d398fd88ec6b2c84ab68d9c3d07dcff02e7afee"
    )
    assert OPTUNA_DISTRIBUTION_LOCK.sdist_sha256 == (
        "b322e5cbdf1655fb84c37646c4a7a1f391de1b47806bbe222e015825d0a82b87"
    )
    assert OPTUNA_DISTRIBUTION_LOCK.third_party_notice_required is True
    assert canonical_sha256(OPTUNA_DISTRIBUTION_LOCK) == OPTUNA_DISTRIBUTION_LOCK_SHA256
    assert OPTUNA_TPE_POLICY.multivariate is True
    assert OPTUNA_TPE_POLICY.group is False
    assert OPTUNA_TPE_POLICY.constant_liar is False
    assert OPTUNA_TPE_POLICY.sequential_max_in_flight == 1
    assert OPTUNA_TPE_POLICY.failed_trial_mapping.endswith("no-fabricated-loss")
    assert canonical_sha256(OPTUNA_TPE_POLICY) == OPTUNA_TPE_POLICY_SHA256


def test_prepared_contract_replays_real_objectives_and_keeps_failures_lossless() -> None:
    observation = _observation(history=_history())
    first = prepare_optuna_tpe_contract(observation)
    second = prepare_optuna_tpe_contract(observation)

    assert first == second
    assert first.status == "contract_only"
    assert first.execution_authorized is False
    assert first.observation_sha256 == canonical_sha256(observation)
    assert first.completed_objective_trials == 2
    assert first.infeasible_objective_trials == 1
    assert first.failed_without_objective_trials == 2
    assert first.next_trial_number == 4
    assert first.maximum_new_trials == 32
    assert first.blocker_codes == (
        "isolated-environment-missing",
        "ask-tell-adapter-missing",
    )
    assert canonical_sha256(first.model_dump(mode="json", exclude={"binding_sha256"})) == (
        first.binding_sha256
    )


def test_pending_or_noncanonical_history_fails_closed() -> None:
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
    with pytest.raises(BenchmarkAdapterError, match="trial is pending"):
        prepare_optuna_tpe_contract(_observation(history=[pending]))

    reversed_history = list(reversed(_history()))
    with pytest.raises(BenchmarkAdapterError, match="ascending dispatch"):
        prepare_optuna_tpe_contract(_observation(history=reversed_history))

    payload = _observation(history=_history()).model_dump(mode="json")
    payload["next_dispatch_ordinal"] = 8
    with pytest.raises(BenchmarkAdapterError, match="not contiguous"):
        prepare_optuna_tpe_contract(BenchmarkObservationV2.model_validate(payload))


def test_objective_schema_drift_and_domain_projection_fail_closed() -> None:
    payload = _observation(history=_history()).model_dump(mode="json")
    payload["history"][0]["outcome"]["objectives"] = {"different": 0.4}
    payload["history"][0]["outcome"]["objective_directions"] = {"different": "minimize"}
    with pytest.raises(BenchmarkAdapterError, match="objective names differ"):
        prepare_optuna_tpe_contract(BenchmarkObservationV2.model_validate(payload))

    payload = _observation(history=_history()).model_dump(mode="json")
    payload["history"][0]["outcome"]["objective_directions"] = {"tracking_error": "maximize"}
    with pytest.raises(BenchmarkAdapterError, match="objective directions differ"):
        prepare_optuna_tpe_contract(BenchmarkObservationV2.model_validate(payload))

    payload = _observation(history=_history()).model_dump(mode="json")
    payload["history"][0]["parameters"]["kp"] = 9.0
    with pytest.raises(BenchmarkAdapterError, match="already satisfy the domain"):
        prepare_optuna_tpe_contract(BenchmarkObservationV2.model_validate(payload))


def test_contract_tamper_and_runtime_substitution_fail_closed() -> None:
    prepared = prepare_optuna_tpe_contract(_observation(history=_history()))
    tampered = prepared.model_dump(mode="python")
    tampered["completed_objective_trials"] += 1
    with pytest.raises(ValidationError, match="replay counts|binding hash"):
        OptunaTpePreparedContractV1.model_validate(tampered)

    inventory = BENCHMARK_METHOD_INVENTORY["optuna_tpe/v1"]
    assert inventory.execution_readiness == "blocked"
    assert "source_archive_hash_pending" not in inventory.blocker_codes
    assert "isolated_environment_missing" in inventory.blocker_codes
    package_sources = [
        source for source in inventory.sources if source.source_kind == "python_package"
    ]
    assert len(package_sources) == 2
    assert all(source.distribution_sha256 for source in package_sources)
    with pytest.raises(ValueError, match="not implemented"):
        create_benchmark_adapter("optuna_tpe/v1")
