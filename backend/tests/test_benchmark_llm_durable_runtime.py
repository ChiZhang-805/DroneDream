from __future__ import annotations

import hashlib
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
    BenchmarkBudgetReservationRequestV1,
    BenchmarkCampaignManifestV1,
    BenchmarkObservationV2,
    BenchmarkRunBindingRequestV1,
    BenchmarkUsageDeltaV1,
    canonical_sha256,
)
from app.benchmarking.coordinator import run_binding_sha256
from app.benchmarking.llm_arm_contracts import (
    BENCHMARK_LLM_ARM_POLICIES_SHA256,
    build_llm_turn_request,
    require_llm_arm_policy,
)
from app.benchmarking.llm_durable_runtime import (
    BENCHMARK_DIRECT_RESERVATION_REASON,
    BenchmarkDurableLLMBlocked,
    BenchmarkProviderExecutionConfigV1,
    BenchmarkProviderTransportResult,
    execute_durable_direct_arm,
    execute_durable_llambo_arm,
    execute_durable_react_arm,
)
from app.benchmarking.method_inventory import BENCHMARK_METHOD_INVENTORY
from app.benchmarking.provider_execution_contract import (
    direct_provider_run_capacity,
    provider_run_capacity,
)
from app.benchmarking.provider_usage_reconciliation import (
    BenchmarkProviderUsageBlocked,
    reconcile_direct_provider_run_usage,
)
from app.benchmarking.registry import BENCHMARK_ADAPTER_REGISTRY, create_benchmark_adapter
from app.orchestration.cognitive_budget import (
    CognitiveTurnBlocked,
    CognitiveTurnPending,
    begin_benchmark_llm_turn,
)
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
        maximum_request_utf8_bytes=65_536,
        maximum_response_utf8_bytes=8_192,
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


def _arm_manifest(adapter_id: str = "llm_direct/v1") -> BenchmarkArmManifestV1:
    arm_id = {
        "llm_direct/v1": "llm-direct",
        "llm_react/v1": "llm-react",
        "llambo_uav/v1": "llambo-uav",
    }[adapter_id]
    return BenchmarkArmManifestV1(
        benchmark_arm_id=arm_id,
        arm_version="v1",
        arm_family="llm_harness",
        proposal_adapter_id=adapter_id,
        intervention={"provider_execution": _provider_config().model_dump(mode="json")},
        provider_contract_sha256=BENCHMARK_LLM_ARM_POLICIES_SHA256,
        execution_enabled=True,
    )


def _campaign_manifest(adapter_id: str = "llm_direct/v1") -> BenchmarkCampaignManifestV1:
    turn_cap = 8 if adapter_id == "llm_react/v1" else 2
    return BenchmarkCampaignManifestV1.model_validate(
        {
            "campaign_key": f"durable-{adapter_id.split('/')[0]}-test",
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
                "logical_turns": turn_cap,
                "network_requests": turn_cap,
                "input_utf8_bytes": 10_000_000,
                "output_utf8_bytes": 10_000_000,
                "provider_tokens": 10_000_000,
                "provider_cost_microusd": 10_000_000,
                "wall_time_seconds": 1000,
                "disk_bytes": 10_000_000,
            },
            "arms": [_arm_manifest(adapter_id).model_dump(mode="json")],
        }
    )


def _create_bound_run(
    db: Session,
    durable_db: SimpleNamespace,
    *,
    adapter_id: str = "llm_direct/v1",
) -> tuple[Any, Any]:
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
    turns_per_generation = 4 if adapter_id == "llm_react/v1" else 1
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
        provider_turn_cap=2 * turns_per_generation,
        provider_request_cap=2 * turns_per_generation,
        provider_max_retries=0,
        openai_model=_MODEL,
        llm_access_mode="byok",
        llm_provider="openai",
        llm_base_url=None,
        next_candidate_dispatch_ordinal=1,
    )
    db.add(job)
    db.flush()
    campaign_manifest = _campaign_manifest(adapter_id)
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
        logical_turn_cap=2 * turns_per_generation,
        network_request_cap=2 * turns_per_generation,
        input_utf8_byte_cap=10_000_000,
        output_utf8_byte_cap=10_000_000,
        provider_token_cap=10_000_000,
        provider_cost_microusd_cap=10_000_000,
        wall_time_second_cap=1000,
        disk_byte_cap=10_000_000,
    )
    db.add(campaign)
    db.flush()
    arm_manifest = _arm_manifest(adapter_id)
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
        run_key=f"{adapter_id.split('/')[0]}-run-001",
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
    reservation_usage = provider_run_capacity(
        _provider_config(),
        maximum_turns_per_generation=turns_per_generation,
    )
    reservation_request = BenchmarkBudgetReservationRequestV1(
        reservation_key=f"provider-run/{run.id}",
        lease_generation=1,
        reason=BENCHMARK_DIRECT_RESERVATION_REASON,
        usage=reservation_usage,
    )
    db.add(
        models.BenchmarkBudgetReservation(
            campaign_id=campaign.id,
            reservation_key=reservation_request.reservation_key,
            lease_generation=1,
            reason=BENCHMARK_DIRECT_RESERVATION_REASON,
            reservation_sha256=canonical_sha256(reservation_request),
            **reservation_usage.model_dump(),
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
        benchmark_arm_id=run.arm.benchmark_arm_id,
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
    last_request: Any | None = None

    def complete(self, request: Any, config: Any) -> BenchmarkProviderTransportResult:
        self.calls += 1
        self.last_request = request
        if self.before_return is not None:
            self.before_return()
        if isinstance(self.response, BaseException):
            raise self.response
        return BenchmarkProviderTransportResult(
            response_text=self.response,
            usage=ProviderUsage(input_tokens=100, output_tokens=20, total_tokens=120),
            latency_ms=25,
        )


@dataclass
class _SequenceTransport:
    responses: list[str | Exception | BaseException]
    calls: int = 0

    def complete(self, request: Any, config: Any) -> BenchmarkProviderTransportResult:
        index = self.calls
        self.calls += 1
        response = self.responses[index]
        if isinstance(response, BaseException):
            raise response
        return BenchmarkProviderTransportResult(
            response_text=response,
            usage=ProviderUsage(input_tokens=90, output_tokens=10, total_tokens=100),
            latency_ms=20,
        )


def _proposal_json(value: float = 1.2) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "decision": "propose",
            "parameters": {"kp": value},
        }
    )


