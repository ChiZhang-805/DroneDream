from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.benchmarking.contracts import (
    BENCHMARK_OBSERVATION_CONTRACT_SHA256,
    BenchmarkArmManifestV1,
    BenchmarkCampaignManifestV1,
    BenchmarkObservationV2,
    BenchmarkRunBindingRequestV1,
    canonical_sha256,
)
from app.benchmarking.coordinator import run_binding_sha256
from app.benchmarking.llm_arm_contracts import BENCHMARK_LLM_ARM_POLICIES_SHA256
from app.benchmarking.llm_durable_runtime import (
    BENCHMARK_DIRECT_RESERVATION_REASON,
    BenchmarkDurableLLMBlocked,
    BenchmarkProviderExecutionConfigV1,
    BenchmarkProviderTransportResult,
    execute_durable_direct_arm,
)
from app.benchmarking.method_inventory import BENCHMARK_METHOD_INVENTORY
from app.benchmarking.registry import BENCHMARK_ADAPTER_REGISTRY, create_benchmark_adapter
from app.orchestration.cognitive_budget import CognitiveTurnPending
from app.orchestration.provider_request_accounting import (
    ProviderUsage,
    recover_abandoned_provider_requests,
)
from app.orchestration.qualification import QUALIFICATION_RULE_SHA256

_COMMIT = "a" * 40
_SHA = "1" * 64
_MODEL = "gpt-4.1-2025-04-14"


@pytest.fixture()
def durable_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[SimpleNamespace]:
    from app import models
    from app.db import Base, _build_engine

    monkeypatch.setenv("DRONEDREAM_SOURCE_COMMIT", _COMMIT)
    engine = _build_engine(f"sqlite:///{tmp_path / 'durable-direct.db'}")
    Base.metadata.create_all(engine)
    try:
        yield SimpleNamespace(engine=engine, models=models)
    finally:
        engine.dispose()


def _component(component_id: str) -> dict[str, Any]:
    return {
        "component_id": component_id,
        "version": "test-v1",
        "source_commit": _COMMIT,
        "artifact_sha256": _SHA,
        "manifest_sha256": "2" * 64,
    }


def _provider_config() -> BenchmarkProviderExecutionConfigV1:
    from app.schemas import ProviderPriceSnapshot

    return BenchmarkProviderExecutionConfigV1(
        provider="openai",
        model_snapshot=_MODEL,
        base_url="https://api.openai.com/v1",
        region="global",
        temperature=0.0,
        top_p=1.0,
        randomness_policy="fixed_seed",
        maximum_generations=2,
        maximum_output_tokens=128,
        request_timeout_ms=10_000,
        llm_policy_registry_sha256=BENCHMARK_LLM_ARM_POLICIES_SHA256,
        model_matrix_sha256="6" * 64,
        price_snapshot=ProviderPriceSnapshot(
            schema_version="dronedream.provider-price-snapshot/v1",
            source="preregistered",
            input_microusd_per_million_tokens=2_000_000,
            output_microusd_per_million_tokens=8_000_000,
            effective_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        ),
    )


def _inventory() -> dict[str, Any]:
    return {
        "schema_id": "dronedream.composite-execution-inventory/v1",
        "repository_subject_commit": _COMMIT,
        "evaluator_subject_commit": _COMMIT,
        "campaign_coordinator_subject_commit": _COMMIT,
        "evidence_head_commit": None,
        "desktop": None,
        "runtime_base": _component("runtime-base"),
        "engine_pack": _component("engine-pack"),
        "px4": _component("px4"),
        "gazebo": _component("gazebo"),
        "prompt_registry_sha256": "3" * 64,
        "response_schema_sha256": "4" * 64,
        "tool_registry_sha256": "5" * 64,
        "model_matrix_sha256": "6" * 64,
        "machine_profile_sha256": "7" * 64,
        "concurrency_profile_sha256": "8" * 64,
    }


def _arm_manifest() -> BenchmarkArmManifestV1:
    return BenchmarkArmManifestV1(
        benchmark_arm_id="llm-direct",
        arm_version="v1",
        arm_family="llm_harness",
        proposal_adapter_id="llm_direct/v1",
        intervention={
            "provider_execution": _provider_config().model_dump(mode="json")
        },
        provider_contract_sha256=BENCHMARK_LLM_ARM_POLICIES_SHA256,
        execution_enabled=True,
    )


