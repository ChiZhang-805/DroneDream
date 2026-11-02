from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import models
from app.benchmarking.contracts import canonical_sha256
from app.benchmarking.physical_stability_job_evidence import (
    PhysicalStabilityJobEvidenceError,
    compile_physical_stability_job_evidence,
)
from app.orchestration.attempt_evidence import TrialAcceptedAttemptEvidenceV1
from app.simulator.scenario_effects import build_scenario_effect_request


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _fixture(*, job_status: str = "COMPLETED"):
    job_id = "job-p5-server-evidence"
    candidate_id = "cand-server-generated-baseline"
    candidate = SimpleNamespace(
        id=candidate_id,
        is_baseline=True,
        parameter_json={"MPC_XY_P": 1.0},
    )
    artifacts_by_trial: dict[str, dict[str, object]] = {}
    rows: dict[str, models.Artifact] = {}
    payloads: dict[str, bytes] = {}
    accepted: dict[str, TrialAcceptedAttemptEvidenceV1 | None] = {}
    trials: list[SimpleNamespace] = []
    obstacle = {
        "type": "box",
        "x": 1.0,
        "y": 2.0,
        "z": 0.5,
        "size_x": 1.0,
        "size_y": 2.0,
        "size_z": 1.0,
    }
    for ordinal in range(1, 11):
        trial_id = f"tri-p5-{ordinal:02d}"
        seed = 31_000 + ordinal
        metric = SimpleNamespace(
            rmse=0.4,
            max_error=0.8,
            completion_time=12.0,
            pass_flag=True,
            crash_flag=False,
            timeout_flag=False,
            instability_flag=False,
        )
        trial = SimpleNamespace(
            id=trial_id,
            job_id=job_id,
            candidate_id=candidate_id,
            seed=seed,
            scenario_type="nominal",
            status="COMPLETED",
            failure_code=None,
            metric=metric,
        )
        trials.append(trial)
        identity = {
            "trial_id": trial_id,
            "job_id": job_id,
            "candidate_id": candidate_id,
            "seed": seed,
            "attempt_count": 1,
        }
        request = build_scenario_effect_request(
            execution_identity=identity,
            scenario_type="nominal",
            scenario_config={},
            job_config={"wind": {}, "sensor_noise_level": "medium"},
            advanced_config={"obstacles": [obstacle]},
        )
        effect = {
            "schema_version": "dronedream.scenario_effect_evidence.v1",
            "request_sha256": request["request_sha256"],
            "execution_identity": identity,
            "launcher": "fixture-launcher",
            "world": "default",
            "effects": [
                {
                    "effect_id": "obstacles",
                    "mechanism": "gazebo_entity_factory",
                    "status": "applied",
                    "capability": {"status": "available", "reason": "fixture"},
                    "evidence": {
                        "created_entities": [
                            {
                                "source_index": 0,
                                "entity_name": "fixture-obstacle",
                                "service": "/world/default/create",
                                "response_data": True,
                                "sdf_sha256": "a" * 64,
                            }
                        ]
                    },
                }
            ],
        }
        parameter_input = {"MPC_XY_P": 1.0}
        parameter = {
            "schema_version": "dronedream.px4_parameter_evidence.v1",
            "kind": "applied",
            "status": "ok",
            "context": {
                "trial_id": trial_id,
                "job_id": job_id,
                "candidate_id": candidate_id,
            },
            "values": parameter_input,
            "verification": {"verified": True, "mismatches": {}},
        }
        artifact_payloads = {
            "telemetry_json": _json_bytes({"samples": []}),
            "scenario_effect_request_json": _json_bytes(request),
            "scenario_effect_evidence_json": _json_bytes(effect),
            "px4_parameters_input_json": _json_bytes(parameter_input),
            "px4_parameter_evidence_json": _json_bytes(parameter),
        }
        evidence_items: list[dict[str, object]] = []
        for artifact_type, raw in artifact_payloads.items():
            artifact_id = f"art-{ordinal:02d}-{artifact_type}"
            digest = hashlib.sha256(raw).hexdigest()
            rows[artifact_id] = models.Artifact(
                id=artifact_id,
                owner_type="trial",
                owner_id=trial_id,
                artifact_type=artifact_type,
                storage_path=f"fixture://{artifact_id}",
            )
            payloads[artifact_id] = raw
            evidence_items.append(
                {
                    "artifact_id": artifact_id,
                    "owner_type": "trial",
                    "owner_id": trial_id,
                    "artifact_type": artifact_type,
                    "mime_type": "application/json",
                    "content_evidence": "sealed-bytes",
                    "receipt_id": f"receipt-{artifact_id}",
                    "receipt_evidence_id": "sha256:" + "9" * 64,
                    "content_sha256": digest,
                    "content_size_bytes": len(raw),
                    "storage_path_sha256": "8" * 64,
                }
            )
        evidence = {
            "schema_id": "dronedream.trial-artifact-evidence/v1",
            "trial_id": trial_id,
            "artifact_count": len(evidence_items),
            "sealed_artifact_count": len(evidence_items),
            "metadata_only_artifact_count": 0,
            "artifacts": evidence_items,
        }
        artifacts_by_trial[trial_id] = evidence
        accepted[trial_id] = TrialAcceptedAttemptEvidenceV1(
            trial_id=trial_id,
            attempt_id=f"attempt-{ordinal:02d}",
            attempt_count=1,
            claim_evidence_id="sha256:" + "1" * 64,
            outcome_evidence_id="sha256:" + "2" * 64,
            terminal_status="COMPLETED",
            outcome_class="success",
            metric_sha256="sha256:" + "3" * 64,
            artifact_evidence_sha256="sha256:" + canonical_sha256(evidence),
        )
    job = SimpleNamespace(
        id=job_id,
        status=job_status,
        simulator_backend_requested="real_cli",
        optimizer_strategy="none",
        provider_turns_attempted=0,
        provider_turns_succeeded=0,
        provider_requests_attempted=0,
        provider_requests_succeeded=0,
        baseline_candidate_id=candidate_id,
        candidates=[candidate],
        trials=trials,
    )
    return job, artifacts_by_trial, rows, payloads, accepted


