"""Helpers for writing JobEvent audit rows."""

from __future__ import annotations

import json
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

    if not isinstance(job_id, str) or not job_id.strip() or len(job_id) > 64:
        raise ValueError("job_id must be a non-empty string of at most 64 characters")
    if (
        not isinstance(event_type, str)
        or not event_type.strip()
        or len(event_type) > 64
    ):
        raise ValueError(
            "event_type must be a non-empty string of at most 64 characters"
        )
    if payload is not None:
        if not isinstance(payload, dict):
            raise ValueError("event payload must be a JSON object")
        try:
            encoded = json.dumps(
                payload,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("event payload must contain finite JSON values") from exc
        if len(encoded) > 262_144:
            raise ValueError("event payload exceeds the 256 KiB safety limit")
    event = models.JobEvent(job_id=job_id, event_type=event_type, payload_json=payload)
    db.add(event)
    return event
