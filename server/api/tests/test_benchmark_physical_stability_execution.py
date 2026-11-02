from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.benchmarking.composite_inventory import (
    COMPOSITE_EXECUTION_VERIFICATION_CONTRACT_SHA256,
    CompositeExecutionVerificationReceiptV1,
)
from app.benchmarking.contracts import (
    CompositeExecutionInventoryV1,
    canonical_sha256,
)
from app.benchmarking.physical_stability import (
    build_physical_stability_manifest,
    compile_physical_stability_trial_plan,
)
from app.benchmarking.physical_stability_execution import (
    PhysicalStabilityExecutionAuthorizationV1,
    build_physical_stability_execution_ledger,
    record_physical_stability_dispatch_attempt,
    record_physical_stability_job_observed,
    record_physical_stability_terminal_observation,
)

_SOURCE = "a" * 40
_SHA = "b" * 64
_NOW = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)


def _component(component_id: str, *, source: str | None = _SOURCE) -> dict[str, object]:
    return {
        "component_id": component_id,
        "version": "unit-v1",
        "source_commit": source,
        "artifact_sha256": _SHA,
        "manifest_sha256": _SHA,
    }


def _inventory(*, engine_source: str = _SOURCE) -> CompositeExecutionInventoryV1:
    return CompositeExecutionInventoryV1.model_validate(
        {
            "repository_subject_commit": _SOURCE,
            "evaluator_subject_commit": _SOURCE,
            "campaign_coordinator_subject_commit": _SOURCE,
            "evidence_head_commit": None,
            "desktop": _component("desktop"),
            "runtime_base": _component("runtime-base", source="c" * 40),
            "engine_pack": _component("engine-pack", source=engine_source),
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


def _contracts(*, engine_source: str = _SOURCE):
    manifest = build_physical_stability_manifest(
        repository_subject_commit=_SOURCE,
        composite_execution_inventory=_inventory(engine_source=engine_source),
    )
    plan = compile_physical_stability_trial_plan(manifest)
    return manifest, plan


def _verification_receipt(
    inventory: CompositeExecutionInventoryV1, **changes
) -> CompositeExecutionVerificationReceiptV1:
    payload = {
        "status": "verified",
        "compatible": True,
        "inventory_sha256": canonical_sha256(inventory),
        "observation_sha256": "5" * 64,
        "compatibility_summary_sha256": "6" * 64,
        "verification_contract_sha256": (
            COMPOSITE_EXECUTION_VERIFICATION_CONTRACT_SHA256
        ),
        "verified_component_ids": (
            "desktop",
            "runtime-base",
            "engine-pack",
            "px4",
            "gazebo",
        ),
        "reason_codes": (),
    }
    payload.update(changes)
    return CompositeExecutionVerificationReceiptV1.model_validate(payload)


def _authorization(manifest, plan, **changes) -> PhysicalStabilityExecutionAuthorizationV1:
    verification = _verification_receipt(manifest.composite_execution_inventory)
    payload = {
        "authorization_id": "p5-red-window-unit",
        "authorization_nonce": "1" * 32,
        "opaque_actor_sha256": "2" * 64,
        "user_confirmation_receipt_sha256": "3" * 64,
        "repository_subject_commit": _SOURCE,
        "manifest_sha256": canonical_sha256(manifest),
        "plan_sha256": canonical_sha256(plan),
        "composite_execution_inventory_sha256": canonical_sha256(
            manifest.composite_execution_inventory
        ),
        "composite_execution_verification": verification,
        "composite_execution_verification_receipt_sha256": canonical_sha256(
            verification
        ),
        "runtime_base_manifest_sha256": (
            manifest.composite_execution_inventory.runtime_base.manifest_sha256
        ),
        "engine_pack_id": "sha256:" + "4" * 64,
        "engine_pack_manifest_sha256": (
            manifest.composite_execution_inventory.engine_pack.manifest_sha256
        ),
        "issued_at_utc": _NOW - timedelta(minutes=1),
        "expires_at_utc": _NOW + timedelta(hours=6),
    }
    payload.update(changes)
    return PhysicalStabilityExecutionAuthorizationV1.model_validate(payload)


def _ledger():
    manifest, plan = _contracts()
    authorization = _authorization(manifest, plan)
    return build_physical_stability_execution_ledger(
        manifest,
        plan,
        authorization,
        now_utc=_NOW,
    )


def test_builds_zero_work_ledger_only_from_exact_short_lived_red_authorization() -> None:
    ledger = _ledger()
    assert ledger.status == "ready"
    assert ledger.attempted_scenario_count == 0
    assert ledger.attempted_trial_count == 0
    assert ledger.terminal_trial_count == 0
    assert ledger.next_scenario_ordinal == 1
    assert [item.scenario_id for item in ledger.scenarios] == [
        "hover-mild-crosswind",
        "circle-mild-crosswind",
        "u-turn-steady-wind",
        "figure-eight-light-gust",
        "circle-sensor-degradation",
        "composite-stress",
    ]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"manifest_sha256": "0" * 64}, "manifest"),
        ({"plan_sha256": "0" * 64}, "trial plan"),
        ({"composite_execution_inventory_sha256": "0" * 64}, "authorized inventory"),
        ({"runtime_base_manifest_sha256": "0" * 64}, "Runtime Base"),
        ({"engine_pack_manifest_sha256": "0" * 64}, "Engine Pack"),
    ],
)
def test_rejects_tampered_source_bound_authorization(change, message) -> None:
    manifest, plan = _contracts()
    with pytest.raises(ValueError, match=message):
        authorization = _authorization(manifest, plan, **change)
        build_physical_stability_execution_ledger(
            manifest, plan, authorization, now_utc=_NOW
        )