def _campaign_manifest() -> BenchmarkCampaignManifestV1:
    return BenchmarkCampaignManifestV1.model_validate(
        {
            "campaign_key": "durable-direct-test",
            "campaign_version": "v1",
            "name": "Durable direct contract fixture",
            "panel": "engineering",
            "protocol_sha256": "9" * 64,
            "generated_at": datetime(2026, 8, 5, tzinfo=timezone.utc),
            "composite_execution_inventory": _inventory(),
            "fairness": {
                "observation_contract_sha256": BENCHMARK_OBSERVATION_CONTRACT_SHA256,
                "parameter_domain_sha256": "a" * 64,
                "objective_contract_sha256": "b" * 64,
                "constraint_contract_sha256": "c" * 64,
                "history_contract_sha256": "d" * 64,
                "failure_semantics_sha256": "e" * 64,
                "simulator_budget_sha256": "f" * 64,
                "qualification_rule_sha256": QUALIFICATION_RULE_SHA256,
                "scenario_manifest_sha256": "1" * 64,
                "seed_block_manifest_sha256": "2" * 64,
            },
            "budget_caps": {
                "jobs": 2,
                "trials": 100,
                "logical_turns": 2,
                "network_requests": 2,
                "input_utf8_bytes": 10_000_000,
                "output_utf8_bytes": 10_000_000,
                "provider_tokens": 10_000_000,
                "provider_cost_microusd": 10_000_000,
                "wall_time_seconds": 1000,
                "disk_bytes": 10_000_000,
            },
            "arms": [_arm_manifest().model_dump(mode="json")],
        }
    )


def _create_bound_run(db: Session, durable_db: SimpleNamespace) -> tuple[Any, Any]:
    models = durable_db.models
    user = models.User(email="owner@example.test")
    db.add(user)
    db.flush()
    batch = models.BatchJob(
        user_id=user.id,
        name="direct-fixture",
        status="QUEUED",
    )
    db.add(batch)
    db.flush()
    job = models.Job(
        user_id=user.id,
        batch_id=batch.id,
        track_type="circle",
        altitude_m=3.0,
        sensor_noise_level="medium",
        objective_profile="robust",
        status="RUNNING",
        simulator_backend_requested="mock",
        optimizer_strategy="llm_harness",
        max_iterations=2,
        max_total_trials=100,
        current_generation=0,
        provider_turn_cap=2,
        provider_request_cap=2,
        provider_max_retries=0,
        openai_model=_MODEL,
        next_candidate_dispatch_ordinal=1,
    )
    db.add(job)
    db.flush()
    campaign_manifest = _campaign_manifest()
    inventory = campaign_manifest.composite_execution_inventory
    campaign = models.BenchmarkCampaign(
        user_id=user.id,
        campaign_key=campaign_manifest.campaign_key,
        campaign_version=campaign_manifest.campaign_version,
        name=campaign_manifest.name,
        panel=campaign_manifest.panel,
        status="ACTIVE",
        protocol_sha256=campaign_manifest.protocol_sha256,
        manifest_sha256=canonical_sha256(campaign_manifest),
        manifest_json=campaign_manifest.model_dump(mode="json"),
        composite_inventory_sha256=canonical_sha256(inventory),
        composite_inventory_json=inventory.model_dump(mode="json"),
        job_cap=2,
        trial_cap=100,
        logical_turn_cap=2,
        network_request_cap=2,
        input_utf8_byte_cap=10_000_000,
        output_utf8_byte_cap=10_000_000,
        provider_token_cap=10_000_000,
        provider_cost_microusd_cap=10_000_000,
        wall_time_second_cap=1000,
        disk_byte_cap=10_000_000,
    )
    db.add(campaign)
    db.flush()
    arm_manifest = _arm_manifest()
    arm = models.BenchmarkArm(
        campaign_id=campaign.id,
        benchmark_arm_id=arm_manifest.benchmark_arm_id,
        arm_version=arm_manifest.arm_version,
        arm_family=arm_manifest.arm_family,
        proposal_adapter_id=arm_manifest.proposal_adapter_id,
        evaluator_contract_id=arm_manifest.evaluator_contract_id,
        manifest_sha256=canonical_sha256(arm_manifest),
        manifest_json=arm_manifest.model_dump(mode="json"),
        execution_enabled=True,
    )
    db.add(arm)
    db.flush()
    batch_reservation = models.BenchmarkBudgetReservation(
        campaign_id=campaign.id,
        reservation_key="batch-bind/direct-fixture",
        lease_generation=1,
        reason="benchmark-batch-binding",
        reservation_sha256="3" * 64,
        jobs=1,
    )
    db.add(batch_reservation)
    db.flush()
    batch_binding = models.BenchmarkCampaignBatchBinding(
        campaign_id=campaign.id,
        batch_id=batch.id,
        binding_key="direct-fixture",
        binding_sha256="4" * 64,
        batch_ordinal=1,
        lease_generation=1,
        job_count=1,
        budget_reservation_id=batch_reservation.id,
    )
    db.add(batch_binding)
    db.flush()
    scenario_sha = "5" * 64
    qualification_sha = "6" * 64
    request = BenchmarkRunBindingRequestV1(
        run_key="direct-run-001",
        job_id=job.id,
        benchmark_arm_id=arm.benchmark_arm_id,
        arm_version=arm.arm_version,
        algorithm_seed=101,
        simulator_seed_block="crn-001",
        provider_randomness_policy="fixed_seed",
        provider_seed=20260805,
    )
    run = models.BenchmarkCampaignRunBinding(
        campaign_id=campaign.id,
        batch_binding_id=batch_binding.id,
        benchmark_arm_id=arm.id,
        job_id=job.id,
        run_key=request.run_key,
        run_ordinal=1,
        batch_run_ordinal=1,
        algorithm_seed=request.algorithm_seed,
        simulator_seed_block=request.simulator_seed_block,
        provider_randomness_policy=request.provider_randomness_policy,
        provider_seed=request.provider_seed,
        qualification_policy_version="sealed-two-stage-v1",
        scenario_suite_sha256=scenario_sha,
        qualification_contract_sha256=qualification_sha,
        binding_sha256=run_binding_sha256(
            request,
            scenario_suite_sha256=scenario_sha,
            qualification_contract_sha256=qualification_sha,
        ),
    )
    db.add(run)
    db.flush()
    db.add(
        models.BenchmarkBudgetReservation(
            campaign_id=campaign.id,
            reservation_key=f"provider-run/{run.id}",
            lease_generation=1,
            reason=BENCHMARK_DIRECT_RESERVATION_REASON,
            reservation_sha256="7" * 64,
            logical_turns=2,
            network_requests=2,
            input_utf8_bytes=10_000_000,
            output_utf8_bytes=10_000_000,
            provider_tokens=10_000_000,
            provider_cost_microusd=10_000_000,
            wall_time_seconds=1000,
        )
    )
    db.commit()
    db.refresh(job)
    db.refresh(run)
    return job, run


