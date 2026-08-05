from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.benchmarking.contracts import CompositeExecutionInventoryV1, canonical_sha256
from app.benchmarking.physical_stability import (
    build_physical_stability_manifest,
    compile_physical_stability_trial_plan,
)
from app.benchmarking.physical_stability_assessment import PhysicalStabilityMetricsV1
from app.benchmarking.physical_stability_bridge import (
    PhysicalStabilityJobCreateObservationV1,
    build_physical_stability_execution_bundle,
)
from app.benchmarking.physical_stability_checkpoint import (
    AtomicPhysicalStabilityCheckpointStore,
)
from app.benchmarking.physical_stability_execution import (
    PhysicalStabilityExecutionAuthorizationV1,
    build_physical_stability_execution_ledger,
)
from app.benchmarking.physical_stability_job_evidence import (
    PhysicalStabilityAcceptedTrialSnapshotV1,
    PhysicalStabilityJobEvidenceSnapshotV1,
)
from app.benchmarking.physical_stability_runner import (
    advance_physical_stability_campaign,
)

_SOURCE = "a" * 40
_SHA = "b" * 64
_NOW = datetime(2026, 8, 5, 4, 0, tzinfo=UTC)


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
        authorization_id="p5-red-window-runner-unit",
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
    return bundle, authorization, ledger


def _snapshot(bundle, ordinal: int, job_id: str) -> PhysicalStabilityJobEvidenceSnapshotV1:
    job = bundle.jobs[ordinal - 1]
    scenario_type = job.request_payload["scenario_suite"]["cases"][0]["scenario_type"]
    baseline_id = f"cand-server-baseline-{ordinal:02d}"
    return PhysicalStabilityJobEvidenceSnapshotV1(
        observed_job_id=job_id,
        observed_baseline_candidate_id=baseline_id,
        job_status="completed",
        trials=tuple(
            PhysicalStabilityAcceptedTrialSnapshotV1(
                observed_trial_id=f"tri-server-{ordinal:02d}-{index:02d}",
                seed=binding.seed,
                scenario_type=scenario_type,
                terminal_status="completed",
                candidate_id=baseline_id,
                accepted_attempt_id=f"attempt-server-{ordinal:02d}-{index:02d}",
                accepted_attempt_count=1,
                claim_evidence_id="sha256:" + "1" * 64,
                outcome_evidence_id="sha256:" + "2" * 64,
                scenario_effect_request_sha256=binding.scenario_effect_request_sha256,
                effect_readback_receipt_sha256="3" * 64,
                parameter_readback_receipt_sha256="4" * 64,
                telemetry_sha256="5" * 64,
                metric_evidence_sha256="6" * 64,
                artifact_inventory_sha256="7" * 64,
                artifact_content_sha256=("8" * 64,),
                effect_ids_read_back=binding.expected_effect_ids,
                metrics=PhysicalStabilityMetricsV1(
                    rmse=0.4,
                    max_error=0.8,
                    completion_time_seconds=12.0,
                    pass_flag=True,
                    crash_flag=False,
                    timeout_flag=False,
                    instability_flag=False,
                ),
            )
            for index, binding in enumerate(job.trials, start=1)
        ),
    )


class _Clock:
    def __init__(self, current: datetime) -> None:
        self.current = current
        self.calls: list[datetime] = []

    def __call__(self) -> datetime:
        value = self.current
        self.calls.append(value)
        self.current += timedelta(seconds=1)
        return value


class _Transport:
    def __init__(self, bundle, *, fail_create: bool = False, evidence_ready: bool = True):
        self.bundle = bundle
        self.fail_create = fail_create
        self.evidence_ready = evidence_ready
        self.create_calls = 0
        self.evidence_calls = 0
        self.job_ordinals: dict[str, int] = {}

    def create_job(self, request, *, idempotency_key, request_sha256, scenario_id):
        self.create_calls += 1
        if self.fail_create:
            raise RuntimeError("fixture indeterminate create")
        ordinal = next(
            item.scenario_ordinal for item in self.bundle.jobs if item.scenario_id == scenario_id
        )
        job_id = f"job-server-{ordinal:02d}"
        self.job_ordinals[job_id] = ordinal
        return PhysicalStabilityJobCreateObservationV1(
            scenario_id=scenario_id,
            observed_job_id=job_id,
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
        )

    def get_physical_stability_evidence(self, observed_job_id):
        self.evidence_calls += 1
        if not self.evidence_ready:
            return None
        return _snapshot(self.bundle, self.job_ordinals[observed_job_id], observed_job_id)


def _store(tmp_path, ledger):
    return AtomicPhysicalStabilityCheckpointStore(
        tmp_path / "p5-runner-unit",
        allowed_evidence_root=tmp_path,
        initial_ledger_sha256=canonical_sha256(ledger),
        authorization_id=ledger.authorization_id,
    )


