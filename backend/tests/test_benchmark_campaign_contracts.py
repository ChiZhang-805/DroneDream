from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.benchmarking.contracts import (
    BENCHMARK_OBSERVATION_CONTRACT_SHA256,
    BENCHMARK_OBSERVATION_V1_CONTRACT_SHA256,
    BenchmarkCampaignManifestV1,
    BenchmarkHistoryItemV2,
    BenchmarkObservationV1,
    BenchmarkObservationV2,
    BenchmarkOptimizerOutcomeV1,
    BenchmarkProposalContextV1,
    BenchmarkProposalV1,
    canonical_sha256,
)
from app.benchmarking.llm_arm_contracts import BENCHMARK_LLM_ARM_POLICIES_SHA256
from app.orchestration.qualification import (
    QUALIFICATION_RULE_SHA256,
    compile_sealed_qualification_contract,
    sealed_qualification_contract_sha256,
)
from app.schemas import ScenarioSuiteConfig

from .test_jobs_api import HEURISTIC_JOB_PAYLOAD

_SHA = "1" * 64
_COMMIT = "a" * 40
_BENCHMARK_SCENARIO_SUITE = {
    "cases": [
        {
            "id": "screening-nominal",
            "scenario_type": "nominal",
            "seeds": [101, 102, 103, 104],
            "enabled": True,
            "holdout": False,
        },
        {
            "id": "sealed-holdout",
            "scenario_type": "combined_perturbed",
            "seeds": list(range(901, 921)),
            "enabled": True,
            "holdout": True,
            "config": {"wind_mps": 3.0},
        },
    ],
    "common_random_numbers": True,
}
_NORMALIZED_BENCHMARK_SCENARIO_SUITE = ScenarioSuiteConfig(
    **_BENCHMARK_SCENARIO_SUITE
).model_dump(mode="json")
_BENCHMARK_JOB_PAYLOAD = {
    **HEURISTIC_JOB_PAYLOAD,
    "scenario_suite": _BENCHMARK_SCENARIO_SUITE,
    "max_total_trials": 100,
}
_INVALID_SEALED_MATRIX_JOB_PAYLOAD = deepcopy(_BENCHMARK_JOB_PAYLOAD)
_INVALID_SEALED_MATRIX_JOB_PAYLOAD["scenario_suite"]["cases"][0]["seeds"] = [
    101,
    102,
    103,
]


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
            "qualification_rule_sha256": QUALIFICATION_RULE_SHA256,
            "scenario_manifest_sha256": canonical_sha256(
                _NORMALIZED_BENCHMARK_SCENARIO_SUITE
            ),
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


def _executable_pair_manifest(*, version: str) -> dict[str, object]:
    """Return two reviewed local arms for executable Batch-binding tests."""

    manifest = _manifest()
    manifest["campaign_version"] = version
    random_arm = manifest["arms"][0]
    random_arm["execution_enabled"] = True
    manifest["arms"][1] = {
        "schema_id": "dronedream.benchmark-arm/v1",
        "benchmark_arm_id": "seeded-halton",
        "arm_version": "v1",
        "arm_family": "traditional",
        "proposal_adapter_id": "seeded_halton/v1",
        "evaluator_contract_id": "dronedream.candidate-evaluator/v1",
        "intervention": {"algorithm_seed_policy": "paired-block-v1"},
        "provider_contract_sha256": None,
        "dependencies": [],
        "execution_enabled": True,
    }
    return manifest