def _observation(job: Any, run: Any) -> BenchmarkObservationV2:
    return BenchmarkObservationV2(
        campaign_id=run.campaign_id,
        run_id=run.id,
        benchmark_arm_id="llm-direct",
        generation_index=job.current_generation + 1,
        next_dispatch_ordinal=job.next_candidate_dispatch_ordinal,
        algorithm_seed=run.algorithm_seed,
        simulator_seed_block_id=run.simulator_seed_block,
        parameter_domain=[
            {
                "name": "kp",
                "baseline": 1.0,
                "minimum": 0.5,
                "maximum": 2.0,
                "value_type": "float",
            }
        ],
        objectives=[{"name": "rmse", "direction": "minimize"}],
        constraints=[{"name": "max_error", "operator": "le", "threshold": 1.0}],
        history=[],
        failure_semantics={"unsafe": "constraint-only", "timeout": "terminal"},
        simulator_budget_remaining=16,
        wall_time_remaining_ms=30_000,
    )


@dataclass
class _Transport:
    response: str | Exception | BaseException
    before_return: Callable[[], None] | None = None
    calls: int = 0

    def complete(self, request: Any, config: Any) -> BenchmarkProviderTransportResult:
        self.calls += 1
        if self.before_return is not None:
            self.before_return()
        if isinstance(self.response, BaseException):
            raise self.response
        return BenchmarkProviderTransportResult(
            response_text=self.response,
            usage=ProviderUsage(input_tokens=100, output_tokens=20, total_tokens=120),
            latency_ms=25,
        )


def _proposal_json(value: float = 1.2) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "decision": "propose",
            "parameters": {"kp": value},
        }
    )


