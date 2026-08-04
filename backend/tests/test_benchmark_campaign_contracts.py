from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.benchmarking.contracts import (
    BENCHMARK_OBSERVATION_CONTRACT_SHA256,
    BenchmarkCampaignManifestV1,
    BenchmarkObservationV1,
    BenchmarkProposalV1,
    canonical_sha256,
)

from .test_jobs_api import HEURISTIC_JOB_PAYLOAD

_SHA = "1" * 64
_COMMIT = "a" * 40


def _component(component_id: str) -> dict[str, object]:
    return {
        "component_id": component_id,
        "version": "test-v1",
        "source_commit": _COMMIT,
        "artifact_sha256": _SHA,
        "manifest_sha256": "2" * 64,
    }


def _manifest() -> dict[str, object]:
    return {
        "schema_id": "dronedream.benchmark-campaign/v1",
        "campaign_key": "panel-a-pilot",
        "campaign_version": "v1",
        "name": "Panel A pilot preregistration",
        "panel": "A",
        "protocol_sha256": (
            "734bb6b42ec25ffc92bd9f15bb6fa27bc3482b4ce0841ce9aa3b080eafb8caee"
        ),
        "generated_at": "2026-08-04T10:00:00Z",
        "composite_execution_inventory": {
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
        },
        "fairness": {
            "schema_id": "dronedream.benchmark-fairness/v1",
            "observation_contract_sha256": BENCHMARK_OBSERVATION_CONTRACT_SHA256,
            "evaluator_contract_id": "dronedream.candidate-evaluator/v1",
            "parameter_domain_sha256": "9" * 64,
            "objective_contract_sha256": "a" * 64,
            "constraint_contract_sha256": "b" * 64,
            "history_contract_sha256": "c" * 64,
            "failure_semantics_sha256": "d" * 64,
            "simulator_budget_sha256": "e" * 64,
            "qualification_rule_sha256": "f" * 64,
            "scenario_manifest_sha256": "0" * 64,
            "seed_block_manifest_sha256": "1" * 64,
        },
        "budget_caps": {
            "schema_id": "dronedream.benchmark-budget-caps/v1",
            "jobs": 96,
            "trials": 5760,
            "logical_turns": 4096,
            "network_requests": 4096,
            "input_utf8_bytes": 100_000_000,
            "output_utf8_bytes": 20_000_000,
            "provider_tokens": 10_000_000,
            "provider_cost_microusd": 250_000_000,
            "wall_time_seconds": 604800,
            "disk_bytes": 1_000_000_000_000,
        },
        "arms": [
            {
                "schema_id": "dronedream.benchmark-arm/v1",
                "benchmark_arm_id": "random-search",
                "arm_version": "v1",
                "arm_family": "traditional",
                "proposal_adapter_id": "random_search/v1",
                "evaluator_contract_id": "dronedream.candidate-evaluator/v1",
                "intervention": {"algorithm_seed_policy": "paired-block-v1"},
                "provider_contract_sha256": None,
                "dependencies": [],
                "execution_enabled": False,
            },
            {
                "schema_id": "dronedream.benchmark-arm/v1",
                "benchmark_arm_id": "dronedream-adaptive",
                "arm_version": "v1",
                "arm_family": "llm_harness",
                "proposal_adapter_id": "dronedream_adaptive_1_4/v1",
                "evaluator_contract_id": "dronedream.candidate-evaluator/v1",
                "intervention": {"turn_policy": "adaptive-1-4-v1"},
                "provider_contract_sha256": "2" * 64,
                "dependencies": [],
                "execution_enabled": False,
            },
        ],
    }


def test_unified_observation_excludes_holdout_and_sensitive_payloads() -> None:
    schema = BenchmarkObservationV1.model_json_schema()
    assert "holdout" not in " ".join(schema["properties"]).lower()

    with pytest.raises(ValueError, match="sensitive field"):
        BenchmarkProposalV1(
            candidate_ref="candidate-1",
            parameters={"MPC_XY_P": 0.95},
            reason_code="bounded-proposal",
            proposal_receipt={"api_key": "forbidden"},
        )
