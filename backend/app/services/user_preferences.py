"""Minimal user preferences with explicit, fail-closed memory consent."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models, schemas
from app.model_harness.domains import validate_long_term_memory_payload
from app.orchestration.experience_memory import (
    HARNESS_EXPERIENCE_RETENTION_DAYS,
    delete_cross_job_experiences,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_user_experience_preferences(
    db: Session,
    *,
    user_id: str,
) -> models.UserExperiencePreferences | None:
    return db.get(models.UserExperiencePreferences, user_id)


def cross_job_memory_enabled(db: Session, *, user_id: str) -> bool:
    preferences = get_user_experience_preferences(db, user_id=user_id)
    return bool(preferences is not None and preferences.memory_enabled)


def account_shared_model_context(
    preferences: models.UserExperiencePreferences | None,
) -> dict[str, object] | None:
    """Return only allowlisted account defaults for bounded model context."""

    if preferences is None or not preferences.memory_enabled:
        return None
    context: dict[str, object] = {
        "memory_domain": "account.shared",
        "source_kind": "account_defaults",
        "long_term_memory_authority": "advisory_only",
        "locale": preferences.locale,
        "default_template_key": preferences.default_template_key,
        "default_track_type": preferences.default_track_type,
        "default_altitude_m": preferences.default_altitude_m,
    }
    validate_long_term_memory_payload(context)
    return context


def serialize_user_experience_preferences(
    preferences: models.UserExperiencePreferences | None,
) -> schemas.UserExperiencePreferences:
    return schemas.UserExperiencePreferences.model_validate(
        {
            "saved": preferences is not None,
            "memory_enabled": bool(preferences and preferences.memory_enabled),
            "locale": preferences.locale if preferences else None,
            "default_template_key": (preferences.default_template_key if preferences else None),
            "default_track_type": (preferences.default_track_type if preferences else None),
            "default_altitude_m": (preferences.default_altitude_m if preferences else None),
            "retention_days": HARNESS_EXPERIENCE_RETENTION_DAYS,
            "updated_at": preferences.updated_at if preferences else None,
        }
    )


def update_user_experience_preferences(
    db: Session,
    *,
    user_id: str,
    request: schemas.UserExperiencePreferencesUpdate,
) -> tuple[models.UserExperiencePreferences, int]:
    preferences = get_user_experience_preferences(db, user_id=user_id)
    if preferences is None:
        preferences = models.UserExperiencePreferences(user_id=user_id)
        db.add(preferences)
    fields = request.model_fields_set
    for field_name in (
        "memory_enabled",
        "locale",
        "default_template_key",
        "default_track_type",
        "default_altitude_m",
    ):
        if field_name in fields:
            setattr(preferences, field_name, getattr(request, field_name))
    preferences.updated_at = _utcnow()
    deleted = 0
    if "memory_enabled" in fields and request.memory_enabled is False:
        deleted = delete_cross_job_experiences(db, user_id=user_id)
    db.flush()
    return preferences, deleted


def delete_user_experience_preferences(
    db: Session,
    *,
    user_id: str,
) -> tuple[bool, int]:
    preferences = get_user_experience_preferences(db, user_id=user_id)
    deleted_memory_count = delete_cross_job_experiences(db, user_id=user_id)
    if preferences is not None:
        db.delete(preferences)
        db.flush()
    return preferences is not None, deleted_memory_count


__all__ = [
    "account_shared_model_context",
    "cross_job_memory_enabled",
    "delete_user_experience_preferences",
    "get_user_experience_preferences",
    "serialize_user_experience_preferences",
    "update_user_experience_preferences",
]
