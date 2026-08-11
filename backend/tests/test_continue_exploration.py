from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

_SCENARIO_SUITE = {
    "cases": [
        {
            "id": "training-nominal",
            "scenario_type": "nominal",
            "seeds": [101],
            "enabled": True,
            "holdout": False,
        },
        {
            "id": "sealed-holdout",
            "scenario_type": "combined_perturbed",
            "seeds": [901],
            "enabled": True,
            "holdout": True,
        },
    ],
    "common_random_numbers": True,
}


def _parent_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "track_type": "circle",
        "start_point": {"x": 0.0, "y": 0.0},
        "altitude_m": 3.0,
        "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
        "sensor_noise_level": "medium",
        "objective_profile": "robust",
        "simulator_backend": "mock",
        "optimizer_strategy": "none",
        "scenario_suite": _SCENARIO_SUITE,
        "max_total_trials": 2,
    }
    payload.update(overrides)
    return payload


def _budget(*, provider_turns: int = 0) -> dict[str, int]:
    return {
        "additional_generation_cap": 2,
        "additional_trial_cap": 4,
        "additional_provider_turn_cap": provider_turns,
        "additional_time_budget_seconds": 600,
    }


def _freeze_parent(client: TestClient, *, payload: dict[str, object] | None = None) -> dict:
    response = client.post("/api/v1/jobs", json=payload or _parent_payload())
    assert response.status_code == 200, response.text
    created = response.json()["data"]

    from app import models
    from app.db import SessionLocal
    from app.orchestration.acceptance import AcceptanceResult
    from app.orchestration.first_qualified import freeze_first_qualified_candidate

    with SessionLocal() as db:
        job = db.get(models.Job, created["id"])
        assert job is not None
        job.status = "FINALIZING"
        candidate = models.CandidateParameterSet(
            job_id=job.id,
            generation_index=0,
            dispatch_ordinal=1,
            source_type="baseline",
            parameter_json={
                "kp_xy": 1.25,
                "kd_xy": 0.22,
                "ki_xy": 0.05,
                "vel_limit": 5.0,
                "accel_limit": 4.0,
                "disturbance_rejection": 0.5,
            },
            aggregated_score=0.25,
            aggregated_metric_json={"selection_key": [0.0, 0.25]},
            trial_count=2,
            completed_trial_count=2,
            failed_trial_count=0,
            is_baseline=True,
        )
        db.add(candidate)
        db.flush()
        job.baseline_candidate_id = candidate.id
        job.best_candidate_id = candidate.id
        freeze_first_qualified_candidate(
            db,
            job=job,
            qualified=[
                (
                    candidate,
                    AcceptanceResult(
                        passed=True,
                        reason="test fixture qualification",
                        pass_rate=1.0,
                        completion_rate=1.0,
                        rmse=0.25,
                        max_error=0.5,
                    ),
                )
            ],
            frozen_at=datetime.now(timezone.utc),
        )
        job.status = "COMPLETED"
        job.current_phase = "completed"
        job.optimization_outcome = "success"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        first_id = job.first_qualified_candidate_id
    created["first_qualified_candidate_id"] = first_id
    return created


def _continue(
    client: TestClient,
    parent: dict,
    *,
    request: dict[str, object] | None = None,
    key: str | None = None,
    control_version: int | None = None,
):
    return client.post(
        (
            f"/api/v1/jobs/{parent['id']}/continue-exploration"
            f"?control_version={control_version or parent['control_version']}"
        ),
        headers={"Idempotency-Key": key or str(uuid4())},
        json=request or {"budget": _budget()},
    )