def _react_json(
    decision: str,
    *,
    tools: tuple[str, ...] = (),
    selected: str | None = None,
) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "decision": decision,
            "tool_adapter_ids": list(tools),
            "selected_proposal_ref": selected,
        }
    )


def test_react_arm_is_promoted_to_durable_server_managed_execution() -> None:
    descriptor = BENCHMARK_ADAPTER_REGISTRY["llm_react/v1"]
    inventory = BENCHMARK_METHOD_INVENTORY["llm_react/v1"]

    assert descriptor.availability == "implemented"
    assert descriptor.implementation_label == "durable-bounded-react-v1"
    assert inventory.execution_readiness == "ready"
    assert inventory.blocker_codes == ()
    with pytest.raises(ValueError, match="server-managed"):
        create_benchmark_adapter("llm_react/v1")


def test_durable_react_checkpoints_action_then_dispatch_and_recovers_without_replay(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id="llm_react/v1")
        observation = _observation(job, run)
        local = create_benchmark_adapter("random_search/v1").propose(observation)
        transport = _SequenceTransport(
            [
                _react_json("act", tools=("random_search/v1",)),
                _react_json("dispatch", selected=local.candidate_ref),
            ]
        )

        result = execute_durable_react_arm(db, job, observation, transport=transport)

        assert result.status == "proposal"
        assert result.proposal is not None
        assert result.proposal.parameters == local.parameters
        assert result.provider_turns_attempted == result.provider_turns_succeeded == 2
        assert transport.calls == 2
        checkpoints = list(
            db.scalars(
                select(models.BenchmarkLLMReactCheckpoint).order_by(
                    models.BenchmarkLLMReactCheckpoint.turn_index
                )
            )
        )
        assert [item.decision for item in checkpoints] == ["act", "dispatch"]
        assert checkpoints[0].state_json["terminal_receipt"] == {}
        assert checkpoints[1].state_json["final_proposal"]["candidate_ref"] == (
            result.proposal.candidate_ref
        )

        replay = _SequenceTransport([AssertionError("provider replayed")])
        recovered = execute_durable_react_arm(db, job, observation, transport=replay)
        assert recovered.status == "proposal_recovered"
        assert recovered.proposal == result.proposal
        assert replay.calls == 0


def test_durable_react_next_turn_requires_successful_checkpoint(
    durable_db: SimpleNamespace,
) -> None:
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id="llm_react/v1")
        observation = _observation(job, run)
        request = build_llm_turn_request(
            policy=require_llm_arm_policy("llm_react/v1"),
            observation=observation,
            model_snapshot=_MODEL,
            turn_index=1,
            turn_role="react_action",
            response_schema={"type": "object"},
            tool_outputs=[],
        )
        begin_benchmark_llm_turn(
            db,
            job,
            generation_index=observation.generation_index,
            turn_index=1,
            turn_role="react_action",
            adapter_id="llm_react/v1",
            maximum_turns_per_generation=4,
            model_snapshot=_MODEL,
            prompt_sha256=request.prompt_sha256,
            evidence_sha256=request.evidence_sha256,
            schema_sha256=request.response_schema_sha256,
            tool_outputs_sha256=request.tool_outputs_sha256,
        )

        with pytest.raises(CognitiveTurnBlocked) as exc_info:
            begin_benchmark_llm_turn(
                db,
                job,
                generation_index=observation.generation_index,
                turn_index=2,
                turn_role="react_action",
                adapter_id="llm_react/v1",
                maximum_turns_per_generation=4,
                model_snapshot=_MODEL,
                prompt_sha256="a" * 64,
                evidence_sha256="b" * 64,
                schema_sha256="c" * 64,
                tool_outputs_sha256="d" * 64,
            )

        assert exc_info.value.code == "cognitive_predecessor_missing"


def test_durable_react_abandon_is_terminal_and_recoverable(
    durable_db: SimpleNamespace,
) -> None:
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id="llm_react/v1")
        observation = _observation(job, run)
        result = execute_durable_react_arm(
            db,
            job,
            observation,
            transport=_SequenceTransport([_react_json("abandon")]),
        )
        assert result.status == "abandoned"
        assert result.proposal is None
        recovered = execute_durable_react_arm(
            db,
            job,
            observation,
            transport=_SequenceTransport([AssertionError("provider replayed")]),
        )
        assert recovered.status == "abandoned_recovered"