def test_provider_execution_contract_rejects_stringified_budget_numbers() -> None:
    payload = _provider_config().model_dump(mode="json")
    payload["maximum_generations"] = "2"
    with pytest.raises(ValueError):
        BenchmarkProviderExecutionConfigV1.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("provider", "base_url"),
    (
        ("openai", "http://api.openai.com/v1"),
        ("openai", "https://user:password@api.openai.com/v1"),
        ("openai", "https://api.openai.com/v1?redirect=evil"),
        ("openai", "https://api.openai.com.evil.example/v1"),
        ("deepseek", "https://api.openai.com/v1"),
        ("unknown-provider", "https://unknown.example/v1"),
    ),
)
def test_provider_execution_contract_rejects_unapproved_origins(
    provider: str,
    base_url: str,
) -> None:
    payload = _provider_config().model_dump(mode="json")
    payload.update({"provider": provider, "base_url": base_url})
    with pytest.raises(ValueError, match="approved credential-free HTTPS"):
        BenchmarkProviderExecutionConfigV1.model_validate_json(json.dumps(payload))


def test_provider_execution_contract_accepts_exact_deepseek_origin() -> None:
    payload = _provider_config().model_dump(mode="json")
    payload.update(
        {
            "provider": "deepseek",
            "model_snapshot": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com/v1",
        }
    )
    parsed = BenchmarkProviderExecutionConfigV1.model_validate_json(json.dumps(payload))
    assert parsed.provider == "deepseek"
    assert parsed.base_url == "https://api.deepseek.com/v1"


def test_durable_bridge_does_not_promote_direct_arm_before_campaign_reconciliation() -> None:
    descriptor = BENCHMARK_ADAPTER_REGISTRY["llm_direct/v1"]
    inventory = BENCHMARK_METHOD_INVENTORY["llm_direct/v1"]
    assert descriptor.availability == "contract_only"
    assert inventory.execution_readiness == "blocked"
    assert "adapter_not_implemented" in inventory.blocker_codes
    with pytest.raises(ValueError, match="not implemented"):
        create_benchmark_adapter("llm_direct/v1")


def test_direct_attempts_are_committed_before_transport_and_success_is_safe(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)

        def assert_attempts_are_durable() -> None:
            turn = db.scalar(select(models.HarnessCognitiveTurnReceipt))
            request = db.scalar(select(models.ProviderNetworkRequestReceipt))
            assert turn is not None and turn.outcome is None
            assert turn.turn_role == "direct_proposal"
            assert request is not None and request.outcome is None

        transport = _Transport(_proposal_json(), assert_attempts_are_durable)
        result = execute_durable_direct_arm(
            db,
            job,
            _observation(job, run),
            transport=transport,
        )

        assert result.status == "proposal"
        assert result.proposal is not None
        assert result.proposal.parameters == {"kp": 1.2}
        assert result.provider_turns_attempted == result.provider_turns_succeeded == 1
        assert result.provider_requests_attempted == result.provider_requests_succeeded == 1
        serialized = json.dumps(result.safe_receipt, sort_keys=True)
        assert "messages" not in serialized
        assert "system" not in serialized
        assert "user" not in serialized
        assert "request_id" not in serialized
        db.refresh(job)
        assert job.provider_turns_attempted == job.provider_turns_succeeded == 1
        assert job.provider_requests_attempted == job.provider_requests_succeeded == 1