def test_continuation_creates_bounded_child_and_preserves_parent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _freeze_parent(client)
    from app.services import jobs as job_service

    monkeypatch.setattr(job_service, "candidate_is_publishable", lambda _candidate: True)
    response = _continue(client, parent)
    assert response.status_code == 200, response.text
    child = response.json()["data"]

    assert child["job_kind"] == "continue_exploration"
    assert child["completion_policy"] == "exploration_budget_stop"
    assert child["continuation_parent_job_id"] == parent["id"]
    assert child["continuation_root_job_id"] == parent["id"]
    assert child["holdout_policy_version"] == "continuation-independent-holdout-v1"
    assert child["provider_turn_cap"] == 0
    assert child["exploration_budget"] == _budget()
    assert child["baseline_parameters"]["kp_xy"] == 1.25

    training = next(case for case in child["scenario_suite"]["cases"] if not case["holdout"])
    holdout = next(case for case in child["scenario_suite"]["cases"] if case["holdout"])
    assert training["seeds"] == [101]
    assert holdout["seeds"] != [901]
    assert set(holdout["seeds"]).isdisjoint({101, 901})

    parent_after = client.get(f"/api/v1/jobs/{parent['id']}").json()["data"]
    assert parent_after["control_version"] == parent["control_version"] + 1
    assert parent_after["first_qualified_candidate_id"] == parent["first_qualified_candidate_id"]
    assert parent_after["continue_exploration_requested"] is True
    assert parent_after["exploration_budget"] == _budget()


def test_continuation_idempotency_replays_but_second_action_is_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _freeze_parent(client)
    from app.services import jobs as job_service

    monkeypatch.setattr(job_service, "candidate_is_publishable", lambda _candidate: True)
    key = str(uuid4())
    first = _continue(client, parent, key=key)
    replay = _continue(client, parent, key=key)
    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()

    duplicate = _continue(client, parent)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CONTINUATION_ALREADY_EXISTS"


def test_continuation_requires_complete_verified_parent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = client.post("/api/v1/jobs", json=_parent_payload())
    parent = response.json()["data"]
    from app.services import jobs as job_service

    monkeypatch.setattr(job_service, "candidate_is_publishable", lambda _candidate: True)
    blocked = _continue(client, parent)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "CONTINUATION_PARENT_NOT_COMPLETE"


def test_preregistered_continuation_budget_cannot_drift_at_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _freeze_parent(
        client,
        payload=_parent_payload(
            continue_exploration_after_qualified=True,
            exploration_budget=_budget(),
        ),
    )
    assert parent["continue_exploration_requested"] is False
    assert parent["exploration_budget"] == _budget()
    from app.services import jobs as job_service

    monkeypatch.setattr(job_service, "candidate_is_publishable", lambda _candidate: True)
    changed = _budget()
    changed["additional_time_budget_seconds"] = 900
    blocked = _continue(client, parent, request={"budget": changed})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "CONTINUATION_BUDGET_MISMATCH"