def test_advances_full_campaign_one_external_action_at_a_time(tmp_path) -> None:
    bundle, authorization, ledger = _contracts()
    store = _store(tmp_path, ledger)
    transport = _Transport(bundle)
    clock = _Clock(_NOW)

    actions = []
    for _ordinal in range(1, 7):
        actions.append(
            advance_physical_stability_campaign(
                bundle,
                ledger,
                authorization,
                transport=transport,
                checkpoint_store=store,
                clock=clock,
            )
        )
        actions.append(
            advance_physical_stability_campaign(
                bundle,
                ledger,
                authorization,
                transport=transport,
                checkpoint_store=store,
                clock=clock,
            )
        )

    assert [item.action for item in actions[::2]] == ["job_dispatched"] * 6
    assert [item.action for item in actions[1:-1:2]] == ["job_closed"] * 5
    assert actions[-1].action == "campaign_closed"
    assert actions[-1].checkpoint_count == 18
    assert transport.create_calls == transport.evidence_calls == 6
    chain = store.load_chain()
    assert chain[-1].ledger.status == "closed"
    assert chain[0].ledger.scenarios[0].dispatch_attempted_at_utc == _NOW
    assert chain[1].ledger.scenarios[0].job_observed_at_utc == _NOW + timedelta(seconds=1)

    repeated = advance_physical_stability_campaign(
        bundle,
        ledger,
        authorization,
        transport=transport,
        checkpoint_store=store,
        clock=clock,
    )
    assert repeated.action == "campaign_closed"
    assert transport.create_calls == transport.evidence_calls == 6


def test_waiting_read_is_repeatable_and_does_not_write_a_checkpoint(tmp_path) -> None:
    bundle, authorization, ledger = _contracts()
    store = _store(tmp_path, ledger)
    transport = _Transport(bundle, evidence_ready=False)
    clock = _Clock(_NOW)

    dispatched = advance_physical_stability_campaign(
        bundle,
        ledger,
        authorization,
        transport=transport,
        checkpoint_store=store,
        clock=clock,
    )
    waiting = advance_physical_stability_campaign(
        bundle,
        ledger,
        authorization,
        transport=transport,
        checkpoint_store=store,
        clock=clock,
    )
    repeated = advance_physical_stability_campaign(
        bundle,
        ledger,
        authorization,
        transport=transport,
        checkpoint_store=store,
        clock=clock,
    )

    assert dispatched.checkpoint_count == waiting.checkpoint_count == repeated.checkpoint_count == 2
    assert waiting.action == repeated.action == "awaiting_terminal_evidence"
    assert transport.create_calls == 1
    assert transport.evidence_calls == 2


def test_indeterminate_create_is_never_automatically_replayed(tmp_path) -> None:
    bundle, authorization, ledger = _contracts()
    store = _store(tmp_path, ledger)
    transport = _Transport(bundle, fail_create=True)
    clock = _Clock(_NOW)

    with pytest.raises(RuntimeError, match="fixture indeterminate create"):
        advance_physical_stability_campaign(
            bundle,
            ledger,
            authorization,
            transport=transport,
            checkpoint_store=store,
            clock=clock,
        )
    assert len(store.load_chain()) == 1
    assert transport.create_calls == 1

    transport.fail_create = False
    with pytest.raises(RuntimeError, match="manual read-only reconciliation"):
        advance_physical_stability_campaign(
            bundle,
            ledger,
            authorization,
            transport=transport,
            checkpoint_store=store,
            clock=clock,
        )
    assert transport.create_calls == 1


def test_expired_authorization_blocks_new_dispatch_but_not_terminal_read(tmp_path) -> None:
    bundle, authorization, ledger = _contracts()
    store = _store(tmp_path, ledger)
    transport = _Transport(bundle)
    valid_clock = _Clock(_NOW)
    advance_physical_stability_campaign(
        bundle,
        ledger,
        authorization,
        transport=transport,
        checkpoint_store=store,
        clock=valid_clock,
    )

    expired_clock = _Clock(authorization.expires_at_utc + timedelta(seconds=1))
    closed = advance_physical_stability_campaign(
        bundle,
        ledger,
        authorization,
        transport=transport,
        checkpoint_store=store,
        clock=expired_clock,
    )
    assert closed.action == "job_closed"

    with pytest.raises(ValueError, match="expired before a new dispatch"):
        advance_physical_stability_campaign(
            bundle,
            ledger,
            authorization,
            transport=transport,
            checkpoint_store=store,
            clock=expired_clock,
        )
    assert transport.create_calls == 1


def test_rejects_authorization_or_recovered_source_drift(tmp_path) -> None:
    bundle, authorization, ledger = _contracts()
    store = _store(tmp_path, ledger)
    transport = _Transport(bundle)
    clock = _Clock(_NOW)
    drifted = authorization.model_copy(update={"repository_subject_commit": "f" * 40})

    with pytest.raises(ValueError, match="authorization differs"):
        advance_physical_stability_campaign(
            bundle,
            ledger,
            drifted,
            transport=transport,
            checkpoint_store=store,
            clock=clock,
        )
    assert transport.create_calls == 0
    assert store.load_chain() == ()
