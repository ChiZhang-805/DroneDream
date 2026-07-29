"""Integration tests for /api/v1 job and trial endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

VALID_JOB_PAYLOAD: dict = {
    "track_type": "circle",
    "start_point": {"x": 0, "y": 0},
    "altitude_m": 5.0,
    "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
    "sensor_noise_level": "medium",
    "objective_profile": "robust",
}
HEURISTIC_JOB_PAYLOAD: dict = {
    **VALID_JOB_PAYLOAD,
    "optimizer_strategy": "heuristic",
    "simulator_backend": "mock",
}


# --- Create ----------------------------------------------------------------


def test_create_job_returns_queued(client: TestClient) -> None:
    resp = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["error"] is None
    job = body["data"]
    assert job["status"] == "QUEUED"
    assert job["id"].startswith("job_")
    # Backward-compatible alias for clients that expected the original
    # ``{job_id, status}`` wording in ``docs/04_API_SPEC.md``.
    assert job["job_id"] == job["id"]
    assert job["queued_at"] is not None
    assert job["started_at"] is None
    assert job["progress"]["completed_trials"] == 0
    assert job["track_type"] == "circle"
    assert job["sensor_noise_level"] == "medium"
    assert job["objective_profile"] == "robust"
    assert job["source_job_id"] is None


def test_baseline_only_job_accepts_locked_catalog_parameters(client: TestClient) -> None:
    response = client.post(
        "/api/v1/jobs",
        json={
            **VALID_JOB_PAYLOAD,
            "optimizer_strategy": "none",
            "simulator_backend": "mock",
            "parameter_space": [
                {
                    "name": "MPC_XY_P",
                    "baseline": 0.95,
                    "minimum": 0.95,
                    "maximum": 0.95,
                    "enabled": True,
                    "locked": True,
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    job = response.json()["data"]
    assert job["optimizer_strategy"] == "none"
    assert job["parameter_space"][0]["locked"] is True


def test_create_job_exposes_job_id_alias(client: TestClient) -> None:
    """The create response must include ``job_id`` (alias of ``id``)."""

    body = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()
    job = body["data"]
    assert body["success"] is True
    assert "id" in job
    assert "job_id" in job
    assert job["id"] == job["job_id"]
    assert job["status"] == "QUEUED"


def test_cancelling_gpt_job_purges_encrypted_api_key(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "unit-test-secret-material")
    created = client.post(
        "/api/v1/jobs",
        json={
            **VALID_JOB_PAYLOAD,
            "optimizer_strategy": "gpt",
            "simulator_backend": "mock",
            "max_iterations": 1,
            "openai": {"api_key": "sk-cancel-me"},
        },
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["data"]["id"]

    cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text

    from sqlalchemy import select

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        secret = db.scalars(
            select(models.JobSecret).where(models.JobSecret.job_id == job_id)
        ).one()
        assert secret.deleted_at is not None
        assert secret.encrypted_api_key == ""
        events = {
            event.event_type
            for event in db.scalars(
                select(models.JobEvent).where(models.JobEvent.job_id == job_id)
            )
        }
        assert "job_secrets_purged" in events


def test_gpt_job_secret_has_bounded_lifetime(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "unit-test-secret-material")
    monkeypatch.setenv("JOB_SECRET_TTL_SECONDS", "900")
    from app.config import get_settings

    get_settings.cache_clear()
    before = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/jobs",
        json={
            **VALID_JOB_PAYLOAD,
            "optimizer_strategy": "gpt",
            "simulator_backend": "mock",
            "openai": {"api_key": "sk-expiring"},
        },
    )
    assert created.status_code == 200, created.text

    from sqlalchemy import select

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        secret = db.scalars(
            select(models.JobSecret).where(
                models.JobSecret.job_id == created.json()["data"]["id"]
            )
        ).one()
        assert secret.expires_at is not None
        expires_at = secret.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        assert 895 <= (expires_at - before).total_seconds() <= 905


def test_gpt_job_rejects_blank_server_secret(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "   ")
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)

    response = client.post(
        "/api/v1/jobs",
        json={
            **VALID_JOB_PAYLOAD,
            "optimizer_strategy": "gpt",
            "simulator_backend": "mock",
            "openai": {"api_key": "sk-will-not-be-stored"},
        },
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "CONFIGURATION_ERROR"


def test_housekeeping_wipes_expired_secret_without_worker(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "unit-test-secret-material")
    created = client.post(
        "/api/v1/jobs",
        json={
            **VALID_JOB_PAYLOAD,
            "optimizer_strategy": "gpt",
            "simulator_backend": "mock",
            "openai": {"api_key": "sk-stuck-in-queue"},
        },
    )
    assert created.status_code == 200, created.text

    from datetime import timedelta

    from sqlalchemy import select

    from app import models
    from app.db import SessionLocal
    from app.services.jobs import purge_expired_job_secrets

    with SessionLocal() as db:
        secret = db.scalars(
            select(models.JobSecret).where(
                models.JobSecret.job_id == created.json()["data"]["id"]
            )
        ).one()
        secret.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

        assert purge_expired_job_secrets(db) == 1
        db.refresh(secret)
        assert secret.deleted_at is not None
        assert secret.encrypted_api_key == ""


def test_list_and_detail_do_not_add_job_id_alias(client: TestClient) -> None:
    """Only create/rerun advertise ``job_id``; list/detail stick to ``id``.

    This keeps the canonical ``id`` schema unchanged on the read endpoints
    while preserving the alias where the original spec promised it.
    """

    created = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    detail = client.get(f"/api/v1/jobs/{created['id']}").json()["data"]
    assert detail["id"] == created["id"]
    assert "job_id" not in detail
    listing = client.get("/api/v1/jobs").json()["data"]
    for row in listing["items"]:
        assert "id" in row
        assert "job_id" not in row


def test_create_job_rejects_invalid_altitude(client: TestClient) -> None:
    bad = {**VALID_JOB_PAYLOAD, "altitude_m": 25.0}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_INPUT"


def test_create_job_rejects_invalid_wind(client: TestClient) -> None:
    bad = {**VALID_JOB_PAYLOAD, "wind": {"north": 20, "east": 0, "south": 0, "west": 0}}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_create_job_rejects_invalid_track_type(client: TestClient) -> None:
    bad = {**VALID_JOB_PAYLOAD, "track_type": "zigzag"}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_create_job_rejects_custom_track_without_reference_track(client: TestClient) -> None:
    bad = {**HEURISTIC_JOB_PAYLOAD, "track_type": "custom", "reference_track": None}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_create_job_rejects_custom_track_with_short_reference_track(client: TestClient) -> None:
    bad = {
        **HEURISTIC_JOB_PAYLOAD,
        "track_type": "custom",
        "reference_track": [{"x": 0, "y": 0, "z": 3}],
    }
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_create_job_accepts_and_persists_custom_reference_track(client: TestClient) -> None:
    payload = {
        **HEURISTIC_JOB_PAYLOAD,
        "track_type": "custom",
        "reference_track": [{"x": 0, "y": 0, "z": 3}, {"x": 5, "y": 0}, {"x": 5, "y": 5, "z": 3}],
    }
    created = client.post("/api/v1/jobs", json=payload)
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["track_type"] == "custom"
    assert len(data["reference_track"]) == 3
    assert data["reference_track"][1]["z"] is None

    fetched = client.get(f"/api/v1/jobs/{data['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["reference_track"] == data["reference_track"]


def test_create_job_rejects_non_finite_custom_reference_track_values(client: TestClient) -> None:
    body = {
        **HEURISTIC_JOB_PAYLOAD,
        "track_type": "custom",
        # 1e309 decodes to +inf in Python's float parser.
        "reference_track": [{"x": 0, "y": 0, "z": 3}, {"x": 1e309, "y": 1}],
    }
    resp = client.post("/api/v1/jobs", content=json.dumps(body))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_create_job_accepts_advanced_scenario_config(client: TestClient) -> None:
    payload = {
        **HEURISTIC_JOB_PAYLOAD,
        "advanced_scenario_config": {
            "wind_gusts": {
                "enabled": True,
                "magnitude_mps": 2.5,
                "direction_deg": 45,
                "period_s": 8,
            },
            "sensor_degradation": {
                "gps_noise_m": 1.0,
                "baro_noise_m": 0.5,
                "imu_noise_scale": 1.2,
                "dropout_rate": 0.2,
            },
            "battery": {"initial_percent": 70, "voltage_sag": True},
            "obstacles": [{"type": "cylinder", "x": 1, "y": 2, "z": 0, "radius": 0.5, "height": 2}],
        },
    }
    resp = client.post("/api/v1/jobs", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["advanced_scenario_config"]["battery"]["initial_percent"] == 70


def test_create_job_rejects_invalid_advanced_dropout_rate(client: TestClient) -> None:
    payload = {
        **HEURISTIC_JOB_PAYLOAD,
        "advanced_scenario_config": {
            "sensor_degradation": {
                "gps_noise_m": 0.0,
                "baro_noise_m": 0.0,
                "imu_noise_scale": 1.0,
                "dropout_rate": 1.5,
            }
        },
    }
    resp = client.post("/api/v1/jobs", json=payload)
    assert resp.status_code == 422


def test_create_job_rejects_invalid_battery_percent(client: TestClient) -> None:
    payload = {
        **HEURISTIC_JOB_PAYLOAD,
        "advanced_scenario_config": {"battery": {"initial_percent": 120, "voltage_sag": False}},
    }
    resp = client.post("/api/v1/jobs", json=payload)
    assert resp.status_code == 422


@pytest.mark.parametrize("track_type", ["hover", "circle", "u_turn", "lemniscate"])
def test_non_custom_track_creation_unchanged(client: TestClient, track_type: str) -> None:
    payload = {**HEURISTIC_JOB_PAYLOAD, "track_type": track_type}
    resp = client.post("/api/v1/jobs", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["track_type"] == track_type
    assert body["reference_track"] is None


def test_hover_track_rejects_non_origin_or_moving_reference(client: TestClient) -> None:
    non_origin = {
        **HEURISTIC_JOB_PAYLOAD,
        "track_type": "hover",
        "start_point": {"x": 1, "y": 0},
    }
    response = client.post("/api/v1/jobs", json=non_origin)
    assert response.status_code == 422
    assert "start_point x=0 and y=0" in response.text

    moving_reference = {
        **HEURISTIC_JOB_PAYLOAD,
        "track_type": "hover",
        "reference_track": [
            {"x": 0, "y": 0, "z": 5},
            {"x": 0.5, "y": 0, "z": 5},
        ],
    }
    response = client.post("/api/v1/jobs", json=moving_reference)
    assert response.status_code == 422
    assert "hover reference_track must remain" in response.text


def test_create_job_rejects_invalid_sensor_noise(client: TestClient) -> None:
    bad = {**VALID_JOB_PAYLOAD, "sensor_noise_level": "extreme"}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422


def test_create_job_rejects_invalid_objective(client: TestClient) -> None:
    bad = {**VALID_JOB_PAYLOAD, "objective_profile": "fun"}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422


def test_create_job_rejects_unknown_fields(client: TestClient) -> None:
    bad = {**VALID_JOB_PAYLOAD, "rogue_field": 1}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422


# --- List / Detail ---------------------------------------------------------


def test_list_jobs_paginates(client: TestClient) -> None:
    for _ in range(3):
        r = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD)
        assert r.status_code == 200

    resp = client.get("/api/v1/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert len(data["items"]) == 3
    assert all(item["status"] == "QUEUED" for item in data["items"])


def test_get_job_detail(client: TestClient) -> None:
    created = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    resp = client.get(f"/api/v1/jobs/{created['id']}")
    assert resp.status_code == 200
    fetched = resp.json()["data"]
    assert fetched["id"] == created["id"]
    assert fetched["status"] == "QUEUED"


def test_get_job_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/jobs/job_does_not_exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "JOB_NOT_FOUND"


# --- Trials ----------------------------------------------------------------


def test_list_trials_for_job_is_empty(client: TestClient) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    resp = client.get(f"/api/v1/jobs/{job['id']}/trials")
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "data": [], "error": None}


def test_list_trials_keeps_array_contract_and_exposes_page_metadata(
    client: TestClient,
) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        candidate = models.CandidateParameterSet(
            job_id=job["id"],
            parameter_json={},
            label="pagination candidate",
        )
        db.add(candidate)
        db.flush()
        db.add_all(
            [
                models.Trial(
                    job_id=job["id"],
                    candidate_id=candidate.id,
                    seed=seed,
                    status="PENDING",
                )
                for seed in range(3)
            ]
        )
        db.commit()

    first = client.get(f"/api/v1/jobs/{job['id']}/trials?page=1&page_size=2")
    assert first.status_code == 200, first.text
    assert isinstance(first.json()["data"], list)
    assert len(first.json()["data"]) == 2
    assert first.headers["X-Total-Count"] == "3"
    assert first.headers["X-Page"] == "1"
    assert first.headers["X-Page-Size"] == "2"

    second = client.get(f"/api/v1/jobs/{job['id']}/trials?page=2&page_size=2")
    assert second.status_code == 200, second.text
    assert len(second.json()["data"]) == 1
    assert {
        item["id"] for item in first.json()["data"]
    }.isdisjoint({item["id"] for item in second.json()["data"]})


def test_trial_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/trials/tri_missing")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "TRIAL_NOT_FOUND"


# --- Rerun -----------------------------------------------------------------


def test_rerun_creates_new_job_preserving_original(client: TestClient) -> None:
    original = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    resp = client.post(f"/api/v1/jobs/{original['id']}/rerun")
    assert resp.status_code == 200
    new_job = resp.json()["data"]
    assert new_job["id"] != original["id"]
    # Rerun response also advertises the ``job_id`` alias (see
    # docs/04_API_SPEC.md §7.4).
    assert new_job["job_id"] == new_job["id"]
    assert new_job["status"] == "QUEUED"
    assert new_job["source_job_id"] == original["id"]
    assert new_job["track_type"] == original["track_type"]
    assert new_job["altitude_m"] == original["altitude_m"]

    # Original still exists unchanged.
    again = client.get(f"/api/v1/jobs/{original['id']}").json()["data"]
    assert again["id"] == original["id"]
    assert again["source_job_id"] is None


def test_rerun_truncates_max_length_display_name(client: TestClient) -> None:
    source = client.post(
        "/api/v1/jobs",
        json={**HEURISTIC_JOB_PAYLOAD, "display_name": "x" * 255},
    ).json()["data"]

    response = client.post(f"/api/v1/jobs/{source['id']}/rerun")

    assert response.status_code == 200, response.text
    display_name = response.json()["data"]["display_name"]
    assert len(display_name) == 255
    assert display_name.endswith(" (rerun)")


def test_rerun_preserves_custom_reference_track(client: TestClient) -> None:
    created = client.post(
        "/api/v1/jobs",
        json={
            **HEURISTIC_JOB_PAYLOAD,
            "track_type": "custom",
            "reference_track": [{"x": 0, "y": 0, "z": 3}, {"x": 4, "y": 2, "z": 3}],
        },
    )
    assert created.status_code == 200, created.text
    source = created.json()["data"]
    rerun = client.post(f"/api/v1/jobs/{source['id']}/rerun")
    assert rerun.status_code == 200, rerun.text
    child = rerun.json()["data"]
    assert child["track_type"] == "custom"
    assert child["reference_track"] == source["reference_track"]


def test_rerun_not_found(client: TestClient) -> None:
    resp = client.post("/api/v1/jobs/job_missing/rerun")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_compare_jobs_returns_completed_metrics(client: TestClient) -> None:
    from app import models
    from app.db import SessionLocal

    job_a = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]["id"]
    job_b = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]["id"]
    with SessionLocal() as db:
        for job_id in (job_a, job_b):
            job = db.get(models.Job, job_id)
            assert job is not None
            job.status = "COMPLETED"
            job.report = models.JobReport(
                job_id=job.id,
                report_status="READY",
                baseline_metric_json={"rmse": 1.0},
                optimized_metric_json={"rmse": 0.8},
            )
        db.commit()
    resp = client.post("/api/v1/jobs/compare", json={"job_ids": [job_a, job_b]})
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]["items"]
    assert len(items) == 2
    assert items[0]["optimized_metrics"]["rmse"] == 0.8


def test_compare_jobs_active_job_metrics_are_null(client: TestClient) -> None:
    job_a = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]["id"]
    job_b = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]["id"]
    resp = client.post("/api/v1/jobs/compare", json={"job_ids": [job_a, job_b]})
    assert resp.status_code == 200
    for item in resp.json()["data"]["items"]:
        assert item["baseline_metrics"] is None
        assert item["optimized_metrics"] is None


def test_compare_jobs_unknown_job_returns_404(client: TestClient) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]["id"]
    resp = client.post("/api/v1/jobs/compare", json={"job_ids": [job, "job_missing"]})
    assert resp.status_code == 404


def test_compare_jobs_csv_content_type(client: TestClient) -> None:
    job_a = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]["id"]
    job_b = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]["id"]
    resp = client.get(f"/api/v1/jobs/compare.csv?job_ids={job_a},{job_b}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")


def test_rerun_gpt_requires_fresh_openai_api_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "dev-unit-test-key")
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)
    payload = {
        **VALID_JOB_PAYLOAD,
        "optimizer_strategy": "gpt",
        "openai": {"api_key": "sk-source"},
    }
    original = client.post("/api/v1/jobs", json=payload).json()["data"]
    resp = client.post(f"/api/v1/jobs/{original['id']}/rerun")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_rerun_gpt_stays_gpt_with_new_openai_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "dev-unit-test-key")
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)
    payload = {
        **VALID_JOB_PAYLOAD,
        "optimizer_strategy": "gpt",
        "openai": {"api_key": "sk-source", "model": "gpt-4.1"},
    }
    original = client.post("/api/v1/jobs", json=payload).json()["data"]
    resp = client.post(
        f"/api/v1/jobs/{original['id']}/rerun",
        json={"openai": {"api_key": "sk-rerun"}},
    )
    assert resp.status_code == 200
    rerun = resp.json()["data"]
    assert rerun["optimizer_strategy"] == "gpt"


def test_rerun_gpt_accepts_provider_neutral_llm_configuration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "dev-unit-test-key")
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)
    payload = {
        **VALID_JOB_PAYLOAD,
        "optimizer_strategy": "gpt",
        "llm": {
            "provider": "deepseek",
            "api_key": "source-provider-key",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
    }
    original_resp = client.post("/api/v1/jobs", json=payload)
    assert original_resp.status_code == 200, original_resp.text
    original = original_resp.json()["data"]

    resp = client.post(
        f"/api/v1/jobs/{original['id']}/rerun",
        json={
            "llm": {
                "provider": "deepseek",
                "api_key": "fresh-provider-key",
                "model": "deepseek-reasoner",
                "base_url": "https://api.deepseek.com/v1",
            },
        },
    )

    assert resp.status_code == 200, resp.text
    rerun = resp.json()["data"]
    assert rerun["optimizer_strategy"] == "gpt"
    assert rerun["llm_provider"] == "deepseek"
    assert rerun["llm_base_url"] == "https://api.deepseek.com/v1"
    assert rerun["openai_model"] == "deepseek-reasoner"


# --- Cancel ----------------------------------------------------------------


def test_cancel_queued_job(client: TestClient) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    resp = client.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert resp.status_code == 200
    cancelled = resp.json()["data"]
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancelled_at"] is not None


def test_committed_finalizing_job_is_readable_listable_and_cancellable(
    client: TestClient,
) -> None:
    created = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        job = db.get(models.Job, created["id"])
        assert job is not None
        job.status = "FINALIZING"
        job.current_phase = "aggregating"
        db.commit()

    detail = client.get(f"/api/v1/jobs/{created['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["status"] == "FINALIZING"
    listing = client.get("/api/v1/jobs", params={"status": "FINALIZING"})
    assert listing.status_code == 200, listing.text
    assert [item["id"] for item in listing.json()["data"]["items"]] == [created["id"]]

    cancelled = client.post(f"/api/v1/jobs/{created['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "CANCELLED"


def test_cancel_twice_rejects(client: TestClient) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    assert client.post(f"/api/v1/jobs/{job['id']}/cancel").status_code == 200
    resp = client.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert resp.status_code == 409
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "JOB_ALREADY_CANCELLED"


def test_cancel_not_found(client: TestClient) -> None:
    resp = client.post("/api/v1/jobs/job_missing/cancel")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


# --- Report ----------------------------------------------------------------


def test_report_not_ready(client: TestClient) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    resp = client.get(f"/api/v1/jobs/{job['id']}/report")
    assert resp.status_code == 409
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "REPORT_NOT_READY"


def test_report_for_missing_job_returns_job_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/jobs/job_missing/report")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


def _seed_job_with_report(
    *,
    status: str,
    report_status: str,
    latest_error_code: str | None = None,
) -> str:
    """Seed a job row (optionally with a JobReport) via a direct DB session.

    Returns the job_id. Requires that the shared test ``client`` fixture has
    already initialised the database.
    """

    from app import db as db_module
    from app import models

    baseline = {
        "rmse": 1.2, "max_error": 2.0, "overshoot_count": 3,
        "completion_time": 9.0, "score": 4.2,
    }
    optimized = {
        "rmse": 0.9, "max_error": 1.5, "overshoot_count": 2,
        "completion_time": 8.0, "score": 3.0,
    }
    comparison = [
        {"metric": "rmse", "label": "RMSE", "baseline": 1.2,
         "optimized": 0.9, "lower_is_better": True, "unit": "m"}
    ]
    best_params = {
        "kp_xy": 1.1, "kd_xy": 0.21, "ki_xy": 0.05,
        "vel_limit": 5.0, "accel_limit": 4.0, "disturbance_rejection": 0.5,
    }

    with db_module.SessionLocal() as db:
        job = models.Job(
            user_id=None,
            track_type="circle",
            start_point_x=0.0,
            start_point_y=0.0,
            altitude_m=3.0,
            wind_north=0.0, wind_east=0.0, wind_south=0.0, wind_west=0.0,
            sensor_noise_level="medium",
            objective_profile="robust",
            status=status,
            current_phase="failed" if status == "FAILED" else "completed",
            latest_error_code=latest_error_code,
            latest_error_message="seeded",
        )
        db.add(job)
        db.flush()
        db.add(
            models.JobReport(
                job_id=job.id,
                best_candidate_id="cand_seed",
                summary_text="best-so-far seeded",
                baseline_metric_json=baseline,
                optimized_metric_json=optimized,
                comparison_metric_json=comparison,
                best_parameter_json=best_params,
                report_status=report_status,
            )
        )
        db.commit()
        return str(job.id)


def test_failed_job_with_ready_report_returns_report(client: TestClient) -> None:
    """Phase 8: a FAILED GPT job with a best-so-far READY report returns it."""

    job_id = _seed_job_with_report(
        status="FAILED",
        report_status="READY",
        latest_error_code="MAX_ITERATIONS_REACHED",
    )
    resp = client.get(f"/api/v1/jobs/{job_id}/report")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["best_candidate_id"] == "cand_seed"
    assert body["data"]["summary_text"] == "best-so-far seeded"
    assert body["data"]["optimized_metrics"]["rmse"] == 0.9


def test_failed_job_without_ready_report_still_returns_job_failed(
    client: TestClient,
) -> None:
    job_id = _seed_job_with_report(
        status="FAILED",
        report_status="FAILED",
        latest_error_code="ALL_TRIALS_FAILED",
    )
    resp = client.get(f"/api/v1/jobs/{job_id}/report")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "JOB_FAILED"
    assert body["error"]["details"]["failure_code"] == "ALL_TRIALS_FAILED"


# --- Artifacts -------------------------------------------------------------


def test_artifacts_empty(client: TestClient) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    resp = client.get(f"/api/v1/jobs/{job['id']}/artifacts")
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "data": [], "error": None}


def test_artifacts_includes_trial_scoped_artifacts(client: TestClient) -> None:
    """Phase 8: trial-level artifacts (e.g. real_cli trajectory plots) are
    returned from the job artifacts endpoint alongside job-level artifacts."""

    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    job_id = job["id"]

    from app import db as db_module
    from app import models

    with db_module.SessionLocal() as db:
        # Seed a trial row bound to this job.
        db.add(
            models.CandidateParameterSet(
                id="cand_seed",
                job_id=job_id,
                parameter_json={},
            )
        )
        db.flush()
        trial = models.Trial(
            job_id=job_id,
            candidate_id="cand_seed",
            seed=7,
            scenario_type="nominal",
            status="COMPLETED",
            attempt_count=1,
        )
        db.add(trial)
        db.flush()
        # Trial-scoped artifact (what real_cli writes).
        db.add(
            models.Artifact(
                owner_type="trial",
                owner_id=trial.id,
                artifact_type="trajectory_plot",
                display_name="Trajectory",
                storage_path="/tmp/trajectory.png",
                mime_type="image/png",
                file_size_bytes=1234,
            )
        )
        # Job-scoped artifact (what the report writer produces).
        db.add(
            models.Artifact(
                owner_type="job",
                owner_id=job_id,
                artifact_type="report_summary",
                display_name="Report",
                storage_path="/tmp/report.json",
                mime_type="application/json",
                file_size_bytes=56,
            )
        )
        db.commit()

    resp = client.get(f"/api/v1/jobs/{job_id}/artifacts")
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]
    owner_types = {a["owner_type"] for a in items}
    kinds = {a["artifact_type"] for a in items}
    assert "trial" in owner_types and "job" in owner_types
    assert "trajectory_plot" in kinds and "report_summary" in kinds

def test_delete_completed_job_and_artifacts(client: TestClient, tmp_path: Path) -> None:
    from app import models
    from app.db import SessionLocal
    from app.storage.integrity import bind_artifact_integrity

    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    other = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    with SessionLocal() as db:
        j = db.get(models.Job, job["id"])
        assert j is not None
        j.status = "COMPLETED"
        cand = models.CandidateParameterSet(job_id=j.id, parameter_json={})
        db.add(cand)
        db.flush()
        trial = models.Trial(job_id=j.id, candidate_id=cand.id, status="COMPLETED")
        db.add(trial)
        db.flush()
        art_file = tmp_path / "mock_artifacts" / "artifact.bin"
        art_file.parent.mkdir(parents=True, exist_ok=True)
        art_file.write_bytes(b"x")
        sealed_file = art_file.with_name("sealed.bin")
        sealed_file.write_bytes(b"sealed")
        sealed_artifact = models.Artifact(
            owner_type="job",
            owner_id=j.id,
            artifact_type="report_json",
            storage_path=str(sealed_file),
        )
        db.add(sealed_artifact)
        db.flush()
        bind_artifact_integrity(
            db,
            artifact=sealed_artifact,
            content=sealed_file,
        )
        db.add(
            models.Artifact(
                owner_type="job",
                owner_id=j.id,
                artifact_type="log",
                storage_path=str(art_file),
            )
        )
        db.add(
            models.Artifact(
                owner_type="trial",
                owner_id=trial.id,
                artifact_type="log",
                storage_path=str(art_file),
            )
        )
        db.add(
            models.Artifact(
                owner_type="job",
                owner_id=other["id"],
                artifact_type="log",
                storage_path="mock://keep",
            )
        )
        db.commit()
    resp = client.delete(f"/api/v1/jobs/{job['id']}")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"id": job["id"], "deleted": True}
    assert client.get(f"/api/v1/jobs/{job['id']}").status_code == 404
    ids = [x['id'] for x in client.get('/api/v1/jobs').json()['data']['items']]
    assert job['id'] not in ids and other['id'] in ids
    with SessionLocal() as db:
        remaining = list(db.query(models.Artifact).all())
        assert all(a.owner_id != job['id'] for a in remaining)
        assert any(a.owner_id == other['id'] for a in remaining)
        assert not art_file.exists()
        assert not sealed_file.exists()
        assert (
            db.query(models.ArtifactDigestReceipt).count() == 0
        )
        assert (
            db.query(models.ArtifactDigestDeleteAuthorization).count()
            == 0
        )


def test_delete_active_job_conflict(client: TestClient) -> None:
    job = client.post('/api/v1/jobs', json=HEURISTIC_JOB_PAYLOAD).json()['data']
    resp = client.delete(f"/api/v1/jobs/{job['id']}")
    assert resp.status_code == 409
    assert resp.json()['error']['code'] == 'JOB_NOT_DELETABLE'


def test_delete_source_job_nulls_child_source_id(client: TestClient) -> None:
    from app import models
    from app.db import SessionLocal
    parent = client.post('/api/v1/jobs', json=HEURISTIC_JOB_PAYLOAD).json()['data']
    child = client.post(f"/api/v1/jobs/{parent['id']}/rerun").json()['data']
    with SessionLocal() as db:
        p = db.get(models.Job, parent['id'])
        assert p is not None
        p.status = 'COMPLETED'
        db.commit()
    assert client.delete(f"/api/v1/jobs/{parent['id']}").status_code == 200
    child_detail = client.get(f"/api/v1/jobs/{child['id']}")
    assert child_detail.status_code == 200
    assert child_detail.json()['data']['source_job_id'] is None


def test_delete_job_ignores_missing_artifact_file(client: TestClient, tmp_path: Path) -> None:
    from app import models
    from app.db import SessionLocal

    job = client.post('/api/v1/jobs', json=HEURISTIC_JOB_PAYLOAD).json()['data']
    missing_path = tmp_path / 'artifacts' / 'missing.bin'
    with SessionLocal() as db:
        j = db.get(models.Job, job['id'])
        assert j is not None
        j.status = 'COMPLETED'
        db.add(
            models.Artifact(
                owner_type="job",
                owner_id=j.id,
                artifact_type="log",
                storage_path=str(missing_path),
            )
        )
        db.commit()

    resp = client.delete(f"/api/v1/jobs/{job['id']}")
    assert resp.status_code == 200, resp.text


def test_delete_job_never_deletes_artifact_outside_allowed_roots(
    client: TestClient, tmp_path: Path
) -> None:
    from app import models
    from app.db import SessionLocal

    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    outside_path = tmp_path / "outside-artifact.bin"
    outside_path.write_bytes(b"must remain")
    with SessionLocal() as db:
        stored_job = db.get(models.Job, job["id"])
        assert stored_job is not None
        stored_job.status = "COMPLETED"
        db.add(
            models.Artifact(
                owner_type="job",
                owner_id=stored_job.id,
                artifact_type="log",
                storage_path=str(outside_path),
            )
        )
        db.commit()

    response = client.delete(f"/api/v1/jobs/{job['id']}")
    assert response.status_code == 200, response.text
    assert outside_path.read_bytes() == b"must remain"
    with SessionLocal() as db:
        assert db.get(models.Job, job['id']) is None
        assert db.query(models.Artifact).filter(models.Artifact.owner_id == job['id']).count() == 0
