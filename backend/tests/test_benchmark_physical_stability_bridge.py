from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app import schemas
from app.benchmarking.contracts import CompositeExecutionInventoryV1, canonical_sha256
from app.benchmarking.physical_stability import (
    build_physical_stability_manifest,
    compile_physical_stability_trial_plan,
)
from app.benchmarking.physical_stability_bridge import (
    PhysicalStabilityExecutionBundleV1,
    PhysicalStabilityJobCreateObservationV1,
    PhysicalStabilityTerminalObservationV1,
    PhysicalStabilityTrialObservationV1,
    build_physical_stability_execution_bundle,
    close_physical_stability_job,
    dispatch_next_physical_stability_job,
    require_manual_reconciliation_after_unobserved_dispatch,
)
from app.benchmarking.physical_stability_execution import (
    PhysicalStabilityExecutionAuthorizationV1,
    build_physical_stability_execution_ledger,
)
from app.services.jobs import _validate_real_cli_scenario_effect_contract

_SOURCE = "a" * 40
_SHA = "b" * 64
_NOW = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)


def _component(component_id: str, *, source: str | None = _SOURCE) -> dict[str, object]:
    return {
        "component_id": component_id,
        "version": "unit-v1",
        "source_commit": source,
        "artifact_sha256": _SHA,
        "manifest_sha256": _SHA,
    }


def _contracts():
    inventory = CompositeExecutionInventoryV1.model_validate(
        {
            "repository_subject_commit": _SOURCE,
            "evaluator_subject_commit": _SOURCE,
            "campaign_coordinator_subject_commit": _SOURCE,
            "evidence_head_commit": None,
            "desktop": _component("desktop"),
            "runtime_base": _component("runtime-base", source="c" * 40),
            "engine_pack": _component("engine-pack"),
            "px4": _component("px4", source="d" * 40),
            "gazebo": _component("gazebo", source=None),
            "prompt_registry_sha256": _SHA,
            "response_schema_sha256": _SHA,
            "tool_registry_sha256": _SHA,
            "model_matrix_sha256": _SHA,
            "machine_profile_sha256": _SHA,
            "concurrency_profile_sha256": _SHA,
        }
    )
    manifest = build_physical_stability_manifest(
        repository_subject_commit=_SOURCE,
        composite_execution_inventory=inventory,
    )
    plan = compile_physical_stability_trial_plan(manifest)
    bundle = build_physical_stability_execution_bundle(manifest, plan)
    authorization = PhysicalStabilityExecutionAuthorizationV1(
        authorization_id="p5-red-window-bridge-unit",
        authorization_nonce="1" * 32,
        opaque_actor_sha256="2" * 64,
        user_confirmation_receipt_sha256="3" * 64,
        repository_subject_commit=_SOURCE,
        manifest_sha256=canonical_sha256(manifest),
        plan_sha256=canonical_sha256(plan),
        composite_execution_inventory_sha256=canonical_sha256(inventory),
        runtime_base_manifest_sha256=inventory.runtime_base.manifest_sha256,
        engine_pack_id="sha256:" + "4" * 64,
        engine_pack_manifest_sha256=inventory.engine_pack.manifest_sha256,
        issued_at_utc=_NOW - timedelta(minutes=1),
        expires_at_utc=_NOW + timedelta(hours=6),
    )
    ledger = build_physical_stability_execution_ledger(
        manifest,
        plan,
        authorization,
        now_utc=_NOW,
    )
    return manifest, plan, bundle, ledger


class _Store:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.checkpoints = []

    def persist(self, ledger, transition) -> None:
        if self.fail_first and not self.checkpoints:
            raise RuntimeError("fixture checkpoint failure")
        assert transition.after_ledger_sha256 == canonical_sha256(ledger)
        self.checkpoints.append((ledger, transition))


class _Transport:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.calls = 0

    def create_job(self, request, *, idempotency_key, request_sha256, scenario_id):
        self.calls += 1
        assert len(self.store.checkpoints) == 1, "dispatch reservation must be durable before I/O"
        assert request.provider_turn_cap == request.provider_request_cap == 0
        return PhysicalStabilityJobCreateObservationV1(
            scenario_id=scenario_id,
            observed_job_id=f"job-{scenario_id}",
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
        )


