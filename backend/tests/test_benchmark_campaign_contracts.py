from __future__ import annotations

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
