from __future__ import annotations

from drone_dream_worker.config import database_log_label


def test_database_log_label_hides_password() -> None:
    label = database_log_label(
        "postgresql+psycopg://worker:super-secret@db.internal:5432/dronedream"
    )

    assert "super-secret" not in label
    assert "***" in label
    assert "db.internal" in label


def test_database_log_label_does_not_echo_invalid_input() -> None:
    secret = "not a valid URL with embedded-secret"

    assert database_log_label(secret) == "<invalid database URL>"