def _complete_observation(bundle, *, job_id: str) -> PhysicalStabilityTerminalObservationV1:
    job = bundle.jobs[0]
    case = job.request_payload["scenario_suite"]["cases"][0]
    trials = tuple(
        PhysicalStabilityTrialObservationV1(
            planned_trial_id=item.planned_trial_id,
            trial_ordinal=item.trial_ordinal,
            observed_trial_id=f"observed-{item.trial_ordinal:03d}",
            seed=item.seed,
            scenario_type=case["scenario_type"],
            status="completed",
            candidate_id="p5-fixed-baseline",
            candidate_is_baseline=True,
            input_contract_sha256=item.input_contract_sha256,
            scenario_effect_request_sha256=item.scenario_effect_request_sha256,
            effect_readback_receipt_sha256="5" * 64,
            parameter_readback_receipt_sha256="6" * 64,
            telemetry_sha256="7" * 64,
            metric_evidence_sha256="8" * 64,
            artifact_inventory_sha256="9" * 64,
            artifact_content_sha256=("0" * 64,),
            effect_ids_read_back=item.expected_effect_ids,
        )
        for item in job.trials
    )
    return PhysicalStabilityTerminalObservationV1(
        repository_subject_commit=bundle.repository_subject_commit,
        execution_bundle_sha256=canonical_sha256(bundle),
        scenario_ordinal=1,
        scenario_id=job.scenario_id,
        observed_job_id=job_id,
        request_sha256=job.request_sha256,
        job_status="completed",
        trials=trials,
    )


def test_compiles_six_complete_source_bound_zero_provider_job_requests() -> None:
    manifest, plan, bundle, _ledger = _contracts()

    assert bundle.execution_authorized is False
    assert bundle.repository_subject_commit == _SOURCE
    assert bundle.manifest_sha256 == canonical_sha256(manifest)
    assert bundle.plan_sha256 == canonical_sha256(plan)
    assert len(bundle.jobs) == 6
    assert sum(len(job.trials) for job in bundle.jobs) == 60
    assert len({job.idempotency_key for job in bundle.jobs}) == 6
    for job, scenario in zip(bundle.jobs, manifest.scenarios, strict=True):
        request = job.request_payload
        assert request["display_name"].endswith(scenario.scenario_id)
        assert request["simulator_backend"] == "real_cli"
        assert request["optimizer_strategy"] == "none"
        assert request["provider_turn_cap"] == request["provider_request_cap"] == 0
        assert request["provider_max_retries"] == 0
        assert request["openai"] is request["llm"] is None
        assert request["max_total_trials"] == 10
        assert request["scenario_suite"]["cases"][0]["seeds"] == list(scenario.seeds)
        assert canonical_sha256(request) == job.request_sha256
        _validate_real_cli_scenario_effect_contract(
            schemas.JobCreateRequest.model_validate(request)
        )


def test_bundle_is_reproducible_and_rejects_plan_or_payload_tamper() -> None:
    manifest, plan, bundle, _ledger = _contracts()
    assert canonical_sha256(bundle) == canonical_sha256(
        build_physical_stability_execution_bundle(manifest, plan)
    )

    plan_payload = plan.model_dump(mode="python")
    plan_payload["manifest_sha256"] = "0" * 64
    tampered_plan = type(plan).model_validate(plan_payload)
    with pytest.raises(ValueError, match="manifest"):
        build_physical_stability_execution_bundle(manifest, tampered_plan)

    bundle_payload = bundle.model_dump(mode="python")
    jobs = list(bundle_payload["jobs"])
    jobs[0] = deepcopy(jobs[0])
    jobs[0]["request_payload"]["provider_turn_cap"] = 1
    bundle_payload["jobs"] = tuple(jobs)
    with pytest.raises(ValidationError, match="hash|zero-provider"):
        PhysicalStabilityExecutionBundleV1.model_validate(bundle_payload)

    manifest_payload = manifest.model_dump(mode="python")
    scenarios = list(manifest_payload["scenarios"])
    scenarios[0] = deepcopy(scenarios[0])
    scenarios[0]["source_problem_sha256"] = "f" * 64
    manifest_payload["scenarios"] = tuple(scenarios)
    source_drifted = type(manifest).model_validate(manifest_payload)
    plan_payload = plan.model_dump(mode="python")
    plan_payload["manifest_sha256"] = canonical_sha256(source_drifted)
    source_drifted_plan = type(plan).model_validate(plan_payload)
    with pytest.raises(ValueError, match="source problem content"):
        build_physical_stability_execution_bundle(source_drifted, source_drifted_plan)


def test_dispatch_persists_reservation_before_single_fake_transport_call() -> None:
    _manifest, _plan, bundle, ledger = _contracts()
    store = _Store()
    transport = _Transport(store)

    running, transitions = dispatch_next_physical_stability_job(
        bundle,
        ledger,
        transport=transport,
        checkpoint_store=store,
        attempted_at_utc=_NOW,
        observed_at_utc=_NOW + timedelta(seconds=1),
    )

    assert transport.calls == 1
    assert [item.action for item in transitions] == ["dispatch_attempted", "job_observed"]
    assert len(store.checkpoints) == 2
    assert running.attempted_trial_count == 10
    assert running.scenarios[0].status == "running"
    assert running.scenarios[0].observed_job_id == "job-hover-mild-crosswind"


