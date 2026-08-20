"""Durable bounded context storage; model-side response IDs are not the sole memory."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .contracts import ConversationEvent, ConversationWindow
from .lifecycle import MissionLifecycleStore


class ContextStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
              conversation_id TEXT NOT NULL,
              sequence INTEGER NOT NULL,
              event_json TEXT NOT NULL,
              PRIMARY KEY (conversation_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS summaries (
              conversation_id TEXT PRIMARY KEY,
              summary TEXT NOT NULL,
              through_sequence INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_context (
              conversation_id TEXT NOT NULL,
              provider TEXT NOT NULL,
              response_id TEXT NOT NULL,
              PRIMARY KEY (conversation_id, provider)
            );
            """
        )
        self._connection.commit()
        self.lifecycle = MissionLifecycleStore(self._connection)

    def close(self) -> None:
        self._connection.close()

    def append(
        self,
        conversation_id: str,
        *,
        role: str,
        event_type: str,
        payload: dict[str, object],
    ) -> ConversationEvent:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        sequence = int(row[0])
        event = ConversationEvent(
            event_id=f"event-{uuid4().hex[:24]}",
            conversation_id=conversation_id,
            sequence=sequence,
            role=role,
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(UTC),
        )
        self._connection.execute(
            "INSERT INTO events(conversation_id, sequence, event_json) VALUES (?, ?, ?)",
            (conversation_id, sequence, event.model_dump_json()),
        )
        self._connection.commit()
        return event

    def set_summary(self, conversation_id: str, summary: str, through_sequence: int) -> None:
        if through_sequence < 1:
            raise ValueError("through_sequence must be positive")
        self._connection.execute(
            """INSERT INTO summaries(conversation_id, summary, through_sequence)
               VALUES (?, ?, ?)
               ON CONFLICT(conversation_id) DO UPDATE SET
                 summary=excluded.summary, through_sequence=excluded.through_sequence""",
            (conversation_id, summary, through_sequence),
        )
        self._connection.commit()

    def set_response_id(self, conversation_id: str, provider: str, response_id: str) -> None:
        self._connection.execute(
            """INSERT INTO provider_context(conversation_id, provider, response_id)
               VALUES (?, ?, ?)
               ON CONFLICT(conversation_id, provider) DO UPDATE SET
                 response_id=excluded.response_id""",
            (conversation_id, provider, response_id),
        )
        self._connection.commit()

    def window(self, conversation_id: str, *, max_recent_events: int = 24) -> ConversationWindow:
        if not 1 <= max_recent_events <= 200:
            raise ValueError("max_recent_events must be between 1 and 200")
        summary_row = self._connection.execute(
            "SELECT summary, through_sequence FROM summaries WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        through_sequence = int(summary_row[1]) if summary_row else 0
        rows = self._connection.execute(
            """SELECT event_json FROM events
               WHERE conversation_id = ? AND sequence > ?
               ORDER BY sequence DESC LIMIT ?""",
            (conversation_id, through_sequence, max_recent_events),
        ).fetchall()
        events = [ConversationEvent.model_validate(json.loads(row[0])) for row in reversed(rows)]
        response_rows = self._connection.execute(
            "SELECT provider, response_id FROM provider_context WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchall()
        return ConversationWindow(
            conversation_id=conversation_id,
            summary=summary_row[0] if summary_row else None,
            recent_events=events,
            previous_response_ids={str(provider): str(value) for provider, value in response_rows},
        )

    def apply_retention(self, conversation_id: str, *, maximum_events: int) -> int:
        if not 24 <= maximum_events <= 100_000:
            raise ValueError("maximum_events must be between 24 and 100000")
        threshold_row = self._connection.execute(
            """SELECT sequence FROM events WHERE conversation_id = ?
               ORDER BY sequence DESC LIMIT 1 OFFSET ?""",
            (conversation_id, maximum_events - 1),
        ).fetchone()
        if threshold_row is None:
            return 0
        threshold = int(threshold_row[0])
        cursor = self._connection.execute(
            "DELETE FROM events WHERE conversation_id = ? AND sequence < ?",
            (conversation_id, threshold),
        )
        self._connection.commit()
        return int(cursor.rowcount)
