"""Canonical timestamp helpers for durable evidence and artifacts."""

from __future__ import annotations

from datetime import datetime, timezone


def canonical_utc_iso(value: datetime | None) -> str | None:
    """Serialize a timestamp identically before and after a DB round trip.

    SQLite does not preserve timezone information for ``DateTime`` columns.
    DroneDream persists UTC timestamps, so a naive value loaded from SQLite is
    interpreted as UTC before serialization.  Aware values are normalized to
    UTC.  This keeps content-addressed reports stable across process restarts.
    """

    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


__all__ = ["canonical_utc_iso"]