def test_checkpoint_failure_prevents_any_transport_io() -> None:
    _manifest, _plan, bundle, ledger = _contracts()
    store = _Store(fail_first=True)
    transport = _Transport(store)

    with pytest.raises(RuntimeError, match="checkpoint"):
        dispatch_next_physical_stability_job(
            bundle,
            ledger,
            transport=transport,
            checkpoint_store=store,
            attempted_at_utc=_NOW,
            observed_at_utc=_NOW + timedelta(seconds=1),
        )
    assert transport.calls == 0


def test_unobserved_dispatch_requires_manual_reconciliation_and_cannot_retry() -> None:
    _manifest, _plan, bundle, ledger = _contracts()
    store = _Store()
    transport = _Transport(store)
    transport.create_job = lambda *args, **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError("fixture transport interruption")
    )

    with pytest.raises(RuntimeError, match="interruption"):
        dispatch_next_physical_stability_job(
            bundle,
            ledger,
            transport=transport,
            checkpoint_store=store,
            attempted_at_utc=_NOW,
            observed_at_utc=_NOW + timedelta(seconds=1),
        )
    attempted_ledger = store.checkpoints[0][0]
    with pytest.raises(RuntimeError, match="manual read-only reconciliation"):
        require_manual_reconciliation_after_unobserved_dispatch(attempted_ledger)
    with pytest.raises(ValueError, match="only one active|preregistered order"):
        dispatch_next_physical_stability_job(
            bundle,
            attempted_ledger,
            transport=_Transport(_Store()),
            checkpoint_store=_Store(),
            attempted_at_utc=_NOW + timedelta(seconds=2),
            observed_at_utc=_NOW + timedelta(seconds=3),
        )


def test_closes_only_from_complete_content_addressed_terminal_evidence() -> None:
    _manifest, _plan, bundle, ledger = _contracts()
    dispatch_store = _Store()
    running, _ = dispatch_next_physical_stability_job(
        bundle,
        ledger,
        transport=_Transport(dispatch_store),
        checkpoint_store=dispatch_store,
        attempted_at_utc=_NOW,
        observed_at_utc=_NOW + timedelta(seconds=1),
    )
    job_id = running.scenarios[0].observed_job_id
    assert job_id is not None
    observation = _complete_observation(bundle, job_id=job_id)
    terminal_store = _Store()

    closed, transition = close_physical_stability_job(
        bundle,
        running,
        observation,
        checkpoint_store=terminal_store,
        terminal_at_utc=_NOW + timedelta(seconds=2),
    )

    assert transition.action == "terminal_observed"
    assert closed.scenarios[0].status == "completed"
    assert closed.scenarios[0].completed_trial_count == 10
    assert closed.terminal_trial_count == 10
    assert closed.next_scenario_ordinal == 2
    assert len(terminal_store.checkpoints) == 1


def test_terminal_evidence_rejects_missing_artifact_hash_and_effect_drift() -> None:
    _manifest, _plan, bundle, ledger = _contracts()
    store = _Store()
    running, _ = dispatch_next_physical_stability_job(
        bundle,
        ledger,
        transport=_Transport(store),
        checkpoint_store=store,
        attempted_at_utc=_NOW,
        observed_at_utc=_NOW + timedelta(seconds=1),
    )
    job_id = running.scenarios[0].observed_job_id
    assert job_id is not None
    observation = _complete_observation(bundle, job_id=job_id)
    payload = observation.model_dump(mode="python")
    trials = list(payload["trials"])
    trials[0] = deepcopy(trials[0])
    trials[0]["artifact_content_sha256"] = ()
    payload["trials"] = tuple(trials)
    with pytest.raises(ValidationError, match="content-addressed evidence"):
        PhysicalStabilityTerminalObservationV1.model_validate(payload)

    payload = observation.model_dump(mode="python")
    trials = list(payload["trials"])
    trials[0] = deepcopy(trials[0])
    trials[0]["scenario_effect_request_sha256"] = "f" * 64
    payload["trials"] = tuple(trials)
    drifted = PhysicalStabilityTerminalObservationV1.model_validate(payload)
    with pytest.raises(ValueError, match="effect request"):
        close_physical_stability_job(
            bundle,
            running,
            drifted,
            checkpoint_store=_Store(),
            terminal_at_utc=_NOW + timedelta(seconds=2),
        )

    for field, value, message in (
        ("input_contract_sha256", "e" * 64, "input contract"),
        ("scenario_type", "turbulence", "scenario type"),
        ("candidate_id", "other-baseline", "fixed baseline"),
    ):
        payload = observation.model_dump(mode="python")
        trials = list(payload["trials"])
        trials[0] = deepcopy(trials[0])
        trials[0][field] = value
        payload["trials"] = tuple(trials)
        drifted = PhysicalStabilityTerminalObservationV1.model_validate(payload)
        with pytest.raises(ValueError, match=message):
            close_physical_stability_job(
                bundle,
                running,
                drifted,
                checkpoint_store=_Store(),
                terminal_at_utc=_NOW + timedelta(seconds=2),
            )
