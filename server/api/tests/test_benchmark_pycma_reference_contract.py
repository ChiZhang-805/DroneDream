from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.benchmarking.adapters import BenchmarkAdapterError
from app.benchmarking.contracts import BenchmarkObservationV2, canonical_sha256
from app.benchmarking.method_inventory import BENCHMARK_METHOD_INVENTORY
from app.benchmarking.pycma_reference_contract import (
    PYCMA_BIPOP_POLICY,
    PYCMA_BIPOP_POLICY_SHA256,
    PYCMA_DISTRIBUTION_LOCK,
    PYCMA_DISTRIBUTION_LOCK_SHA256,
    PycmaBipopPreparedContractV1,
    prepare_pycma_bipop_contract,
)
from app.benchmarking.registry import create_benchmark_adapter


def _observation() -> BenchmarkObservationV2:
    return BenchmarkObservationV2(
        campaign_id="campaign-1",
        run_id="run-1",
        benchmark_arm_id="bipop-cma-es",
        generation_index=1,
        next_dispatch_ordinal=1,
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
        objectives=[{"name": "rmse", "direction": "minimize"}],
        constraints=[{"name": "max_error", "operator": "le", "threshold": 1.0}],
        failure_semantics={"unsafe": "competing_terminal_event"},
        simulator_budget_remaining=64,
        wall_time_remaining_ms=60_000,
    )


def test_pycma_source_and_official_bipop_policy_are_content_addressed() -> None:
    assert PYCMA_DISTRIBUTION_LOCK.package_version == "4.4.4"
    assert PYCMA_DISTRIBUTION_LOCK.upstream_commit == ("83089d1d681165b8cc849f4a05c9f1c1869d79a3")
    assert PYCMA_DISTRIBUTION_LOCK.wheel_sha256 == (
        "edb6d02eb2aac2d54650f16a8f0c70711ff17445957de7c9de92ff7fd4b7ef38"
    )
    assert PYCMA_DISTRIBUTION_LOCK.sdist_sha256 == (
        "632bd654b5dce04c0eaa3166679d3e4773ce7a79eab7934e7f363c341b9a8170"
    )
    assert canonical_sha256(PYCMA_DISTRIBUTION_LOCK) == PYCMA_DISTRIBUTION_LOCK_SHA256
    assert PYCMA_BIPOP_POLICY.coordinator_api == "cma.fmin2"
    assert PYCMA_BIPOP_POLICY.bipop is True
    assert PYCMA_BIPOP_POLICY.restarts == 9
    assert PYCMA_BIPOP_POLICY.one_candidate_adapter_equivalent is False
    assert PYCMA_BIPOP_POLICY.failed_trial_policy.endswith("no-fabricated-fitness")
    assert canonical_sha256(PYCMA_BIPOP_POLICY) == PYCMA_BIPOP_POLICY_SHA256


def test_prepared_contract_is_deterministic_but_never_authorizes_execution() -> None:
    observation = _observation()
    first = prepare_pycma_bipop_contract(observation)
    second = prepare_pycma_bipop_contract(observation)

    assert first == second
    assert first.status == "contract_only"
    assert first.execution_authorized is False
    assert first.observation_sha256 == canonical_sha256(observation)
    expected_log_mean = (math.log(0.2) - math.log(0.05)) / (math.log(0.5) - math.log(0.05))
    assert first.initial_mean_unit == pytest.approx((1.0 / 3.0, expected_log_mean))
    assert first.maximum_objective_evaluations == 64
    assert first.blocker_codes == (
        "isolated-environment-missing",
        "objective-callback-coordinator-missing",
    )
    assert canonical_sha256(first.model_dump(mode="json", exclude={"binding_sha256"})) == (
        first.binding_sha256
    )


def test_contract_rejects_late_attachment_and_noncontinuous_domains() -> None:
    late_payload = _observation().model_dump(mode="json")
    late_payload["generation_index"] = 2
    with pytest.raises(BenchmarkAdapterError, match="generation one"):
        prepare_pycma_bipop_contract(BenchmarkObservationV2.model_validate(late_payload))

    discrete_payload = _observation().model_dump(mode="json")
    discrete_payload["parameter_domain"][0]["step"] = 0.1
    with pytest.raises(BenchmarkAdapterError, match="continuous float"):
        prepare_pycma_bipop_contract(BenchmarkObservationV2.model_validate(discrete_payload))


def test_contract_tamper_and_runtime_substitution_fail_closed() -> None:
    prepared = prepare_pycma_bipop_contract(_observation())
    tampered = prepared.model_dump(mode="python")
    tampered["maximum_objective_evaluations"] += 1
    with pytest.raises(ValidationError, match="binding hash"):
        PycmaBipopPreparedContractV1.model_validate(tampered)

    inventory = BENCHMARK_METHOD_INVENTORY["bipop_cma_es/v1"]
    assert inventory.execution_readiness == "blocked"
    assert "source_archive_hash_pending" not in inventory.blocker_codes
    assert "isolated_environment_missing" in inventory.blocker_codes
    assert all(source.distribution_sha256 for source in inventory.sources)
    with pytest.raises(ValueError, match="not implemented"):
        create_benchmark_adapter("bipop_cma_es/v1")
