"""User-owned, minimal preference and memory lifecycle tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_experience_preferences_are_opt_in_bounded_and_deletable(client) -> None:
    from app import models
    from app.db import SessionLocal

    initial = client.get("/api/v1/preferences/experience")
    assert initial.status_code == 200
    assert initial.json()["data"] == {
        "schema_version": "1.0",
        "saved": False,
        "memory_enabled": False,
        "locale": None,
        "default_template_key": None,
        "default_track_type": None,
        "default_altitude_m": None,
        "retention_days": 90,
        "stored_content": (
            "allowlisted_preferences_and_verified_structured_job_outcomes_only"
        ),
        "updated_at": None,
    }

    saved = client.put(
        "/api/v1/preferences/experience",
        json={
            "memory_enabled": True,
            "locale": "zh-CN",
            "default_template_key": "hover-basics@1",
            "default_track_type": "hover",
            "default_altitude_m": 3.0,
        },
    )
    assert saved.status_code == 200
    saved_data = saved.json()["data"]
    assert saved_data["saved"] is True
    assert saved_data["memory_enabled"] is True
    assert saved_data["locale"] == "zh-CN"
    assert saved_data["default_template_key"] == "hover-basics@1"
    assert saved_data["default_track_type"] == "hover"
    assert saved_data["default_altitude_m"] == 3.0
    assert saved_data["deleted_memory_count"] == 0
    assert "user_id" not in saved_data

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        preferences = db.query(models.UserExperiencePreferences).one()
        source = models.Job(
            id="job_preferences_delete_source",
            user_id=preferences.user_id,
            track_type="hover",
            altitude_m=3.0,
            sensor_noise_level="low",
            objective_profile="stable",
            status="COMPLETED",
            optimizer_strategy="llm_harness",
            current_generation=1,
            max_iterations=3,
            max_total_trials=30,
        )
        db.add(source)
        db.flush()
        db.add(
            models.HarnessExperienceMemory(
                user_id=preferences.user_id,
                source_job_id=source.id,
                source_generation=1,
                memory_schema_version="1.0",
                source_evidence_schema_version="2.9",
                source_prompt_template_version="1.7",
                source_tool_registry_version="1.1",
                source_eligibility_policy_version="1.4",
                task_family_sha256="a" * 64,
                scenario_profile_json={},
                tool_id="turbo",
                decision_source="model",
                plan_phase="refinement",
                batch_policy="balanced",
                dispatched_candidates=2,
                planned_candidates=2,
                observed_outcome_json={},
                source_receipt_sha256="b" * 64,
                created_at=now,
                expires_at=now + timedelta(days=90),
            )
        )
        db.commit()

    disabled = client.put(
        "/api/v1/preferences/experience",
        json={"memory_enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["data"]["memory_enabled"] is False
    assert disabled.json()["data"]["deleted_memory_count"] == 1
    with SessionLocal() as db:
        assert db.query(models.HarnessExperienceMemory).count() == 0

    erased = client.delete("/api/v1/preferences/experience")
    assert erased.status_code == 200
    assert erased.json()["data"] == {
        "deleted_preferences": True,
        "deleted_memory_count": 0,
        "memory_enabled": False,
    }
    with SessionLocal() as db:
        assert db.query(models.UserExperiencePreferences).count() == 0
        assert db.query(models.HarnessExperienceMemory).count() == 0

    reset = client.get("/api/v1/preferences/experience")
    assert reset.status_code == 200
    assert reset.json()["data"]["saved"] is False
    assert reset.json()["data"]["memory_enabled"] is False


def test_experience_preferences_reject_unknown_or_unbounded_values(client) -> None:
    assert client.put(
        "/api/v1/preferences/experience",
        json={},
    ).status_code == 422
    assert client.put(
        "/api/v1/preferences/experience",
        json={"raw_chat_history": "never store this"},
    ).status_code == 422
    assert client.put(
        "/api/v1/preferences/experience",
        json={"default_template_key": "unreviewed@999"},
    ).status_code == 422
    assert client.put(
        "/api/v1/preferences/experience",
        json={"default_altitude_m": 200.0},
    ).status_code == 422
    assert client.put(
        "/api/v1/preferences/experience",
        json={"memory_enabled": None},
    ).status_code == 422