def _executable_direct_manifest(*, version: str) -> dict[str, object]:
    manifest = _manifest()
    manifest["campaign_version"] = version
    manifest["arms"] = [
        {
            "schema_id": "dronedream.benchmark-arm/v1",
            "benchmark_arm_id": "llm-direct",
            "arm_version": "v1",
            "arm_family": "llm_harness",
            "proposal_adapter_id": "llm_direct/v1",
            "evaluator_contract_id": "dronedream.candidate-evaluator/v1",
            "intervention": {
                "provider_execution": {
                    "schema_id": "dronedream.benchmark-provider-execution/v1",
                    "provider": "openai",
                    "model_snapshot": "gpt-4.1-2025-04-14",
                    "api_surface": "chat_completions",
                    "base_url": "https://api.openai.com/v1",
                    "region": "global",
                    "temperature": 0.0,
                    "top_p": 1.0,
                    "randomness_policy": "fixed_seed",
                    "response_format": "json_schema",
                    "maximum_generations": 2,
                    "maximum_request_utf8_bytes": 65_536,
                    "maximum_response_utf8_bytes": 8_192,
                    "maximum_output_tokens": 128,
                    "request_timeout_ms": 10_000,
                    "provider_retry_cap": 0,
                    "llm_policy_registry_sha256": BENCHMARK_LLM_ARM_POLICIES_SHA256,
                    "model_matrix_sha256": "6" * 64,
                    "price_snapshot": {
                        "schema_version": "dronedream.provider-price-snapshot/v1",
                        "source": "preregistered",
                        "input_microusd_per_million_tokens": 2_000_000,
                        "output_microusd_per_million_tokens": 8_000_000,
                        "effective_at": "2026-08-05T00:00:00Z",
                    },
                }
            },
            "provider_contract_sha256": BENCHMARK_LLM_ARM_POLICIES_SHA256,
            "dependencies": [],
            "execution_enabled": True,
        }
    ]
    return manifest


def _direct_job_payload() -> dict[str, object]:
    return {
        **_BENCHMARK_JOB_PAYLOAD,
        "optimizer_strategy": "gpt",
        "max_iterations": 2,
        "provider_turn_cap": 2,
        "provider_request_cap": 2,
        "provider_max_retries": 0,
        "openai": {
            "api_key": "unit-test-provider-key",
            "model": "gpt-4.1-2025-04-14",
        },
    }


def test_unified_observation_excludes_holdout_and_sensitive_payloads() -> None:
    v1_schema = BenchmarkObservationV1.model_json_schema()
    v2_schema = BenchmarkObservationV2.model_json_schema()
    assert "holdout" not in " ".join(v1_schema["properties"]).lower()
    assert "holdout" not in " ".join(v2_schema["properties"]).lower()

    with pytest.raises(ValueError, match="sensitive field"):
        BenchmarkProposalV1(
            candidate_ref="candidate-1",
            parameters={"MPC_XY_P": 0.95},
            reason_code="bounded-proposal",
            proposal_receipt={"api_key": "forbidden"},
        )

    with pytest.raises(ValueError, match="objective outcomes"):
        BenchmarkOptimizerOutcomeV1(
            role="objective",
            loss=None,
            objectives={},
            objective_directions={},
            constraint_violations={},
            feasible=True,
            failure_rate=0.0,
            completed=True,
        )

    assert BENCHMARK_OBSERVATION_CONTRACT_SHA256 != BENCHMARK_OBSERVATION_V1_CONTRACT_SHA256


def test_v2_history_fails_closed_on_sensitive_oversized_or_inconsistent_provenance() -> None:
    with pytest.raises(ValueError, match="sensitive field"):
        BenchmarkProposalContextV1(
            proposal_adapter_id="optimizer_portfolio/v1",
            reason_code="portfolio-proposal",
            proposal_receipt_sha256="1" * 64,
            optimizer_strategy="optimizer_portfolio",
            optimizer_metadata={"raw_prompt": "forbidden"},
        )

    with pytest.raises(ValueError, match="65536 UTF-8 bytes"):
        BenchmarkProposalContextV1(
            proposal_adapter_id="optimizer_portfolio/v1",
            reason_code="portfolio-proposal",
            proposal_receipt_sha256="1" * 64,
            optimizer_strategy="optimizer_portfolio",
            optimizer_metadata={"diagnostic": "x" * 66_000},
        )

    objective = BenchmarkOptimizerOutcomeV1(
        role="objective",
        loss=0.2,
        objectives={"tracking": 0.2},
        objective_directions={"tracking": "minimize"},
        constraint_violations={"safety": 0.0},
        feasible=True,
        failure_rate=0.0,
        completed=True,
    )
    with pytest.raises(ValueError, match="must be quarantined"):
        BenchmarkHistoryItemV2(
            candidate_ref="indeterminate-candidate",
            generation_index=1,
            dispatch_ordinal=1,
            parameters={"x": 0.5},
            screening_status="indeterminate",
            outcome=objective,
            failure_code="worker-lost",
        )

    with pytest.raises(ValueError, match="constraint-only outcomes"):
        BenchmarkOptimizerOutcomeV1(
            role="constraint_only",
            loss=99.0,
            objectives={},
            objective_directions={},
            constraint_violations={"safety": 1.0},
            feasible=False,
            failure_rate=1.0,
            completed=True,
        )