def test_provider_failure_is_fail_closed_and_does_not_persist_exception_text(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        with pytest.raises(BenchmarkDurableLLMBlocked) as exc_info:
            execute_durable_direct_arm(
                db,
                job,
                _observation(job, run),
                transport=_Transport(RuntimeError("api_key=must-not-persist")),
            )
        assert exc_info.value.code == "benchmark_provider_transport_failed"
        turn = db.scalar(select(models.HarnessCognitiveTurnReceipt))
        request = db.scalar(select(models.ProviderNetworkRequestReceipt))
        assert turn is not None and turn.outcome.status == "provider_failed"
        assert request is not None and request.outcome.status == "failed"
        persisted = " ".join(
            str(item.__dict__)
            for item in (turn, turn.outcome, request, request.outcome)
        )
        assert "must-not-persist" not in persisted


def test_schema_failure_records_network_success_but_not_model_success(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        with pytest.raises(BenchmarkDurableLLMBlocked) as exc_info:
            execute_durable_direct_arm(
                db,
                job,
                _observation(job, run),
                transport=_Transport("{}"),
            )
        assert exc_info.value.code == "benchmark_direct_response_invalid"
        turn = db.scalar(select(models.HarnessCognitiveTurnReceipt))
        request = db.scalar(select(models.ProviderNetworkRequestReceipt))
        assert turn is not None and turn.outcome.status == "invalid_schema"
        assert request is not None and request.outcome.status == "succeeded"
        db.refresh(job)
        assert job.provider_turns_succeeded == 0
        assert job.provider_requests_succeeded == 1


def test_first_qualified_stop_consumes_zero_provider_work(durable_db: SimpleNamespace) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        job.first_qualified_candidate_id = "frozen-candidate"
        db.commit()
        transport = _Transport(RuntimeError("must not run"))
        result = execute_durable_direct_arm(
            db,
            job,
            _observation(job, run),
            transport=transport,
        )
        assert result.status == "first_qualified_stop"
        assert transport.calls == 0
        assert db.scalar(select(models.HarnessCognitiveTurnReceipt)) is None
        assert db.scalar(select(models.ProviderNetworkRequestReceipt)) is None


def test_process_crash_leaves_indeterminate_attempt_and_never_replays(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        observation = _observation(job, run)
        with pytest.raises(KeyboardInterrupt):
            execute_durable_direct_arm(
                db,
                job,
                observation,
                transport=_Transport(KeyboardInterrupt()),
            )
        turn = db.scalar(select(models.HarnessCognitiveTurnReceipt))
        request = db.scalar(select(models.ProviderNetworkRequestReceipt))
        assert turn is not None and turn.outcome is None
        assert request is not None and request.outcome is None
        attempted_at = request.attempted_at
        if attempted_at.tzinfo is None:
            attempted_at = attempted_at.replace(tzinfo=timezone.utc)
        assert recover_abandoned_provider_requests(
            db,
            job,
            cognitive_turn_receipt_id=turn.id,
            request_timeout_seconds=10,
            now=attempted_at + timedelta(seconds=71),
        ) == 1
        db.refresh(request)
        assert request.outcome.status == "indeterminate"
        second_transport = _Transport(_proposal_json())
        with pytest.raises(CognitiveTurnPending):
            execute_durable_direct_arm(
                db,
                job,
                observation,
                transport=second_transport,
            )
        assert second_transport.calls == 0
        assert job.provider_requests_attempted == 1


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda job, run, db, models: setattr(job, "provider_max_retries", 1),
            "benchmark_provider_budget_drift",
        ),
        (
            lambda job, run, db, models: setattr(run, "binding_sha256", "f" * 64),
            "benchmark_run_binding_drift",
        ),
        (
            lambda job, run, db, models: db.delete(
                db.scalar(
                    select(models.BenchmarkBudgetReservation).where(
                        models.BenchmarkBudgetReservation.reservation_key
                        == f"provider-run/{run.id}"
                    )
                )
            ),
            "benchmark_provider_budget_unreserved",
        ),
    ],
)
def test_budget_binding_and_retry_drift_fail_before_transport(
    durable_db: SimpleNamespace,
    mutation: Callable[[Any, Any, Session, Any], None],
    expected_code: str,
) -> None:
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        mutation(job, run, db, durable_db.models)
        db.commit()
        transport = _Transport(_proposal_json())
        with pytest.raises(BenchmarkDurableLLMBlocked) as exc_info:
            execute_durable_direct_arm(
                db,
                job,
                _observation(job, run),
                transport=transport,
            )
        assert exc_info.value.code == expected_code
        assert transport.calls == 0


def test_observation_and_engine_source_drift_fail_before_transport(
    durable_db: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        wrong_observation = _observation(job, run).model_copy(
            update={"algorithm_seed": run.algorithm_seed + 1}
        )
        transport = _Transport(_proposal_json())
        with pytest.raises(BenchmarkDurableLLMBlocked) as observation_error:
            execute_durable_direct_arm(
                db,
                job,
                wrong_observation,
                transport=transport,
            )
        assert observation_error.value.code == "benchmark_observation_binding_drift"
        assert transport.calls == 0

        monkeypatch.setenv("DRONEDREAM_SOURCE_COMMIT", "b" * 40)
        with pytest.raises(BenchmarkDurableLLMBlocked) as source_error:
            execute_durable_direct_arm(
                db,
                job,
                _observation(job, run),
                transport=transport,
            )
        assert source_error.value.code == "benchmark_engine_source_drift"
        assert transport.calls == 0