def test_rejects_tampered_denied_and_incomplete_composite_verification() -> None:
    manifest, plan = _contracts()
    with pytest.raises(ValueError, match="receipt hash"):
        _authorization(
            manifest,
            plan,
            composite_execution_verification_receipt_sha256="0" * 64,
        )

    denied = _verification_receipt(
        manifest.composite_execution_inventory,
        status="denied",
        compatible=False,
        verified_component_ids=(),
        reason_codes=("fixture-denial",),
    )
    with pytest.raises(ValueError, match="verified compatible"):
        _authorization(
            manifest,
            plan,
            composite_execution_verification=denied,
            composite_execution_verification_receipt_sha256=canonical_sha256(denied),
        )

    incomplete = _verification_receipt(
        manifest.composite_execution_inventory,
        verified_component_ids=("runtime-base", "engine-pack", "px4", "gazebo"),
    )
    authorization = _authorization(
        manifest,
        plan,
        composite_execution_verification=incomplete,
        composite_execution_verification_receipt_sha256=canonical_sha256(incomplete),
    )
    with pytest.raises(ValueError, match="exact inventory components"):
        build_physical_stability_execution_ledger(
            manifest, plan, authorization, now_utc=_NOW
        )


def test_rejects_expired_future_and_overlong_authorization_windows() -> None:
    manifest, plan = _contracts()
    expired = _authorization(
        manifest,
        plan,
        issued_at_utc=_NOW - timedelta(hours=2),
        expires_at_utc=_NOW - timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="expired"):
        build_physical_stability_execution_ledger(manifest, plan, expired, now_utc=_NOW)

    future = _authorization(
        manifest,
        plan,
        issued_at_utc=_NOW + timedelta(minutes=6),
        expires_at_utc=_NOW + timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="not yet valid"):
        build_physical_stability_execution_ledger(manifest, plan, future, now_utc=_NOW)

    with pytest.raises(ValueError, match="eight hours"):
        _authorization(
            manifest,
            plan,
            issued_at_utc=_NOW,
            expires_at_utc=_NOW + timedelta(hours=8, seconds=1),
        )


def test_rejects_engine_pack_that_is_not_built_from_exact_subject() -> None:
    manifest, plan = _contracts(engine_source="f" * 40)
    authorization = _authorization(manifest, plan)
    with pytest.raises(ValueError, match="exact subject"):
        build_physical_stability_execution_ledger(
            manifest, plan, authorization, now_utc=_NOW
        )