def test_durable_react_terminal_checkpoint_tamper_blocks_without_provider_replay(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id="llm_react/v1")
        observation = _observation(job, run)
        local = create_benchmark_adapter("random_search/v1").propose(observation)
        execute_durable_react_arm(
            db,
            job,
            observation,
            transport=_SequenceTransport(
                [
                    _react_json("act", tools=("random_search/v1",)),
                    _react_json("dispatch", selected=local.candidate_ref),
                ]
            ),
        )
        terminal = db.scalar(
            select(models.BenchmarkLLMReactCheckpoint).where(
                models.BenchmarkLLMReactCheckpoint.turn_index == 2
            )
        )
        assert terminal is not None
        state = dict(terminal.state_json)
        receipt = dict(state["terminal_receipt"])
        receipt["provider_turns_attempted"] = 1
        state["terminal_receipt"] = receipt
        final_proposal = dict(state["final_proposal"])
        final_proposal["proposal_receipt"] = receipt
        state["final_proposal"] = final_proposal
        terminal.state_json = state
        terminal.state_sha256 = canonical_sha256(state)
        db.commit()

        replay = _SequenceTransport([AssertionError("provider replayed")])
        with pytest.raises(BenchmarkDurableLLMBlocked) as exc_info:
            execute_durable_react_arm(db, job, observation, transport=replay)
        assert exc_info.value.code == "benchmark_react_checkpoint_drift"
        assert replay.calls == 0


def test_durable_react_rejects_repeated_tool_without_replaying_consumed_turn(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id="llm_react/v1")
        observation = _observation(job, run)
        transport = _SequenceTransport(
            [
                _react_json("act", tools=("random_search/v1",)),
                _react_json("act", tools=("random_search/v1",)),
            ]
        )
        with pytest.raises(BenchmarkDurableLLMBlocked) as exc_info:
            execute_durable_react_arm(db, job, observation, transport=transport)
        assert exc_info.value.code == "benchmark_react_state_rejected"
        assert transport.calls == 2
        assert (
            db.scalar(
                select(models.BenchmarkLLMReactCheckpoint).where(
                    models.BenchmarkLLMReactCheckpoint.turn_index == 2
                )
            )
            is None
        )
        second = db.scalar(
            select(models.HarnessCognitiveTurnReceipt).where(
                models.HarnessCognitiveTurnReceipt.turn_index == 2
            )
        )
        assert second is not None and second.outcome.status == "invalid_schema"
        replay = _SequenceTransport([AssertionError("provider replayed")])
        with pytest.raises(CognitiveTurnBlocked) as replay_error:
            execute_durable_react_arm(db, job, observation, transport=replay)
        assert replay_error.value.code == "turn_result_not_replayable"
        assert replay.calls == 0


def test_durable_react_fourth_turn_cannot_extend_the_tool_loop(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id="llm_react/v1")
        observation = _observation(job, run)
        transport = _SequenceTransport(
            [
                _react_json("act", tools=("random_search/v1",)),
                _react_json("act", tools=("seeded_halton/v1",)),
                _react_json("act", tools=("repo_constrained_mobo/v1",)),
                _react_json("act", tools=("optimizer_portfolio/v1",)),
            ]
        )

        with pytest.raises(BenchmarkDurableLLMBlocked) as exc_info:
            execute_durable_react_arm(db, job, observation, transport=transport)

        assert exc_info.value.code == "benchmark_react_state_rejected"
        assert transport.calls == 4
        checkpoints = list(
            db.scalars(
                select(models.BenchmarkLLMReactCheckpoint).order_by(
                    models.BenchmarkLLMReactCheckpoint.turn_index
                )
            )
        )
        assert [item.turn_index for item in checkpoints] == [1, 2, 3]
        fourth = db.scalar(
            select(models.HarnessCognitiveTurnReceipt).where(
                models.HarnessCognitiveTurnReceipt.turn_index == 4
            )
        )
        assert fourth is not None and fourth.outcome.status == "invalid_schema"
        assert job.provider_turns_attempted == 4
        assert job.provider_requests_attempted == 4


def test_durable_react_crash_after_checkpoint_never_replays_paid_next_turn(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id="llm_react/v1")
        observation = _observation(job, run)
        transport = _SequenceTransport(
            [
                _react_json("act", tools=("random_search/v1",)),
                KeyboardInterrupt("simulated process crash"),
            ]
        )
        with pytest.raises(KeyboardInterrupt):
            execute_durable_react_arm(db, job, observation, transport=transport)
        assert transport.calls == 2
        checkpoints = list(db.scalars(select(models.BenchmarkLLMReactCheckpoint)))
        assert len(checkpoints) == 1 and checkpoints[0].turn_index == 1
        second = db.scalar(
            select(models.HarnessCognitiveTurnReceipt).where(
                models.HarnessCognitiveTurnReceipt.turn_index == 2
            )
        )
        assert second is not None and second.outcome is None
        replay = _SequenceTransport([AssertionError("provider replayed")])
        with pytest.raises(CognitiveTurnPending):
            execute_durable_react_arm(db, job, observation, transport=replay)
        assert replay.calls == 0


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


def test_direct_provider_capacity_is_deterministic_and_worst_case() -> None:
    capacity = direct_provider_run_capacity(_provider_config())

    assert capacity.logical_turns == 2
    assert capacity.network_requests == 2
    assert capacity.input_utf8_bytes == 65_536 * 2
    assert capacity.output_utf8_bytes == 8_192 * 2
    assert capacity.provider_tokens == (65_536 + 128) * 2
    assert capacity.provider_cost_microusd == 264_192
    assert capacity.wall_time_seconds == 20
    react_capacity = provider_run_capacity(_provider_config(), maximum_turns_per_generation=4)
    assert react_capacity.logical_turns == 8
    assert react_capacity.network_requests == 8
    assert react_capacity.provider_cost_microusd == capacity.provider_cost_microusd * 4