def test_continuation_rejects_stale_parent_control_version(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _freeze_parent(client)
    from app.services import jobs as job_service

    monkeypatch.setattr(job_service, "candidate_is_publishable", lambda _candidate: True)
    renamed = client.patch(
        f"/api/v1/jobs/{parent['id']}?control_version={parent['control_version']}",
        headers={"Idempotency-Key": str(uuid4())},
        json={"display_name": "changed after view"},
    )
    assert renamed.status_code == 200, renamed.text
    blocked = _continue(client, parent, control_version=parent["control_version"])
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "CONTROL_VERSION_CONFLICT"


def test_model_continuation_requires_fresh_binding_and_never_copies_parent_secret(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "unit-test-continuation-secret-material")
    parent = _freeze_parent(client)
    from app import models, secrets
    from app.db import SessionLocal
    from app.services import jobs as job_service

    monkeypatch.setattr(job_service, "candidate_is_publishable", lambda _candidate: True)
    with SessionLocal() as db:
        job = db.get(models.Job, parent["id"])
        assert job is not None
        job.optimizer_strategy = "llm_harness"
        job.llm_access_mode = "byok"
        job.llm_provider = "openai"
        job.openai_model = "gpt-4.1-2025-04-14"
        parent_secret = models.JobSecret(
            job_id=job.id,
            provider="openai",
            encrypted_api_key=secrets.encrypt_secret("parent-key-must-not-be-reused"),
        )
        db.add(parent_secret)
        db.commit()
        parent_secret_token = parent_secret.encrypted_api_key

    missing = _continue(
        client,
        parent,
        request={"budget": _budget(provider_turns=4)},
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "CONTINUATION_FRESH_GRANT_REQUIRED"

    created = _continue(
        client,
        parent,
        request={
            "budget": _budget(provider_turns=4),
            "llm": {
                "access_mode": "byok",
                "provider": "openai",
                "api_key": "fresh-child-key",
                "model": "gpt-4.1-2025-04-14",
            },
        },
    )
    assert created.status_code == 200, created.text
    child_id = created.json()["data"]["id"]
    with SessionLocal() as db:
        child_secrets = list(
            db.query(models.JobSecret).filter(models.JobSecret.job_id == child_id)
        )
        assert len(child_secrets) == 1
        assert child_secrets[0].encrypted_api_key != parent_secret_token
        assert secrets.decrypt_secret(child_secrets[0].encrypted_api_key) == "fresh-child-key"


def test_parent_with_continuation_cannot_be_deleted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _freeze_parent(client)
    from app import models
    from app.db import SessionLocal
    from app.services import jobs as job_service

    monkeypatch.setattr(job_service, "candidate_is_publishable", lambda _candidate: True)
    child = _continue(client, parent).json()["data"]
    with SessionLocal() as db:
        child_row = db.get(models.Job, child["id"])
        assert child_row is not None
        child_row.status = "COMPLETED"
        db.commit()
    blocked = client.delete(
        f"/api/v1/jobs/{parent['id']}?control_version={parent['control_version'] + 1}",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "JOB_HAS_CONTINUATION_CHILD"


def test_client_cannot_create_or_rerun_continuation_policy(client: TestClient) -> None:
    direct = client.post(
        "/api/v1/jobs",
        json={**_parent_payload(), "completion_policy": "exploration_budget_stop"},
    )
    assert direct.status_code == 422
    assert direct.json()["error"]["code"] == "INVALID_COMPLETION_POLICY"


def test_continuation_result_semantics_do_not_overstate_a_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.orchestration import aggregation
    from app.orchestration.acceptance import AcceptanceResult

    job = SimpleNamespace(
        job_kind="continue_exploration",
        exploration_budget_json={"additional_time_budget_seconds": 600},
        started_at=datetime.now(timezone.utc),
        queued_at=None,
        created_at=datetime.now(timezone.utc),
    )
    criteria = SimpleNamespace()
    monkeypatch.setattr(
        aggregation,
        "evaluate_candidate",
        lambda _candidate, _criteria: AcceptanceResult(
            passed=True,
            reason="fixture",
            pass_rate=1.0,
            completion_rate=1.0,
            rmse=0.1,
            max_error=0.2,
        ),
    )
    baseline = SimpleNamespace(
        is_baseline=True,
        aggregated_metric_json={"selection_key": [0.0, 0.25]},
        aggregated_score=0.25,
    )
    tied = SimpleNamespace(
        is_baseline=False,
        aggregated_metric_json={"selection_key": [0.0, 0.25]},
        aggregated_score=0.25,
    )
    improved = SimpleNamespace(
        is_baseline=False,
        aggregated_metric_json={"selection_key": [0.0, 0.20]},
        aggregated_score=0.20,
    )
    job.candidates = [baseline, tied, improved]
    monkeypatch.setattr(aggregation, "candidate_is_publishable", lambda _candidate: True)
    assert aggregation._determine_terminal_state(job, baseline, criteria)[0] == (
        "exploration_no_improvement"
    )
    assert aggregation._determine_terminal_state(job, tied, criteria)[0] == (
        "exploration_no_improvement"
    )
    assert aggregation._determine_terminal_state(job, improved, criteria)[0] == (
        "exploration_improved"
    )


def test_exploration_tie_break_uses_dispatch_order_not_candidate_uuid() -> None:
    from app.orchestration import aggregation

    common = {
        "aggregated_metric_json": {"selection_key": [0.0, 0.25]},
        "aggregated_score": 0.25,
        "is_baseline": False,
        "generation_index": 1,
        "dispatch_ordinal": 2,
    }
    lexically_early = SimpleNamespace(id="cand_000", **common)
    lexically_late = SimpleNamespace(id="cand_zzz", **common)
    assert aggregation._candidate_selection_rank_key(lexically_early) == (
        aggregation._candidate_selection_rank_key(lexically_late)
    )