def _compile(fixture):
    job, evidence, rows, payloads, accepted = fixture
    return compile_physical_stability_job_evidence(
        job,
        artifact_evidence_override=evidence,
        artifact_rows_override=rows,
        artifact_payloads_override=payloads,
        accepted_attempt_override=accepted,
    )


def test_compiles_server_baseline_and_complete_byte_verified_trials() -> None:
    snapshot = _compile(_fixture())

    assert snapshot.observed_baseline_candidate_id == "cand-server-generated-baseline"
    assert snapshot.job_status == "completed"
    assert len(snapshot.trials) == 10
    assert all(item.terminal_status == "completed" for item in snapshot.trials)
    assert all(item.effect_ids_read_back == ("obstacles",) for item in snapshot.trials)
    assert all(item.parameter_readback_receipt_sha256 for item in snapshot.trials)
    assert all(item.safety_critical_failure is False for item in snapshot.trials)


def test_rejects_parameter_tamper_duplicate_type_and_provider_activity() -> None:
    fixture = _fixture()
    payloads = fixture[3]
    first_parameter_id = next(
        key for key in payloads if key.endswith("px4_parameter_evidence_json")
    )
    payloads[first_parameter_id] += b" "
    with pytest.raises(PhysicalStabilityJobEvidenceError, match="bytes diverged"):
        _compile(fixture)

    fixture = _fixture()
    first_evidence = next(iter(fixture[1].values()))
    first_evidence["artifacts"].append(deepcopy(first_evidence["artifacts"][0]))
    first_trial_id = str(first_evidence["trial_id"])
    current_attempt = fixture[4][first_trial_id]
    assert current_attempt is not None
    fixture[4][first_trial_id] = current_attempt.model_copy(
        update={"artifact_evidence_sha256": "sha256:" + canonical_sha256(first_evidence)}
    )
    with pytest.raises(PhysicalStabilityJobEvidenceError, match="duplicated"):
        _compile(fixture)

    fixture = _fixture()
    fixture[0].provider_requests_attempted = 1
    with pytest.raises(PhysicalStabilityJobEvidenceError, match="provider activity"):
        _compile(fixture)


def test_failed_job_retains_missing_attempt_as_indeterminate() -> None:
    fixture = _fixture(job_status="FAILED")
    first_trial = fixture[0].trials[0]
    first_trial.status = "FAILED"
    first_trial.failure_code = "SIMULATION_TIMEOUT"
    fixture[4][first_trial.id] = None

    snapshot = _compile(fixture)

    assert snapshot.job_status == "failed"
    assert snapshot.trials[0].terminal_status == "indeterminate"
    assert snapshot.trials[0].failure_code == "MISSING_ACCEPTED_ATTEMPT_EVIDENCE"


def test_completed_job_fails_closed_when_accepted_attempt_is_missing() -> None:
    fixture = _fixture()
    first_trial = fixture[0].trials[0]
    fixture[4][first_trial.id] = None

    with pytest.raises(ValueError, match="completed P5 Job contains incomplete"):
        _compile(fixture)


def test_authenticated_route_fails_closed_before_terminal_evidence(client: TestClient) -> None:
    created = client.post("/api/v1/jobs", json={})
    assert created.status_code == 200, created.text
    job_id = created.json()["data"]["id"]

    response = client.get(f"/api/v1/jobs/{job_id}/physical-stability-evidence")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PHYSICAL_STABILITY_EVIDENCE_NOT_READY"