def test_create_campaign_freezes_manifest_and_registered_arms(client: TestClient) -> None:
    manifest = _manifest()
    response = client.post(
        "/api/v1/benchmark-campaigns",
        json={"manifest": manifest},
        headers={"Idempotency-Key": "00000000-0000-4000-8000-000000000001"},
    )

    assert response.status_code == 200, response.text
    record = response.json()["data"]
    parsed = BenchmarkCampaignManifestV1.model_validate_json(json.dumps(manifest))
    assert record["manifest_sha256"] == canonical_sha256(parsed)
    assert record["status"] == "PREREGISTERED"
    assert record["budget_caps"]["trials"] == 5760
    assert [arm["benchmark_arm_id"] for arm in record["arms"]] == [
        "dronedream-adaptive",
        "random-search",
    ]
    assert all(not arm["execution_enabled"] for arm in record["arms"])

    detail = client.get(f"/api/v1/benchmark-campaigns/{record['id']}")
    assert detail.status_code == 200
    assert detail.json()["data"] == record

    from app.db import SessionLocal

    with SessionLocal() as db:
        with pytest.raises(DatabaseError, match="preregistration is immutable"):
            db.execute(
                text("UPDATE benchmark_campaigns SET name='mutated' WHERE id=:id"),
                {"id": record["id"]},
            )
            db.commit()
        db.rollback()
        db.execute(
            text("UPDATE benchmark_campaigns SET status='ACTIVE' WHERE id=:id"),
            {"id": record["id"]},
        )
        db.commit()

    active = client.get(f"/api/v1/benchmark-campaigns/{record['id']}")
    assert active.status_code == 200
    assert active.json()["data"]["status"] == "ACTIVE"


def test_identical_manifest_replays_but_same_version_cannot_be_overwritten(
    client: TestClient,
) -> None:
    payload = {"manifest": _manifest()}
    first = client.post("/api/v1/benchmark-campaigns", json=payload)
    assert first.status_code == 200, first.text
    repeated = client.post("/api/v1/benchmark-campaigns", json=payload)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["data"]["id"] == first.json()["data"]["id"]

    changed = deepcopy(payload)
    changed["manifest"]["name"] = "attempted overwrite"
    conflict = client.post("/api/v1/benchmark-campaigns", json=changed)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "BENCHMARK_CAMPAIGN_VERSION_CONFLICT"


def test_unregistered_or_unimplemented_arm_fails_closed(client: TestClient) -> None:
    unknown = _manifest()
    unknown["arms"][0]["proposal_adapter_id"] = "temporary_monkeypatch/v1"
    response = client.post("/api/v1/benchmark-campaigns", json={"manifest": unknown})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BENCHMARK_ADAPTER_NOT_REGISTERED"

    premature = _manifest()
    premature["campaign_version"] = "v2"
    premature["arms"][0]["proposal_adapter_id"] = "reference_scbo/v1"
    premature["arms"][0]["execution_enabled"] = True
    response = client.post("/api/v1/benchmark-campaigns", json={"manifest": premature})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BENCHMARK_ADAPTER_NOT_IMPLEMENTED"


def test_manifest_rejects_secret_shaped_fields_before_persistence(client: TestClient) -> None:
    manifest = _manifest()
    manifest["arms"][0]["intervention"] = {"password": "must-not-persist"}
    response = client.post("/api/v1/benchmark-campaigns", json={"manifest": manifest})
    assert response.status_code == 422

    listing = client.get("/api/v1/benchmark-campaigns")
    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 0