def test_persists_dispatch_attempt_before_job_and_counts_all_reserved_trials() -> None:
    initial = _ledger()
    attempted, first_transition = record_physical_stability_dispatch_attempt(
        initial,
        scenario_ordinal=1,
        attempted_at_utc=_NOW,
    )
    assert attempted.status == "active"
    assert attempted.attempted_scenario_count == 1
    assert attempted.attempted_trial_count == 10
    assert attempted.terminal_trial_count == 0
    assert attempted.next_scenario_ordinal == 2
    assert first_transition.action == "dispatch_attempted"
    assert first_transition.before_ledger_sha256 == canonical_sha256(initial)
    assert first_transition.after_ledger_sha256 == canonical_sha256(attempted)

    running, second_transition = record_physical_stability_job_observed(
        attempted,
        scenario_ordinal=1,
        observed_job_id="job_p5_unit",
        observed_at_utc=_NOW + timedelta(seconds=1),
    )
    assert running.scenarios[0].status == "running"
    assert running.scenarios[0].observed_job_id == "job_p5_unit"
    assert second_transition.action == "job_observed"
    with pytest.raises(ValueError, match="only one active"):
        record_physical_stability_dispatch_attempt(
            running,
            scenario_ordinal=2,
            attempted_at_utc=_NOW + timedelta(seconds=2),
        )


def test_terminal_failure_retains_all_ten_trials_and_cannot_be_retried() -> None:
    ledger, _ = record_physical_stability_dispatch_attempt(
        _ledger(), scenario_ordinal=1, attempted_at_utc=_NOW
    )
    closed, transition = record_physical_stability_terminal_observation(
        ledger,
        scenario_ordinal=1,
        terminal_status="indeterminate",
        completed_trial_count=0,
        failed_trial_count=0,
        timeout_trial_count=0,
        cancelled_trial_count=0,
        indeterminate_trial_count=10,
        observation_receipt_sha256="5" * 64,
        terminal_at_utc=_NOW + timedelta(seconds=1),
        failure_code="JOB_CREATE_RESPONSE_INDETERMINATE",
    )
    assert closed.attempted_trial_count == 10
    assert closed.terminal_trial_count == 10
    assert closed.scenarios[0].indeterminate_trial_count == 10
    assert transition.action == "terminal_observed"
    with pytest.raises(ValueError, match="preregistered order|cannot be retried"):
        record_physical_stability_dispatch_attempt(
            closed, scenario_ordinal=1, attempted_at_utc=_NOW + timedelta(seconds=2)
        )
    with pytest.raises(ValueError, match="overwrite"):
        record_physical_stability_terminal_observation(
            closed,
            scenario_ordinal=1,
            terminal_status="failed",
            completed_trial_count=0,
            failed_trial_count=10,
            timeout_trial_count=0,
            cancelled_trial_count=0,
            indeterminate_trial_count=0,
            observation_receipt_sha256="6" * 64,
            terminal_at_utc=_NOW + timedelta(seconds=3),
            failure_code="RETRY_FORBIDDEN",
        )


def test_rejects_incomplete_terminal_accounting_and_skipped_dispatch_order() -> None:
    ledger = _ledger()
    with pytest.raises(ValueError, match="preregistered order"):
        record_physical_stability_dispatch_attempt(
            ledger, scenario_ordinal=2, attempted_at_utc=_NOW
        )
    attempted, _ = record_physical_stability_dispatch_attempt(
        ledger, scenario_ordinal=1, attempted_at_utc=_NOW
    )
    with pytest.raises(ValueError, match="all ten"):
        record_physical_stability_terminal_observation(
            attempted,
            scenario_ordinal=1,
            terminal_status="failed",
            completed_trial_count=0,
            failed_trial_count=9,
            timeout_trial_count=0,
            cancelled_trial_count=0,
            indeterminate_trial_count=0,
            observation_receipt_sha256="7" * 64,
            terminal_at_utc=_NOW + timedelta(seconds=1),
            failure_code="ONE_TRIAL_DROPPED",
        )


def test_rejects_non_monotonic_timestamps_and_completed_trials_without_job() -> None:
    attempted, _ = record_physical_stability_dispatch_attempt(
        _ledger(), scenario_ordinal=1, attempted_at_utc=_NOW
    )
    with pytest.raises(ValueError, match="cannot precede"):
        record_physical_stability_job_observed(
            attempted,
            scenario_ordinal=1,
            observed_job_id="job_p5_unit",
            observed_at_utc=_NOW - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="observed Job"):
        record_physical_stability_terminal_observation(
            attempted,
            scenario_ordinal=1,
            terminal_status="completed",
            completed_trial_count=10,
            failed_trial_count=0,
            timeout_trial_count=0,
            cancelled_trial_count=0,
            indeterminate_trial_count=0,
            observation_receipt_sha256="8" * 64,
            terminal_at_utc=_NOW + timedelta(seconds=1),
        )
