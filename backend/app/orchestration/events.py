"""Helpers for writing JobEvent audit rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app import models


def record_event(
    db: Session,
    job_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> models.JobEvent:
    """Append a JobEvent row. Caller controls commit lifecycle."""

    event = models.JobEvent(job_id=job_id, event_type=event_type, payload_json=payload)
    db.add(event)
    return event