def test_campaign_coordinator_fences_and_idempotently_accounts_global_caps(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/benchmark-campaigns",
        json={"manifest": _manifest()},
    )
    assert created.status_code == 200, created.text
    campaign_id = created.json()["data"]["id"]

    claimed = client.post(
        f"/api/v1/benchmark-campaigns/{campaign_id}/coordinator/claim",
        json={"owner_id": "coordinator-a", "lease_seconds": 120},
    )
    assert claimed.status_code == 200, claimed.text
    lease = claimed.json()["data"]
    token = lease["lease_token"]
    generation = lease["lease_generation"]
    assert generation == 1

    competing = client.post(
        f"/api/v1/benchmark-campaigns/{campaign_id}/coordinator/claim",
        json={"owner_id": "coordinator-b", "lease_seconds": 120},
    )
    assert competing.status_code == 409
    assert competing.json()["error"]["code"] == "BENCHMARK_COORDINATOR_LEASE_HELD"

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        state = db.get(models.BenchmarkCampaignCoordinatorState, campaign_id)
        assert state is not None
        assert state.lease_token_hash != token
        assert state.lease_token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()
        db.execute(
            text("UPDATE benchmark_campaigns SET status='ACTIVE' WHERE id=:id"),
            {"id": campaign_id},
        )
        db.commit()

    reservation_payload = {
        "reservation_key": "run-001-dispatch",
        "lease_generation": generation,
        "reason": "run-dispatch",
        "usage": {
            "jobs": 2,
            "trials": 20,
            "logical_turns": 2,
            "network_requests": 2,
            "input_utf8_bytes": 4096,
            "output_utf8_bytes": 1024,
            "provider_tokens": 900,
            "provider_cost_microusd": 25000,
            "wall_time_seconds": 120,
            "disk_bytes": 2048,
        },
    }
    wrong_token = client.post(
        f"/api/v1/benchmark-campaigns/{campaign_id}/budget-reservations",
        json=reservation_payload,
        headers={"X-Benchmark-Lease-Token": "x" * 32},
    )
    assert wrong_token.status_code == 409
    assert wrong_token.json()["error"]["code"] == "BENCHMARK_COORDINATOR_FENCE_REJECTED"

    reserved = client.post(
        f"/api/v1/benchmark-campaigns/{campaign_id}/budget-reservations",
        json=reservation_payload,
        headers={"X-Benchmark-Lease-Token": token},
    )
    assert reserved.status_code == 200, reserved.text
    reservation = reserved.json()["data"]
    replay = client.post(
        f"/api/v1/benchmark-campaigns/{campaign_id}/budget-reservations",
        json=reservation_payload,
        headers={"X-Benchmark-Lease-Token": token},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["id"] == reservation["id"]

    conflict_payload = deepcopy(reservation_payload)
    conflict_payload["usage"]["trials"] = 21
    conflict = client.post(
        f"/api/v1/benchmark-campaigns/{campaign_id}/budget-reservations",
        json=conflict_payload,
        headers={"X-Benchmark-Lease-Token": token},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "BENCHMARK_RESERVATION_KEY_CONFLICT"

    exceeds = deepcopy(reservation_payload)
    exceeds["reservation_key"] = "run-002-dispatch"
    exceeds["usage"]["jobs"] = 95
    cap_failure = client.post(
        f"/api/v1/benchmark-campaigns/{campaign_id}/budget-reservations",
        json=exceeds,
        headers={"X-Benchmark-Lease-Token": token},
    )
    assert cap_failure.status_code == 409
    assert cap_failure.json()["error"]["code"] == "BENCHMARK_CAMPAIGN_CAP_EXCEEDED"

    usage = client.get(f"/api/v1/benchmark-campaigns/{campaign_id}/usage")
    assert usage.status_code == 200
    assert usage.json()["data"]["used"] == reservation_payload["usage"]
    assert usage.json()["data"]["remaining"]["jobs"] == 94

    with SessionLocal() as db:
        with pytest.raises(DatabaseError, match="reservations are append-only"):
            db.execute(
                text(
                    "UPDATE benchmark_budget_reservations SET trials=999 "
                    "WHERE id=:id"
                ),
                {"id": reservation["id"]},
            )
            db.commit()
        db.rollback()

    released = client.post(
        f"/api/v1/benchmark-campaigns/{campaign_id}/coordinator/release",
        json={"lease_generation": generation},
        headers={"X-Benchmark-Lease-Token": token},
    )
    assert released.status_code == 200, released.text
    assert released.json()["data"]["lease_owner"] is None

    stale = deepcopy(reservation_payload)
    stale["reservation_key"] = "stale-generation"
    stale_response = client.post(
        f"/api/v1/benchmark-campaigns/{campaign_id}/budget-reservations",
        json=stale,
        headers={"X-Benchmark-Lease-Token": token},
    )
    assert stale_response.status_code == 409
    assert stale_response.json()["error"]["code"] == "BENCHMARK_COORDINATOR_FENCE_REJECTED"

    reclaimed = client.post(
        f"/api/v1/benchmark-campaigns/{campaign_id}/coordinator/claim",
        json={"owner_id": "coordinator-b", "lease_seconds": 60},
    )
    assert reclaimed.status_code == 200, reclaimed.text
    assert reclaimed.json()["data"]["lease_generation"] == 2


def test_expired_coordinator_lease_is_recoverable_without_resetting_usage(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/benchmark-campaigns",
        json={"manifest": _manifest()},
    ).json()["data"]
    first = client.post(
        f"/api/v1/benchmark-campaigns/{created['id']}/coordinator/claim",
        json={"owner_id": "crashed-coordinator", "lease_seconds": 60},
    )
    assert first.status_code == 200, first.text

    from app.db import SessionLocal

    with SessionLocal() as db:
        db.execute(
            text(
                "UPDATE benchmark_campaign_coordinator_states "
                "SET lease_expires_at='2000-01-01 00:00:00' WHERE campaign_id=:id"
            ),
            {"id": created["id"]},
        )
        db.commit()

    recovered = client.post(
        f"/api/v1/benchmark-campaigns/{created['id']}/coordinator/claim",
        json={"owner_id": "recovery-coordinator", "lease_seconds": 60},
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["data"]["lease_generation"] == 2


def test_coordinator_endpoints_preserve_not_found_contract(client: TestClient) -> None:
    campaign_id = "00000000-0000-4000-8000-000000000099"
    claimed = client.post(
        f"/api/v1/benchmark-campaigns/{campaign_id}/coordinator/claim",
        json={"owner_id": "coordinator-a", "lease_seconds": 60},
    )
    assert claimed.status_code == 404
    assert claimed.json()["error"]["code"] == "BENCHMARK_CAMPAIGN_NOT_FOUND"

    usage = client.get(f"/api/v1/benchmark-campaigns/{campaign_id}/usage")
    assert usage.status_code == 404
    assert usage.json()["error"]["code"] == "BENCHMARK_CAMPAIGN_NOT_FOUND"


def test_campaign_batch_binding_freezes_all_jobs_ordinals_arms_and_seeds(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/benchmark-campaigns",
        json={"manifest": _manifest()},
    ).json()["data"]
    batch = client.post(
        "/api/v1/batches",
        json={
            "name": "paired-block-01",
            "jobs": [
                {**HEURISTIC_JOB_PAYLOAD, "display_name": "random"},
                {**HEURISTIC_JOB_PAYLOAD, "display_name": "adaptive"},
            ],
        },
    ).json()["data"]
    jobs = client.get(f"/api/v1/batches/{batch['id']}/jobs").json()["data"]

    from app.db import SessionLocal

    with SessionLocal() as db:
        db.execute(
            text("UPDATE benchmark_campaigns SET status='ACTIVE' WHERE id=:id"),
            {"id": created["id"]},
        )
        db.commit()
    claimed = client.post(
        f"/api/v1/benchmark-campaigns/{created['id']}/coordinator/claim",
        json={"owner_id": "campaign-coordinator", "lease_seconds": 120},
    ).json()["data"]
    payload = {
        "binding_key": "pilot-a-block-01",
        "lease_generation": claimed["lease_generation"],
        "batch_id": batch["id"],
        "runs": [
            {
                "run_key": "run-02-adaptive",
                "job_id": jobs[1]["id"],
                "benchmark_arm_id": "dronedream-adaptive",
                "arm_version": "v1",
                "algorithm_seed": 102,
                "simulator_seed_block": "crn-block-01",
                "provider_randomness_policy": "fixed_seed",
                "provider_seed": 20260804,
            },
            {
                "run_key": "run-01-random",
                "job_id": jobs[0]["id"],
                "benchmark_arm_id": "random-search",
                "arm_version": "v1",
                "algorithm_seed": 101,
                "simulator_seed_block": "crn-block-01",
                "provider_randomness_policy": "not_applicable",
                "provider_seed": None,
            },
        ],
    }
    endpoint = f"/api/v1/benchmark-campaigns/{created['id']}/batch-bindings"
    response = client.post(
        endpoint,
        json=payload,
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )
    assert response.status_code == 200, response.text
    binding = response.json()["data"]
    assert binding["batch_ordinal"] == 1
    assert binding["job_count"] == 2
    assert [run["run_key"] for run in binding["runs"]] == [
        "run-01-random",
        "run-02-adaptive",
    ]
    assert [run["run_ordinal"] for run in binding["runs"]] == [1, 2]
    assert [run["batch_run_ordinal"] for run in binding["runs"]] == [1, 2]
    assert binding["runs"][0]["simulator_seed_block"] == "crn-block-01"
    assert binding["runs"][1]["provider_seed"] == 20260804

    reordered_payload = deepcopy(payload)
    reordered_payload["runs"].reverse()
    replay = client.post(
        endpoint,
        json=reordered_payload,
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["id"] == binding["id"]
    changed = deepcopy(payload)
    changed["runs"][0]["algorithm_seed"] = 999
    conflict = client.post(
        endpoint,
        json=changed,
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "BENCHMARK_BATCH_BINDING_KEY_CONFLICT"

    listing = client.get(endpoint)
    assert listing.status_code == 200
    assert listing.json()["data"] == [binding]
    usage = client.get(f"/api/v1/benchmark-campaigns/{created['id']}/usage")
    assert usage.json()["data"]["used"]["jobs"] == 2

    second_batch = client.post(
        "/api/v1/batches",
        json={"name": "paired-block-02", "jobs": [HEURISTIC_JOB_PAYLOAD]},
    ).json()["data"]
    second_job = client.get(
        f"/api/v1/batches/{second_batch['id']}/jobs"
    ).json()["data"][0]
    second_binding = client.post(
        endpoint,
        json={
            "binding_key": "pilot-a-block-02",
            "lease_generation": claimed["lease_generation"],
            "batch_id": second_batch["id"],
            "runs": [
                {
                    "run_key": "run-03-random",
                    "job_id": second_job["id"],
                    "benchmark_arm_id": "random-search",
                    "arm_version": "v1",
                    "algorithm_seed": 103,
                    "simulator_seed_block": "crn-block-02",
                    "provider_randomness_policy": "not_applicable",
                    "provider_seed": None,
                }
            ],
        },
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )
    assert second_binding.status_code == 200, second_binding.text
    assert second_binding.json()["data"]["batch_ordinal"] == 2
    assert second_binding.json()["data"]["runs"][0]["run_ordinal"] == 3
    usage = client.get(f"/api/v1/benchmark-campaigns/{created['id']}/usage")
    assert usage.json()["data"]["used"]["jobs"] == 3

    with SessionLocal() as db:
        with pytest.raises(DatabaseError, match="execution bindings are append-only"):
            db.execute(
                text(
                    "UPDATE benchmark_campaign_run_bindings SET algorithm_seed=999 "
                    "WHERE id=:id"
                ),
                {"id": binding["runs"][0]["id"]},
            )
            db.commit()
        db.rollback()


def test_campaign_batch_binding_rejects_partial_started_or_unknown_arm(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/benchmark-campaigns",
        json={"manifest": _manifest()},
    ).json()["data"]
    batch = client.post(
        "/api/v1/batches",
        json={
            "name": "paired-block-02",
            "jobs": [HEURISTIC_JOB_PAYLOAD, HEURISTIC_JOB_PAYLOAD],
        },
    ).json()["data"]
    jobs = client.get(f"/api/v1/batches/{batch['id']}/jobs").json()["data"]
    from app.db import SessionLocal

    with SessionLocal() as db:
        db.execute(
            text("UPDATE benchmark_campaigns SET status='ACTIVE' WHERE id=:id"),
            {"id": created["id"]},
        )
        db.commit()
    claimed = client.post(
        f"/api/v1/benchmark-campaigns/{created['id']}/coordinator/claim",
        json={"owner_id": "campaign-coordinator", "lease_seconds": 120},
    ).json()["data"]
    endpoint = f"/api/v1/benchmark-campaigns/{created['id']}/batch-bindings"
    base_run = {
        "run_key": "run-01",
        "job_id": jobs[0]["id"],
        "benchmark_arm_id": "random-search",
        "arm_version": "v1",
        "algorithm_seed": 101,
        "simulator_seed_block": "crn-block-02",
        "provider_randomness_policy": "not_applicable",
        "provider_seed": None,
    }
    partial = client.post(
        endpoint,
        json={
            "binding_key": "partial",
            "lease_generation": claimed["lease_generation"],
            "batch_id": batch["id"],
            "runs": [base_run],
        },
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )
    assert partial.status_code == 422
    assert partial.json()["error"]["code"] == "BENCHMARK_BATCH_JOB_SET_MISMATCH"

    unknown = deepcopy(base_run)
    unknown["benchmark_arm_id"] = "unregistered-arm"
    unknown["job_id"] = jobs[1]["id"]
    unknown["run_key"] = "run-02"
    arm_failure = client.post(
        endpoint,
        json={
            "binding_key": "unknown-arm",
            "lease_generation": claimed["lease_generation"],
            "batch_id": batch["id"],
            "runs": [base_run, unknown],
        },
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )
    assert arm_failure.status_code == 422
    assert arm_failure.json()["error"]["code"] == "BENCHMARK_RUN_ARM_NOT_IN_CAMPAIGN"

    with SessionLocal() as db:
        from app import models

        job = db.get(models.Job, jobs[0]["id"])
        assert job is not None
        job.status = "RUNNING"
        db.commit()
    second_run = deepcopy(base_run)
    second_run["job_id"] = jobs[1]["id"]
    second_run["run_key"] = "run-02"
    started = client.post(
        endpoint,
        json={
            "binding_key": "started",
            "lease_generation": claimed["lease_generation"],
            "batch_id": batch["id"],
            "runs": [base_run, second_run],
        },
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )
    assert started.status_code == 409
    assert started.json()["error"]["code"] == "BENCHMARK_BATCH_ALREADY_STARTED"
