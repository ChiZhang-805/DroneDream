from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.export_test_run_receipt import build_test_run_receipt

_SOURCE_COMMIT = "a" * 40
_BASE_COMMIT = "b" * 40
_TIMESTAMP = "2026-07-28T00:00:00Z"
_LOG = Path(__file__).resolve().parent / "fixtures" / "test_run_receipt_v1.log"


def _build_receipt() -> dict[str, object]:
    return build_test_run_receipt(
        source_commit=_SOURCE_COMMIT,
        base_commit=_BASE_COMMIT,
        generated_at=_TIMESTAMP,
        platform="test-platform",
        python_version="3.13.0",
        pytest_version="9.1.0",
        full_suite_log_path=_LOG,
        full_suite_command="python -m pytest -q",
        full_suite_working_directory="backend",
        full_suite_started_at=_TIMESTAMP,
        full_suite_finished_at="2026-07-28T00:12:39Z",
        full_suite_duration_seconds=759.17,
        full_suite_passed=1139,
        focused_log_path=_LOG,
        focused_command="python -m pytest -q focused",
        focused_working_directory="backend",
        focused_started_at="2026-07-28T00:13:00Z",
        focused_finished_at="2026-07-28T00:13:01Z",
        focused_duration_seconds=1.0,
        focused_passed=1,
        bridge_reason="Fixture verifies deterministic receipt binding.",
    )


def test_test_run_receipt_is_deterministic_and_content_addressed() -> None:
    first = _build_receipt()
    second = _build_receipt()

    assert first == second
    assert first["schema_version"] == "dronedream.test-run-receipt.v1"
    assert first["source_commit"] == _SOURCE_COMMIT
    assert first["full_suite"]["result"] == {
        "status": "passed",
        "passed": 1139,
        "failed": 0,
    }
    assert first["full_suite"]["log"]["sha256"] == hashlib.sha256(_LOG.read_bytes()).hexdigest()
    unsigned = dict(first)
    receipt_sha256 = unsigned.pop("receipt_sha256")
    assert (
        receipt_sha256
        == hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
    )


def test_test_run_receipt_rejects_noncanonical_commit() -> None:
    with pytest.raises(ValueError, match="full lowercase Git SHA"):
        build_test_run_receipt(
            source_commit="ABC",
            base_commit=_BASE_COMMIT,
            generated_at=_TIMESTAMP,
            platform="test-platform",
            python_version="3.13.0",
            pytest_version="9.1.0",
            full_suite_log_path=_LOG,
            full_suite_command="python -m pytest -q",
            full_suite_working_directory="backend",
            full_suite_started_at=_TIMESTAMP,
            full_suite_finished_at="2026-07-28T00:12:39Z",
            full_suite_duration_seconds=759.17,
            full_suite_passed=1139,
            focused_log_path=_LOG,
            focused_command="python -m pytest -q focused",
            focused_working_directory="backend",
            focused_started_at="2026-07-28T00:13:00Z",
            focused_finished_at="2026-07-28T00:13:01Z",
            focused_duration_seconds=1.0,
            focused_passed=1,
            bridge_reason="Fixture verifies deterministic receipt binding.",
        )