def test_new_campaign_cannot_silently_execute_the_legacy_v1_observation_contract(
    client: TestClient,
) -> None:
    manifest = _manifest()
    manifest["campaign_version"] = "legacy-observation-v1"
    manifest["fairness"][
        "observation_contract_sha256"
    ] = BENCHMARK_OBSERVATION_V1_CONTRACT_SHA256

    response = client.post("/api/v1/benchmark-campaigns", json={"manifest": manifest})

    assert response.status_code == 422
    assert "frozen observation contract" in response.text


def test_new_campaign_requires_the_server_frozen_qualification_rule(
    client: TestClient,
) -> None:
    manifest = _manifest()
    manifest["campaign_version"] = "wrong-qualification-rule"
    manifest["fairness"]["qualification_rule_sha256"] = "f" * 64

    response = client.post("/api/v1/benchmark-campaigns", json={"manifest": manifest})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == (
        "BENCHMARK_QUALIFICATION_RULE_MISMATCH"
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
        json={"manifest": _executable_pair_manifest(version="binding-freeze-v1")},
    ).json()["data"]
    batch = client.post(
        "/api/v1/batches",
        json={
            "name": "paired-block-01",
            "jobs": [
                {**_BENCHMARK_JOB_PAYLOAD, "display_name": "random"},
                {**_BENCHMARK_JOB_PAYLOAD, "display_name": "adaptive"},
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
                "run_key": "run-02-halton",
                "job_id": jobs[1]["id"],
                "benchmark_arm_id": "seeded-halton",
                "arm_version": "v1",
                "algorithm_seed": 102,
                "simulator_seed_block": "crn-block-01",
                "provider_randomness_policy": "not_applicable",
                "provider_seed": None,
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
        "run-02-halton",
    ]
    assert [run["run_ordinal"] for run in binding["runs"]] == [1, 2]
    assert [run["batch_run_ordinal"] for run in binding["runs"]] == [1, 2]
    assert binding["runs"][0]["simulator_seed_block"] == "crn-block-01"
    assert binding["runs"][1]["provider_seed"] is None
    frozen_contract = compile_sealed_qualification_contract(
        ScenarioSuiteConfig(**_BENCHMARK_SCENARIO_SUITE)
    )
    expected_contract_sha256 = sealed_qualification_contract_sha256(frozen_contract)
    assert all(
        run["qualification_policy_version"] == "sealed-two-stage-v1"
        for run in binding["runs"]
    )
    assert all(
        run["scenario_suite_sha256"]
        == canonical_sha256(_NORMALIZED_BENCHMARK_SCENARIO_SUITE)
        for run in binding["runs"]
    )
    assert all(
        run["qualification_contract_sha256"] == expected_contract_sha256
        for run in binding["runs"]
    )

    from app import models

    with SessionLocal() as db:
        bound_jobs = [db.get(models.Job, item["id"]) for item in jobs]
        assert all(job is not None for job in bound_jobs)
        assert all(
            job.holdout_policy_version == "sealed-two-stage-v1"
            and job.holdout_contract_json == frozen_contract.model_dump(mode="json")
            for job in bound_jobs
            if job is not None
        )

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
        json={"name": "paired-block-02", "jobs": [_BENCHMARK_JOB_PAYLOAD]},
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


def test_direct_batch_binding_atomically_reserves_frozen_provider_capacity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.benchmarking import registry

    monkeypatch.setenv("APP_SECRET_KEY", "unit-test-secret-material")
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)
    descriptor = registry.BENCHMARK_ADAPTER_REGISTRY["llm_direct/v1"]
    monkeypatch.setitem(
        registry.BENCHMARK_ADAPTER_REGISTRY,
        "llm_direct/v1",
        registry.BenchmarkAdapterDescriptor(
            adapter_id=descriptor.adapter_id,
            family=descriptor.family,
            availability="implemented",
            implementation_label=descriptor.implementation_label,
            method_classification=descriptor.method_classification,
        ),
    )
    created_response = client.post(
        "/api/v1/benchmark-campaigns",
        json={"manifest": _executable_direct_manifest(version="direct-reserve-v1")},
    )
    assert created_response.status_code == 200, created_response.text
    created = created_response.json()["data"]
    batch_response = client.post(
        "/api/v1/batches",
        json={"name": "direct-block-01", "jobs": [_direct_job_payload()]},
    )
    assert batch_response.status_code == 200, batch_response.text
    batch = batch_response.json()["data"]
    job = client.get(f"/api/v1/batches/{batch['id']}/jobs").json()["data"][0]

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        db.execute(
            text("UPDATE benchmark_campaigns SET status='ACTIVE' WHERE id=:id"),
            {"id": created["id"]},
        )
        db.commit()
    claimed = client.post(
        f"/api/v1/benchmark-campaigns/{created['id']}/coordinator/claim",
        json={"owner_id": "direct-coordinator", "lease_seconds": 120},
    ).json()["data"]
    response = client.post(
        f"/api/v1/benchmark-campaigns/{created['id']}/batch-bindings",
        json={
            "binding_key": "direct-block-01",
            "lease_generation": claimed["lease_generation"],
            "batch_id": batch["id"],
            "runs": [
                {
                    "run_key": "direct-run-01",
                    "job_id": job["id"],
                    "benchmark_arm_id": "llm-direct",
                    "arm_version": "v1",
                    "algorithm_seed": 101,
                    "simulator_seed_block": "crn-direct-01",
                    "provider_randomness_policy": "fixed_seed",
                    "provider_seed": 20260805,
                }
            ],
        },
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["data"]["runs"][0]["id"]

    with SessionLocal() as db:
        reservation = db.scalar(
            select(models.BenchmarkBudgetReservation).where(
                models.BenchmarkBudgetReservation.reservation_key
                == f"provider-run/{run_id}"
            )
        )
        assert reservation is not None
        assert reservation.reason == "benchmark-provider-execution"
        assert reservation.logical_turns == 2
        assert reservation.network_requests == 2
        assert reservation.input_utf8_bytes == 65_536 * 2
        assert reservation.output_utf8_bytes == 8_192 * 2
        assert reservation.provider_tokens == (65_536 + 128) * 2
        assert reservation.provider_cost_microusd == 264_192
        assert reservation.wall_time_seconds == 20


def test_direct_batch_binding_rolls_back_when_provider_capacity_exceeds_campaign(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.benchmarking import registry

    monkeypatch.setenv("APP_SECRET_KEY", "unit-test-secret-material")
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)
    descriptor = registry.BENCHMARK_ADAPTER_REGISTRY["llm_direct/v1"]
    monkeypatch.setitem(
        registry.BENCHMARK_ADAPTER_REGISTRY,
        "llm_direct/v1",
        registry.BenchmarkAdapterDescriptor(
            adapter_id=descriptor.adapter_id,
            family=descriptor.family,
            availability="implemented",
            implementation_label=descriptor.implementation_label,
            method_classification=descriptor.method_classification,
        ),
    )
    manifest = _executable_direct_manifest(version="direct-cap-rollback-v1")
    manifest["budget_caps"]["logical_turns"] = 1
    created = client.post(
        "/api/v1/benchmark-campaigns",
        json={"manifest": manifest},
    ).json()["data"]
    batch = client.post(
        "/api/v1/batches",
        json={"name": "direct-cap-block", "jobs": [_direct_job_payload()]},
    ).json()["data"]
    job = client.get(f"/api/v1/batches/{batch['id']}/jobs").json()["data"][0]

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        db.execute(
            text("UPDATE benchmark_campaigns SET status='ACTIVE' WHERE id=:id"),
            {"id": created["id"]},
        )
        db.commit()
    claimed = client.post(
        f"/api/v1/benchmark-campaigns/{created['id']}/coordinator/claim",
        json={"owner_id": "direct-cap-coordinator", "lease_seconds": 120},
    ).json()["data"]
    response = client.post(
        f"/api/v1/benchmark-campaigns/{created['id']}/batch-bindings",
        json={
            "binding_key": "direct-cap-block",
            "lease_generation": claimed["lease_generation"],
            "batch_id": batch["id"],
            "runs": [
                {
                    "run_key": "direct-cap-run",
                    "job_id": job["id"],
                    "benchmark_arm_id": "llm-direct",
                    "arm_version": "v1",
                    "algorithm_seed": 101,
                    "simulator_seed_block": "crn-direct-cap",
                    "provider_randomness_policy": "fixed_seed",
                    "provider_seed": 20260805,
                }
            ],
        },
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "BENCHMARK_CAMPAIGN_CAP_EXCEEDED"

    with SessionLocal() as db:
        assert db.scalar(
            select(models.BenchmarkCampaignBatchBinding).where(
                models.BenchmarkCampaignBatchBinding.campaign_id == created["id"]
            )
        ) is None
        assert db.scalar(
            select(models.BenchmarkCampaignRunBinding).where(
                models.BenchmarkCampaignRunBinding.campaign_id == created["id"]
            )
        ) is None
        assert db.scalar(
            select(models.BenchmarkBudgetReservation).where(
                models.BenchmarkBudgetReservation.campaign_id == created["id"]
            )
        ) is None
        state = db.get(models.BenchmarkCampaignCoordinatorState, created["id"])
        assert state is not None
        assert state.next_batch_ordinal == 1
        assert state.next_run_ordinal == 1


def test_campaign_batch_binding_rejects_partial_started_or_unknown_arm(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/benchmark-campaigns",
        json={"manifest": _executable_pair_manifest(version="binding-rejections-v1")},
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


def test_campaign_binding_rejects_preregistered_but_execution_disabled_arm(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/benchmark-campaigns",
        json={"manifest": _manifest()},
    ).json()["data"]
    batch = client.post(
        "/api/v1/batches",
        json={"name": "disabled-arm", "jobs": [_BENCHMARK_JOB_PAYLOAD]},
    ).json()["data"]
    job = client.get(f"/api/v1/batches/{batch['id']}/jobs").json()["data"][0]

    from app import models
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
    response = client.post(
        f"/api/v1/benchmark-campaigns/{created['id']}/batch-bindings",
        json={
            "binding_key": "disabled-arm",
            "lease_generation": claimed["lease_generation"],
            "batch_id": batch["id"],
            "runs": [
                {
                    "run_key": "run-disabled",
                    "job_id": job["id"],
                    "benchmark_arm_id": "random-search",
                    "arm_version": "v1",
                    "algorithm_seed": 101,
                    "simulator_seed_block": "crn-disabled",
                    "provider_randomness_policy": "not_applicable",
                    "provider_seed": None,
                }
            ],
        },
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == (
        "BENCHMARK_RUN_ARM_EXECUTION_DISABLED"
    )
    usage = client.get(f"/api/v1/benchmark-campaigns/{created['id']}/usage")
    assert usage.json()["data"]["used"]["jobs"] == 0
    with SessionLocal() as db:
        stored = db.get(models.Job, job["id"])
        assert stored is not None
        assert stored.holdout_policy_version == "legacy-visible-v0"
        assert stored.holdout_contract_json is None


@pytest.mark.parametrize(
    ("job_payload", "expected_error"),
    [
        (HEURISTIC_JOB_PAYLOAD, "BENCHMARK_SCENARIO_CONTRACT_MISSING"),
        (
            _INVALID_SEALED_MATRIX_JOB_PAYLOAD,
            "BENCHMARK_QUALIFICATION_CONTRACT_INVALID",
        ),
    ],
)
def test_campaign_binding_rejects_a_job_without_exact_sealed_contract(
    client: TestClient,
    job_payload: dict[str, object],
    expected_error: str,
) -> None:
    created = client.post(
        "/api/v1/benchmark-campaigns",
        json={
            "manifest": _executable_pair_manifest(
                version="invalid-sealed-matrix-v1"
            )
        },
    ).json()["data"]
    batch = client.post(
        "/api/v1/batches",
        json={"name": "invalid-sealed-matrix", "jobs": [job_payload]},
    ).json()["data"]
    job = client.get(f"/api/v1/batches/{batch['id']}/jobs").json()["data"][0]

    from app import models
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
    response = client.post(
        f"/api/v1/benchmark-campaigns/{created['id']}/batch-bindings",
        json={
            "binding_key": "invalid-sealed-matrix",
            "lease_generation": claimed["lease_generation"],
            "batch_id": batch["id"],
            "runs": [
                {
                    "run_key": "run-invalid",
                    "job_id": job["id"],
                    "benchmark_arm_id": "random-search",
                    "arm_version": "v1",
                    "algorithm_seed": 101,
                    "simulator_seed_block": "crn-invalid",
                    "provider_randomness_policy": "not_applicable",
                    "provider_seed": None,
                }
            ],
        },
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == expected_error
    with SessionLocal() as db:
        stored = db.get(models.Job, job["id"])
        assert stored is not None
        assert stored.holdout_policy_version == "legacy-visible-v0"
        assert stored.holdout_contract_json is None


def test_campaign_binding_rolls_back_job_sealing_when_global_cap_rejects(
    client: TestClient,
) -> None:
    manifest = _executable_pair_manifest(version="atomic-cap-rejection")
    manifest["budget_caps"]["jobs"] = 1
    created = client.post(
        "/api/v1/benchmark-campaigns",
        json={"manifest": manifest},
    ).json()["data"]
    batch = client.post(
        "/api/v1/batches",
        json={
            "name": "atomic-cap-rejection",
            "jobs": [_BENCHMARK_JOB_PAYLOAD, _BENCHMARK_JOB_PAYLOAD],
        },
    ).json()["data"]
    jobs = client.get(f"/api/v1/batches/{batch['id']}/jobs").json()["data"]

    from app import models
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
    response = client.post(
        f"/api/v1/benchmark-campaigns/{created['id']}/batch-bindings",
        json={
            "binding_key": "atomic-cap-rejection",
            "lease_generation": claimed["lease_generation"],
            "batch_id": batch["id"],
            "runs": [
                {
                    "run_key": "run-random",
                    "job_id": jobs[0]["id"],
                    "benchmark_arm_id": "random-search",
                    "arm_version": "v1",
                    "algorithm_seed": 101,
                    "simulator_seed_block": "crn-cap",
                    "provider_randomness_policy": "not_applicable",
                    "provider_seed": None,
                },
                {
                    "run_key": "run-halton",
                    "job_id": jobs[1]["id"],
                    "benchmark_arm_id": "seeded-halton",
                    "arm_version": "v1",
                    "algorithm_seed": 102,
                    "simulator_seed_block": "crn-cap",
                    "provider_randomness_policy": "not_applicable",
                    "provider_seed": None,
                },
            ],
        },
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BENCHMARK_CAMPAIGN_CAP_EXCEEDED"
    usage = client.get(f"/api/v1/benchmark-campaigns/{created['id']}/usage")
    assert usage.json()["data"]["used"]["jobs"] == 0
    with SessionLocal() as db:
        stored = [db.get(models.Job, job["id"]) for job in jobs]
        assert all(item is not None for item in stored)
        assert all(
            item.holdout_policy_version == "legacy-visible-v0"
            and item.holdout_contract_json is None
            for item in stored
            if item is not None
        )


def test_campaign_binding_rejects_paired_arms_with_scenario_drift(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/benchmark-campaigns",
        json={"manifest": _executable_pair_manifest(version="scenario-drift-v1")},
    ).json()["data"]
    drifted = deepcopy(_BENCHMARK_JOB_PAYLOAD)
    drifted["scenario_suite"]["cases"][1]["config"] = {"wind_mps": 4.0}
    batch = client.post(
        "/api/v1/batches",
        json={
            "name": "drifted-pair",
            "jobs": [_BENCHMARK_JOB_PAYLOAD, drifted],
        },
    ).json()["data"]
    jobs = client.get(f"/api/v1/batches/{batch['id']}/jobs").json()["data"]

    from app import models
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
    response = client.post(
        f"/api/v1/benchmark-campaigns/{created['id']}/batch-bindings",
        json={
            "binding_key": "drifted-pair",
            "lease_generation": claimed["lease_generation"],
            "batch_id": batch["id"],
            "runs": [
                {
                    "run_key": "run-random",
                    "job_id": jobs[0]["id"],
                    "benchmark_arm_id": "random-search",
                    "arm_version": "v1",
                    "algorithm_seed": 101,
                    "simulator_seed_block": "crn-shared",
                    "provider_randomness_policy": "not_applicable",
                    "provider_seed": None,
                },
                {
                    "run_key": "run-halton",
                    "job_id": jobs[1]["id"],
                    "benchmark_arm_id": "seeded-halton",
                    "arm_version": "v1",
                    "algorithm_seed": 102,
                    "simulator_seed_block": "crn-shared",
                    "provider_randomness_policy": "not_applicable",
                    "provider_seed": None,
                },
            ],
        },
        headers={"X-Benchmark-Lease-Token": claimed["lease_token"]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BENCHMARK_PAIRED_SCENARIO_MISMATCH"
    with SessionLocal() as db:
        stored = [db.get(models.Job, job["id"]) for job in jobs]
        assert all(item is not None for item in stored)
        assert all(
            item.holdout_policy_version == "legacy-visible-v0"
            and item.holdout_contract_json is None
            for item in stored
            if item is not None
        )