def test_direct_arm_is_promoted_only_to_server_managed_durable_execution() -> None:
    descriptor = BENCHMARK_ADAPTER_REGISTRY["llm_direct/v1"]
    inventory = BENCHMARK_METHOD_INVENTORY["llm_direct/v1"]
    assert descriptor.availability == "implemented"
    assert inventory.execution_readiness == "ready"
    assert inventory.blocker_codes == ()
    with pytest.raises(ValueError, match="server-managed"):
        create_benchmark_adapter("llm_direct/v1")


def test_llambo_arm_is_promoted_as_an_adaptation_not_a_standard_reproduction() -> None:
    descriptor = BENCHMARK_ADAPTER_REGISTRY["llambo_uav/v1"]
    inventory = BENCHMARK_METHOD_INVENTORY["llambo_uav/v1"]
    assert descriptor.availability == "implemented"
    assert descriptor.method_classification == "adapted_reference"
    assert inventory.execution_readiness == "ready"
    assert inventory.blocker_codes == ()
    assert any(
        "not claimed as a standard LLAMBO reproduction" in note
        for note in inventory.reproducibility_notes
    )
    with pytest.raises(ValueError, match="server-managed"):
        create_benchmark_adapter("llambo_uav/v1")


def _production_observation(job: Any, run: Any) -> BenchmarkObservationV2:
    return _observation(job, run).model_copy(
        update={
            "parameter_domain": [
                {
                    "name": "MPC_XY_P",
                    "baseline": 0.95,
                    "minimum": 0.6,
                    "maximum": 1.3,
                    "value_type": "float",
                }
            ]
        }
    )


def _production_proposal_json(value: float = 1.1) -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "decision": "propose",
            "parameters": {"MPC_XY_P": value},
        }
    )


def _prepare_production_job(job: Any) -> None:
    job.parameter_space_json = [
        {
            "name": "MPC_XY_P",
            "baseline": 0.95,
            "minimum": 0.6,
            "maximum": 1.3,
            "enabled": True,
            "locked": False,
        }
    ]
    job.baseline_parameter_json = {"MPC_XY_P": 0.95}


