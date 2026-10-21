"""Production routing tests for immutable benchmark arm bindings."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.benchmarking.contracts import (
    BENCHMARK_OBSERVATION_CONTRACT_SHA256,
    canonical_sha256,
)
from app.orchestration.qualification import QUALIFICATION_RULE_SHA256

_SHA = "1" * 64
_COMMIT = "a" * 40
_SCENARIO_SUITE = {
    "cases": [
        {
            "id": "screen-nominal",
            "scenario_type": "nominal",
            "seeds": [101, 102, 103, 104],
            "enabled": True,
            "holdout": False,
            "config": {},
        },
        {
            "id": "qualification-combined",
            "scenario_type": "combined_perturbed",
            "seeds": list(range(901, 921)),
            "enabled": True,
            "holdout": True,
            "config": {"wind_mps": 3.0},
        },
    ],
    "common_random_numbers": True,
}


def _component(component_id: str) -> dict[str, object]:
    return {
        "component_id": component_id,
        "version": "test-v1",
        "source_commit": _COMMIT,
        "artifact_sha256": _SHA,
        "manifest_sha256": "2" * 64,
    }


def _job_payload() -> dict[str, Any]:
    return {
        "display_name": "benchmark-routing-poisoned-product-strategy",
        "simulator_backend": "mock",
        # This is deliberately incompatible with the frozen benchmark arm.
        # The test proves that it cannot select the research algorithm.
        "optimizer_strategy": "heuristic",
        "parameter_space": [
            {
                "name": "MPC_XY_P",
                "baseline": 0.95,
                "minimum": 0.6,
                "maximum": 1.3,
                "step": 0.1,
            }
        ],
        "objective_config": {
            "objectives": [
                {
                    "metric": "rmse",
                    "direction": "minimize",
                    "weight": 1.0,
                    "normalization": 1.0,
                }
            ],
            "constraints": [],
        },
        "scenario_suite": deepcopy(_SCENARIO_SUITE),
        "acceptance_criteria": {
            "target_rmse": 1e-12,
            "target_max_error": 1e-12,
            "min_pass_rate": 1.0,
        },
        "max_iterations": 2,
        "trials_per_candidate": 4,
        "max_total_trials": 100,
    }


def _manifest(
    *,
    adapter_id: str,
    benchmark_arm_id: str,
    fairness_hashes: dict[str, str],
    scenario_manifest_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_id": "dronedream.benchmark-campaign/v1",
        "campaign_key": f"routing-{benchmark_arm_id}",
        "campaign_version": "v1",
        "name": "Production benchmark arm routing",
        "panel": "engineering",
        "protocol_sha256": "7" * 64,
        "generated_at": "2026-08-05T00:00:00Z",
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
            **fairness_hashes,
            "qualification_rule_sha256": QUALIFICATION_RULE_SHA256,
            "scenario_manifest_sha256": scenario_manifest_sha256,
            "seed_block_manifest_sha256": "9" * 64,
        },
        "budget_caps": {
            "schema_id": "dronedream.benchmark-budget-caps/v1",
            "jobs": 4,
            "trials": 400,
            "logical_turns": 0,
            "network_requests": 0,
            "input_utf8_bytes": 0,
            "output_utf8_bytes": 0,
            "provider_tokens": 0,
            "provider_cost_microusd": 0,
            "wall_time_seconds": 3600,
            "disk_bytes": 10_000_000,
        },
        "arms": [
            {
                "schema_id": "dronedream.benchmark-arm/v1",
                "benchmark_arm_id": benchmark_arm_id,
                "arm_version": "v1",
                "arm_family": "traditional",
                "proposal_adapter_id": adapter_id,
                "evaluator_contract_id": "dronedream.candidate-evaluator/v1",
                "intervention": {"algorithm_seed_policy": "paired-block-v1"},
                "provider_contract_sha256": None,
                "dependencies": [],
                "execution_enabled": True,
            }
        ],
    }


def _bind_job(
    client: TestClient,
    *,
    adapter_id: str,
    benchmark_arm_id: str,
) -> str:
    created_batch = client.post(
        "/api/v1/batches",
        json={"name": f"batch-{benchmark_arm_id}", "jobs": [_job_payload()]},
    )
    assert created_batch.status_code == 200, created_batch.text
    batch = created_batch.json()["data"]
    listed_jobs = client.get(f"/api/v1/batches/{batch['id']}/jobs")
    assert listed_jobs.status_code == 200, listed_jobs.text
    job = listed_jobs.json()["data"][0]

    from app import models
    from app.benchmarking.job_runtime import runtime_fairness_hashes
    from app.db import SessionLocal
    from app.schemas import ScenarioSuiteConfig

    with SessionLocal() as db:
        stored = db.get(models.Job, job["id"])
        assert stored is not None
        hashes = runtime_fairness_hashes(stored)
        scenario_manifest_sha256 = canonical_sha256(
            ScenarioSuiteConfig.model_validate(stored.scenario_suite_json).model_dump(mode="json")
        )
    campaign = client.post(
        "/api/v1/benchmark-campaigns",
        json={
            "manifest": _manifest(
                adapter_id=adapter_id,
                benchmark_arm_id=benchmark_arm_id,
                fairness_hashes=hashes,
                scenario_manifest_sha256=scenario_manifest_sha256,
            )
        },
    ).json()["data"]
    with SessionLocal() as db:
        db.execute(
            text("UPDATE benchmark_campaigns SET status='ACTIVE' WHERE id=:id"),
            {"id": campaign["id"]},
        )
        db.commit()
    lease = client.post(
        f"/api/v1/benchmark-campaigns/{campaign['id']}/coordinator/claim",
        json={"owner_id": "routing-test", "lease_seconds": 120},
    ).json()["data"]
    bound = client.post(
        f"/api/v1/benchmark-campaigns/{campaign['id']}/batch-bindings",
        json={
            "binding_key": f"binding-{benchmark_arm_id}",
            "lease_generation": lease["lease_generation"],
            "batch_id": batch["id"],
            "runs": [
                {
                    "run_key": f"run-{benchmark_arm_id}",
                    "job_id": job["id"],
                    "benchmark_arm_id": benchmark_arm_id,
                    "arm_version": "v1",
                    "algorithm_seed": 20260805,
                    "simulator_seed_block": "crn-routing",
                    "provider_randomness_policy": "not_applicable",
                    "provider_seed": None,
                }
            ],
        },
        headers={"X-Benchmark-Lease-Token": lease["lease_token"]},
    )
    assert bound.status_code == 200, bound.text
    return str(job["id"])


@pytest.mark.parametrize(
    ("adapter_id", "benchmark_arm_id"),
    (("random_search/v1", "random-search"), ("seeded_halton/v1", "seeded-halton")),
)
def test_bound_job_uses_frozen_arm_not_product_optimizer_strategy(
    client: TestClient,
    adapter_id: str,
    benchmark_arm_id: str,
) -> None:
    job_id = _bind_job(
        client,
        adapter_id=adapter_id,
        benchmark_arm_id=benchmark_arm_id,
    )

    from app import models
    from app.db import SessionLocal
    from app.orchestration import runner

    for _ in range(120):
        runner.tick("benchmark-routing-test-worker")
        with SessionLocal() as db:
            job = db.get(models.Job, job_id)
            assert job is not None
            if job.status in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
    else:  # pragma: no cover - bounded diagnostic guard.
        raise AssertionError("benchmark Job did not reach a terminal state")

    with SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        assert job.status == "COMPLETED"
        assert job.optimizer_strategy == "heuristic"
        optimizer_candidates = [item for item in job.candidates if not item.is_baseline]
        assert optimizer_candidates
        for candidate in optimizer_candidates:
            metadata = candidate.optimizer_metadata_json
            assert isinstance(metadata, dict)
            context = metadata["benchmark_proposal_context"]
            assert context["proposal_adapter_id"] == adapter_id
            assert candidate.proposal_reason == f"benchmark:{adapter_id}"
        assert not any(
            event.event_type == "optimizer_started"
            and (event.event_data_json or {}).get("strategy") == "heuristic"
            for event in job.events
        )


def test_bound_job_manifest_drift_fails_before_baseline_dispatch(client: TestClient) -> None:
    job_id = _bind_job(
        client,
        adapter_id="random_search/v1",
        benchmark_arm_id="random-search",
    )

    from sqlalchemy.orm.attributes import set_committed_value

    from app import models
    from app.benchmarking.job_runtime import BenchmarkJobRuntimeBlocked
    from app.db import SessionLocal
    from app.orchestration.job_manager import start_job

    with SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        binding = job.benchmark_run_binding
        assert binding is not None
        arm = db.get(models.BenchmarkArm, binding.benchmark_arm_id)
        assert arm is not None
        # Simulate a corrupted persistence snapshot without issuing an UPDATE;
        # the real database also has an immutable-row trigger as the first line
        # of defence.
        set_committed_value(
            arm,
            "manifest_json",
            {**arm.manifest_json, "arm_version": "tampered-v2"},
        )
        with pytest.raises(BenchmarkJobRuntimeBlocked, match="manifest hash"):
            start_job(db, job)
        db.rollback()
        db.refresh(job)
        assert job.status == "QUEUED"
        assert not job.candidates
        assert not job.trials


def test_bound_job_scenario_manifest_drift_fails_before_baseline_dispatch(
    client: TestClient,
) -> None:
    job_id = _bind_job(
        client,
        adapter_id="random_search/v1",
        benchmark_arm_id="random-search",
    )

    from sqlalchemy.orm.attributes import set_committed_value

    from app import models
    from app.benchmarking.job_runtime import BenchmarkJobRuntimeBlocked
    from app.db import SessionLocal
    from app.orchestration.job_manager import start_job

    with SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        binding = job.benchmark_run_binding
        assert binding is not None
        campaign = db.get(models.BenchmarkCampaign, binding.campaign_id)
        assert campaign is not None
        manifest = deepcopy(campaign.manifest_json)
        manifest["fairness"]["scenario_manifest_sha256"] = "f" * 64
        set_committed_value(campaign, "manifest_json", manifest)
        set_committed_value(campaign, "manifest_sha256", canonical_sha256(manifest))

        with pytest.raises(BenchmarkJobRuntimeBlocked) as raised:
            start_job(db, job)
        assert raised.value.code == "benchmark_scenario_manifest_drift"
        db.rollback()
        db.refresh(job)
        assert job.status == "QUEUED"
        assert not job.candidates
        assert not job.trials