def test_production_dispatch_routes_direct_handoff_to_candidate_and_trials(
    durable_db: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.orchestration import job_manager

    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        _prepare_production_job(job)
        db.commit()
        observation = _production_observation(job, run)
        context = SimpleNamespace(
            arm=SimpleNamespace(
                proposal_adapter_id="llm_direct/v1",
                benchmark_arm_id="llm-direct",
            ),
            binding=run,
        )
        transport = _Transport(_production_proposal_json())
        monkeypatch.setattr(
            job_manager,
            "build_benchmark_job_observation",
            lambda _db, _job: (context, observation),
        )
        monkeypatch.setattr(
            job_manager,
            "build_job_secret_benchmark_transport",
            lambda _db, _job, _provider: transport,
        )

        result = job_manager.dispatch_next_benchmark_generation(db, job)

        assert result.status == "dispatched"
        assert result.dispatched_candidates == 1
        assert transport.calls == 1
        candidates = list(
            db.scalars(
                select(durable_db.models.CandidateParameterSet).where(
                    durable_db.models.CandidateParameterSet.job_id == job.id,
                    durable_db.models.CandidateParameterSet.is_baseline.is_(False),
                )
            )
        )
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.parameter_json["MPC_XY_P"] == pytest.approx(1.1)
        assert candidate.proposal_reason == "benchmark:llm_direct/v1"
        assert list(
            db.scalars(
                select(durable_db.models.Trial).where(
                    durable_db.models.Trial.candidate_id == candidate.id
                )
            )
        )
        context_payload = candidate.optimizer_metadata_json["benchmark_proposal_context"]
        assert context_payload["proposal_adapter_id"] == "llm_direct/v1"
        assert "messages" not in json.dumps(candidate.optimizer_metadata_json)


def test_production_dispatch_routes_llambo_handoff_to_candidate_and_trials(
    durable_db: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.orchestration import job_manager

    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id="llambo_uav/v1")
        _prepare_production_job(job)
        db.commit()
        observation = _production_observation(job, run)
        context = SimpleNamespace(
            arm=SimpleNamespace(
                proposal_adapter_id="llambo_uav/v1",
                benchmark_arm_id="llambo-uav",
            ),
            binding=run,
        )
        transport = _Transport(_production_proposal_json(1.15))
        monkeypatch.setattr(
            job_manager,
            "build_benchmark_job_observation",
            lambda _db, _job: (context, observation),
        )
        monkeypatch.setattr(
            job_manager,
            "build_job_secret_benchmark_transport",
            lambda _db, _job, _provider: transport,
        )

        result = job_manager.dispatch_next_benchmark_generation(db, job)

        assert result.status == "dispatched"
        assert transport.calls == 1
        candidate = db.scalar(
            select(durable_db.models.CandidateParameterSet).where(
                durable_db.models.CandidateParameterSet.job_id == job.id,
                durable_db.models.CandidateParameterSet.is_baseline.is_(False),
            )
        )
        assert candidate is not None
        assert candidate.parameter_json["MPC_XY_P"] == pytest.approx(1.15)
        assert candidate.proposal_reason == "benchmark:llambo_uav/v1"
        payload = candidate.optimizer_metadata_json["benchmark_proposal_context"]
        assert payload["proposal_adapter_id"] == "llambo_uav/v1"
        assert "messages" not in json.dumps(candidate.optimizer_metadata_json)


def test_production_dispatch_routes_bounded_react_checkpoint_to_candidate_and_trials(
    durable_db: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.orchestration import job_manager

    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id="llm_react/v1")
        _prepare_production_job(job)
        db.commit()
        observation = _production_observation(job, run)
        local = create_benchmark_adapter("random_search/v1").propose(observation)
        context = SimpleNamespace(
            arm=SimpleNamespace(
                proposal_adapter_id="llm_react/v1",
                benchmark_arm_id="llm-react",
            ),
            binding=run,
        )
        transport = _SequenceTransport(
            [
                _react_json("act", tools=("random_search/v1",)),
                _react_json("dispatch", selected=local.candidate_ref),
            ]
        )
        monkeypatch.setattr(
            job_manager,
            "build_benchmark_job_observation",
            lambda _db, _job: (context, observation),
        )
        monkeypatch.setattr(
            job_manager,
            "build_job_secret_benchmark_transport",
            lambda _db, _job, _provider: transport,
        )

        result = job_manager.dispatch_next_benchmark_generation(db, job)

        assert result.status == "dispatched"
        assert result.dispatched_candidates == 1
        assert transport.calls == 2
        candidate = db.scalar(
            select(durable_db.models.CandidateParameterSet).where(
                durable_db.models.CandidateParameterSet.job_id == job.id,
                durable_db.models.CandidateParameterSet.is_baseline.is_(False),
            )
        )
        assert candidate is not None
        assert candidate.parameter_json["MPC_XY_P"] == pytest.approx(local.parameters["MPC_XY_P"])
        assert candidate.proposal_reason == "benchmark:llm_react/v1"
        assert list(
            db.scalars(
                select(durable_db.models.Trial).where(
                    durable_db.models.Trial.candidate_id == candidate.id
                )
            )
        )
        payload = candidate.optimizer_metadata_json["benchmark_proposal_context"]
        assert payload["proposal_adapter_id"] == "llm_react/v1"
        assert "messages" not in json.dumps(candidate.optimizer_metadata_json)


def test_production_dispatch_recovers_react_checkpoint_without_secret_resolution(
    durable_db: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.orchestration import job_manager

    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id="llm_react/v1")
        _prepare_production_job(job)
        db.commit()
        observation = _production_observation(job, run)
        local = create_benchmark_adapter("random_search/v1").propose(observation)
        transport = _SequenceTransport(
            [
                _react_json("act", tools=("random_search/v1",)),
                _react_json("dispatch", selected=local.candidate_ref),
            ]
        )
        execute_durable_react_arm(db, job, observation, transport=transport)
        assert transport.calls == 2

        context = SimpleNamespace(
            arm=SimpleNamespace(
                proposal_adapter_id="llm_react/v1",
                benchmark_arm_id="llm-react",
            ),
            binding=run,
        )
        secret_resolutions = 0

        def forbidden_secret_resolution(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal secret_resolutions
            secret_resolutions += 1
            raise AssertionError("checkpoint recovery must not resolve a credential")

        monkeypatch.setattr(
            job_manager,
            "build_benchmark_job_observation",
            lambda _db, _job: (context, observation),
        )
        monkeypatch.setattr(
            job_manager,
            "build_job_secret_benchmark_transport",
            forbidden_secret_resolution,
        )

        result = job_manager.dispatch_next_benchmark_generation(db, job)

        assert result.status == "dispatched"
        assert result.dispatched_candidates == 1
        assert secret_resolutions == 0
        assert (
            len(
                list(
                    db.scalars(
                        select(durable_db.models.CandidateParameterSet).where(
                            durable_db.models.CandidateParameterSet.job_id == job.id,
                            durable_db.models.CandidateParameterSet.is_baseline.is_(False),
                        )
                    )
                )
            )
            == 1
        )
        assert len(list(db.scalars(select(durable_db.models.ProviderNetworkRequestReceipt)))) == 2


def test_production_dispatch_recovers_handoff_without_secret_or_provider_replay(
    durable_db: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.orchestration import job_manager

    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        _prepare_production_job(job)
        db.commit()
        observation = _production_observation(job, run)
        first_transport = _Transport(_production_proposal_json(1.2))
        execute_durable_direct_arm(db, job, observation, transport=first_transport)
        assert first_transport.calls == 1

        context = SimpleNamespace(
            arm=SimpleNamespace(
                proposal_adapter_id="llm_direct/v1",
                benchmark_arm_id="llm-direct",
            ),
            binding=run,
        )
        secret_resolutions = 0

        def forbidden_secret_resolution(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal secret_resolutions
            secret_resolutions += 1
            raise AssertionError("recovery must not resolve a credential")

        monkeypatch.setattr(
            job_manager,
            "build_benchmark_job_observation",
            lambda _db, _job: (context, observation),
        )
        monkeypatch.setattr(
            job_manager,
            "build_job_secret_benchmark_transport",
            forbidden_secret_resolution,
        )

        result = job_manager.dispatch_next_benchmark_generation(db, job)

        assert result.status == "dispatched"
        assert secret_resolutions == 0
        assert (
            len(
                list(
                    db.scalars(
                        select(durable_db.models.CandidateParameterSet).where(
                            durable_db.models.CandidateParameterSet.job_id == job.id,
                            durable_db.models.CandidateParameterSet.is_baseline.is_(False),
                        )
                    )
                )
            )
            == 1
        )
        assert len(list(db.scalars(select(durable_db.models.ProviderNetworkRequestReceipt)))) == 1


@pytest.mark.parametrize(
    ("adapter_id", "arm_id"),
    (("llm_direct/v1", "llm-direct"), ("llm_react/v1", "llm-react")),
)
def test_production_dispatch_without_job_secret_fails_before_attempt(
    durable_db: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    adapter_id: str,
    arm_id: str,
) -> None:
    from app.orchestration import job_manager

    monkeypatch.setenv("OPENAI_API_KEY", "environment-key-must-not-be-consumed")
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id=adapter_id)
        _prepare_production_job(job)
        db.commit()
        observation = _production_observation(job, run)
        context = SimpleNamespace(
            arm=SimpleNamespace(
                proposal_adapter_id=adapter_id,
                benchmark_arm_id=arm_id,
            ),
            binding=run,
        )
        monkeypatch.setattr(
            job_manager,
            "build_benchmark_job_observation",
            lambda _db, _job: (context, observation),
        )

        result = job_manager.dispatch_next_benchmark_generation(db, job)

        assert result.status == "benchmark_blocked"
        assert result.error_code == "benchmark_provider_credential_unavailable"
        assert "environment-key-must-not-be-consumed" not in (result.error or "")
        assert job.provider_turns_attempted == 0
        assert job.provider_requests_attempted == 0
        assert not list(db.scalars(select(durable_db.models.HarnessCognitiveTurnReceipt)))
        assert not list(db.scalars(select(durable_db.models.ProviderNetworkRequestReceipt)))


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
        request_receipt = db.scalar(select(models.ProviderNetworkRequestReceipt))
        handoff = db.scalar(select(models.BenchmarkDirectProposalHandoff))
        assert request_receipt is not None
        assert handoff is not None
        assert handoff.parameters_json == {"kp": 1.2}
        assert handoff.parameter_sha256 == canonical_sha256({"kp": 1.2})
        assert handoff.proposal_receipt_sha256 == canonical_sha256(result.safe_receipt)
        assert transport.last_request.request_body()["seed"] == 20260805
        assert request_receipt.request_body_sha256 == transport.last_request.request_body_sha256
        reconciliation = reconcile_direct_provider_run_usage(db, run.id)
        assert reconciliation.status == "complete"
        assert reconciliation.actual_observed.logical_turns == 1
        assert reconciliation.actual_observed.network_requests == 1
        assert reconciliation.actual_observed.provider_tokens == 120
        assert reconciliation.actual_observed.provider_cost_microusd == 360
        assert reconciliation.actual_observed.wall_time_seconds == 1
        assert result.safe_receipt["provider_usage_reconciliation_sha256"] == canonical_sha256(
            reconciliation
        )
        serialized = json.dumps(result.safe_receipt, sort_keys=True)
        assert "messages" not in serialized
        assert "system" not in serialized
        assert "user" not in serialized
        assert "request_id" not in serialized
        db.refresh(job)
        assert job.provider_turns_attempted == job.provider_turns_succeeded == 1
        assert job.provider_requests_attempted == job.provider_requests_succeeded == 1


def test_successful_direct_proposal_recovers_without_replaying_provider(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        observation = _observation(job, run)
        first_transport = _Transport(_proposal_json(1.35))
        first = execute_durable_direct_arm(
            db,
            job,
            observation,
            transport=first_transport,
        )
        assert first.status == "proposal"
        assert first_transport.calls == 1

        replay_transport = _Transport(RuntimeError("must not replay"))
        recovered = execute_durable_direct_arm(
            db,
            job,
            observation,
            transport=replay_transport,
        )
        assert recovered.status == "proposal_recovered"
        assert recovered.recovered_from_handoff is True
        assert recovered.proposal == first.proposal
        assert recovered.safe_receipt == first.safe_receipt
        assert replay_transport.calls == 0
        assert db.scalar(select(models.HarnessCognitiveTurnReceipt)) is not None
        assert len(list(db.scalars(select(models.ProviderNetworkRequestReceipt)))) == 1
        assert len(list(db.scalars(select(models.BenchmarkDirectProposalHandoff)))) == 1


def test_llambo_attempt_is_durable_and_recovers_without_provider_replay(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id="llambo_uav/v1")
        observation = _observation(job, run)

        def assert_attempts_are_durable() -> None:
            turn = db.scalar(select(models.HarnessCognitiveTurnReceipt))
            request = db.scalar(select(models.ProviderNetworkRequestReceipt))
            assert turn is not None and turn.outcome is None
            assert turn.turn_role == "llambo_proposal"
            assert turn.trigger_policy_version == "benchmark-llambo-uav-v1"
            assert turn.trigger_reasons_json == ["preregistered-llambo-uav-turn"]
            assert request is not None and request.outcome is None

        first_transport = _Transport(_proposal_json(1.35), assert_attempts_are_durable)
        first = execute_durable_llambo_arm(
            db,
            job,
            observation,
            transport=first_transport,
        )
        assert first.status == "proposal"
        assert first_transport.calls == 1
        assert first.proposal is not None
        assert first.proposal.reason_code == "benchmark-llambo-uav"
        assert first.safe_receipt["adaptation_policy_sha256"] == canonical_sha256(
            require_llm_arm_policy("llambo_uav/v1")
        )
        handoff = db.scalar(select(models.BenchmarkLLAMBOProposalHandoff))
        assert handoff is not None
        assert db.scalar(select(models.BenchmarkDirectProposalHandoff)) is None

        replay_transport = _Transport(RuntimeError("must not replay"))
        recovered = execute_durable_llambo_arm(
            db,
            job,
            observation,
            transport=replay_transport,
        )
        assert recovered.status == "proposal_recovered"
        assert recovered.recovered_from_handoff is True
        assert recovered.proposal == first.proposal
        assert replay_transport.calls == 0
        assert len(list(db.scalars(select(models.ProviderNetworkRequestReceipt)))) == 1


def test_llambo_adaptation_policy_tamper_blocks_without_provider_replay(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id="llambo_uav/v1")
        observation = _observation(job, run)
        execute_durable_llambo_arm(
            db,
            job,
            observation,
            transport=_Transport(_proposal_json()),
        )
        handoff = db.scalar(select(models.BenchmarkLLAMBOProposalHandoff))
        assert handoff is not None
        tampered = dict(handoff.proposal_receipt_json)
        tampered["adaptation_policy_sha256"] = "0" * 64
        handoff.proposal_receipt_json = tampered
        handoff.proposal_receipt_sha256 = canonical_sha256(tampered)
        db.commit()

        transport = _Transport(RuntimeError("must not replay"))
        with pytest.raises(BenchmarkDurableLLMBlocked) as exc_info:
            execute_durable_llambo_arm(
                db,
                job,
                observation,
                transport=transport,
            )
        assert exc_info.value.code == "benchmark_llambo_handoff_receipt_drift"
        assert transport.calls == 0


def test_direct_handoff_persists_only_validated_safe_material(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        result = execute_durable_direct_arm(
            db,
            job,
            _observation(job, run),
            transport=_Transport(_proposal_json()),
        )
        handoff = db.scalar(select(models.BenchmarkDirectProposalHandoff))
        assert handoff is not None
        persisted = json.dumps(
            {
                "schema": handoff.handoff_schema,
                "parameters": handoff.parameters_json,
                "receipt": handoff.proposal_receipt_json,
            },
            sort_keys=True,
        )
        assert result.proposal is not None
        assert result.proposal.parameters == handoff.parameters_json
        for forbidden in (
            "messages",
            "system",
            "user",
            "request_id",
            "api_key",
            _proposal_json(),
        ):
            assert forbidden not in persisted


def test_direct_handoff_cross_field_tamper_blocks_without_provider_replay(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        observation = _observation(job, run)
        execute_durable_direct_arm(
            db,
            job,
            observation,
            transport=_Transport(_proposal_json()),
        )
        handoff = db.scalar(select(models.BenchmarkDirectProposalHandoff))
        assert handoff is not None
        tampered = dict(handoff.proposal_receipt_json)
        tampered["campaign_id"] = "campaign-from-another-run"
        handoff.proposal_receipt_json = tampered
        handoff.proposal_receipt_sha256 = canonical_sha256(tampered)
        db.commit()

        transport = _Transport(RuntimeError("must not replay"))
        with pytest.raises(BenchmarkDurableLLMBlocked) as exc_info:
            execute_durable_direct_arm(
                db,
                job,
                observation,
                transport=transport,
            )
        assert exc_info.value.code == "benchmark_direct_handoff_receipt_drift"
        assert transport.calls == 0


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
        reconciliation = reconcile_direct_provider_run_usage(db, run.id)
        assert reconciliation.status == "usage_incomplete"
        assert reconciliation.cognitive_turns.failed == 1
        assert reconciliation.network_requests.failed == 1
        assert reconciliation.actual_observed.logical_turns == 1
        assert reconciliation.actual_observed.network_requests == 1
        persisted = " ".join(
            str(item.__dict__) for item in (turn, turn.outcome, request, request.outcome)
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


def test_response_byte_cap_records_consumed_request_but_rejects_model_result(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    oversized_response = "x" * 8_193
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        with pytest.raises(BenchmarkDurableLLMBlocked) as exc_info:
            execute_durable_direct_arm(
                db,
                job,
                _observation(job, run),
                transport=_Transport(oversized_response),
            )
        assert exc_info.value.code == "benchmark_provider_response_too_large"
        turn = db.scalar(select(models.HarnessCognitiveTurnReceipt))
        request = db.scalar(select(models.ProviderNetworkRequestReceipt))
        assert turn is not None and turn.outcome.status == "invalid_schema"
        assert turn.outcome.error_code == "benchmark_provider_response_too_large"
        assert request is not None and request.outcome.status == "succeeded"
        assert request.outcome.output_utf8_bytes == 8_193
        assert (
            request.outcome.response_sha256
            == hashlib.sha256(oversized_response.encode("utf-8")).hexdigest()
        )
        assert oversized_response not in str(request.outcome.__dict__)
        db.refresh(job)
        assert job.provider_turns_succeeded == 0
        assert job.provider_requests_succeeded == 1


@pytest.mark.parametrize(
    "adapter_id",
    ("llm_direct/v1", "llm_react/v1", "llambo_uav/v1"),
)
def test_first_qualified_stop_consumes_zero_provider_work(
    durable_db: SimpleNamespace,
    adapter_id: str,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db, adapter_id=adapter_id)
        job.first_qualified_candidate_id = "frozen-candidate"
        db.commit()
        transport = _Transport(RuntimeError("must not run"))
        executor = {
            "llm_direct/v1": execute_durable_direct_arm,
            "llm_react/v1": execute_durable_react_arm,
            "llambo_uav/v1": execute_durable_llambo_arm,
        }[adapter_id]
        result = executor(db, job, _observation(job, run), transport=transport)
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
        assert (
            recover_abandoned_provider_requests(
                db,
                job,
                cognitive_turn_receipt_id=turn.id,
                request_timeout_seconds=10,
                now=attempted_at + timedelta(seconds=71),
            )
            == 1
        )
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


def test_missing_provider_usage_is_durable_but_cannot_produce_a_proposal(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models

    @dataclass
    class _MissingUsageTransport:
        def complete(self, request: Any, config: Any) -> BenchmarkProviderTransportResult:
            return BenchmarkProviderTransportResult(
                response_text=_proposal_json(),
                usage=ProviderUsage(),
                latency_ms=25,
            )

    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        with pytest.raises(BenchmarkDurableLLMBlocked) as exc_info:
            execute_durable_direct_arm(
                db,
                job,
                _observation(job, run),
                transport=_MissingUsageTransport(),
            )
        assert exc_info.value.code == "benchmark_provider_usage_incomplete"
        request = db.scalar(select(models.ProviderNetworkRequestReceipt))
        turn = db.scalar(select(models.HarnessCognitiveTurnReceipt))
        assert request is not None and request.outcome.status == "succeeded"
        assert request.outcome.total_tokens is None
        assert turn is not None and turn.outcome.status == "provider_failed"
        reconciliation = reconcile_direct_provider_run_usage(db, run.id)
        assert reconciliation.status == "usage_incomplete"
        assert reconciliation.network_requests.succeeded == 1
        assert reconciliation.requests_with_incomplete_usage == 1


def test_indeterminate_attempt_is_counted_and_never_presented_as_complete(
    durable_db: SimpleNamespace,
) -> None:
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        with pytest.raises(KeyboardInterrupt):
            execute_durable_direct_arm(
                db,
                job,
                _observation(job, run),
                transport=_Transport(KeyboardInterrupt()),
            )
        reconciliation = reconcile_direct_provider_run_usage(db, run.id)
        assert reconciliation.status == "indeterminate"
        assert reconciliation.cognitive_turns.indeterminate == 1
        assert reconciliation.network_requests.indeterminate == 1
        assert reconciliation.actual_observed.logical_turns == 1
        assert reconciliation.actual_observed.network_requests == 1


def test_reservation_hash_drift_blocks_before_transport(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        reservation = db.scalar(
            select(models.BenchmarkBudgetReservation).where(
                models.BenchmarkBudgetReservation.reservation_key == f"provider-run/{run.id}"
            )
        )
        assert reservation is not None
        reservation.reservation_sha256 = "f" * 64
        db.commit()
        transport = _Transport(_proposal_json())
        with pytest.raises(BenchmarkDurableLLMBlocked) as exc_info:
            execute_durable_direct_arm(
                db,
                job,
                _observation(job, run),
                transport=transport,
            )
        assert exc_info.value.code == "benchmark_provider_reservation_hash_drift"
        assert transport.calls == 0


@pytest.mark.parametrize("delta", [-1, 1])
def test_reservation_capacity_drift_blocks_before_transport(
    durable_db: SimpleNamespace,
    delta: int,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        reservation = db.scalar(
            select(models.BenchmarkBudgetReservation).where(
                models.BenchmarkBudgetReservation.reservation_key == f"provider-run/{run.id}"
            )
        )
        assert reservation is not None
        reservation.input_utf8_bytes += delta
        changed_usage = BenchmarkUsageDeltaV1(
            **{field: getattr(reservation, field) for field in BenchmarkUsageDeltaV1.model_fields}
        )
        reservation.reservation_sha256 = canonical_sha256(
            BenchmarkBudgetReservationRequestV1(
                reservation_key=reservation.reservation_key,
                lease_generation=reservation.lease_generation,
                reason=reservation.reason,
                usage=changed_usage,
            )
        )
        db.commit()
        transport = _Transport(_proposal_json())

        with pytest.raises(BenchmarkDurableLLMBlocked) as exc_info:
            execute_durable_direct_arm(
                db,
                job,
                _observation(job, run),
                transport=transport,
            )

        assert exc_info.value.code == "benchmark_provider_budget_drift"
        assert transport.calls == 0


def test_reconciliation_rejects_actual_usage_beyond_rebound_capacity(
    durable_db: SimpleNamespace,
) -> None:
    models = durable_db.models
    with Session(durable_db.engine) as db:
        job, run = _create_bound_run(db, durable_db)
        execute_durable_direct_arm(
            db,
            job,
            _observation(job, run),
            transport=_Transport(_proposal_json()),
        )
        reservation = db.scalar(
            select(models.BenchmarkBudgetReservation).where(
                models.BenchmarkBudgetReservation.reservation_key == f"provider-run/{run.id}"
            )
        )
        assert reservation is not None
        reservation.output_utf8_bytes = 1
        changed_usage = BenchmarkUsageDeltaV1(
            jobs=reservation.jobs,
            trials=reservation.trials,
            logical_turns=reservation.logical_turns,
            network_requests=reservation.network_requests,
            input_utf8_bytes=reservation.input_utf8_bytes,
            output_utf8_bytes=reservation.output_utf8_bytes,
            provider_tokens=reservation.provider_tokens,
            provider_cost_microusd=reservation.provider_cost_microusd,
            wall_time_seconds=reservation.wall_time_seconds,
            disk_bytes=reservation.disk_bytes,
        )
        reservation.reservation_sha256 = canonical_sha256(
            BenchmarkBudgetReservationRequestV1(
                reservation_key=reservation.reservation_key,
                lease_generation=reservation.lease_generation,
                reason=reservation.reason,
                usage=changed_usage,
            )
        )
        db.commit()
        with pytest.raises(BenchmarkProviderUsageBlocked) as exc_info:
            reconcile_direct_provider_run_usage(db, run.id)
        assert exc_info.value.code == "benchmark_provider_usage_exceeds_reservation"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda job, run, db, models: setattr(job, "llm_access_mode", "platform"),
            "benchmark_provider_access_mode_drift",
        ),
        (
            lambda job, run, db, models: setattr(job, "llm_provider", "deepseek"),
            "benchmark_provider_identity_drift",
        ),
        (
            lambda job, run, db, models: setattr(
                job, "llm_base_url", "https://api.deepseek.com/v1"
            ),
            "benchmark_provider_endpoint_drift",
        ),
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
