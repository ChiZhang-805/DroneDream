"""Boundary tests for bounded PX4/simulator stream capture."""

from __future__ import annotations

import hashlib
import json

from app.simulator.artifact_schema import validate_log_capture_receipt_payload
from app.simulator.bounded_log_capture import (
    LOG_CAPTURE_SCHEMA_VERSION,
    StreamingBoundedLogCapture,
    append_bounded_log_text,
    receipt_path_for,
)


def _receipt(path):
    return json.loads(receipt_path_for(path).read_text(encoding="utf-8"))


def test_small_normal_log_preserves_exact_utf8_bytes(tmp_path) -> None:
    path = tmp_path / "stdout.log"
    original = "PX4 ready\r\n位置稳定\n".encode()
    capture = StreamingBoundedLogCapture(
        path,
        cap_bytes=4096,
        stream_name="simulator_stdout",
    )

    capture.feed_bytes(original)
    receipt = capture.close()

    assert path.read_bytes() == original
    assert receipt["raw_observed_bytes"] == len(original)
    assert receipt["normalized_observed_bytes"] == len(original)
    assert receipt["retained_bytes"] == len(original)
    assert receipt["truncated"] is False
    assert receipt["retained_sha256"] == hashlib.sha256(original).hexdigest()


def test_ansi_sequences_split_across_chunks_are_removed(tmp_path) -> None:
    path = tmp_path / "stdout.log"
    capture = StreamingBoundedLogCapture(
        path,
        cap_bytes=4096,
        stream_name="simulator_stdout",
    )

    capture.feed_bytes(b"before \x1b[")
    capture.feed_bytes(b"31mRED\x1b[")
    capture.feed_bytes(b"0m after\n")
    receipt = capture.close()

    assert path.read_bytes() == b"before RED after\n"
    assert receipt["ansi_sequence_count"] == 2
    assert receipt["ansi_control_bytes_removed"] == len(b"\x1b[31m\x1b[0m")


def test_utf8_codepoint_split_across_chunks_is_not_corrupted(tmp_path) -> None:
    path = tmp_path / "stderr.log"
    encoded = "起飞检查通过\n".encode()
    capture = StreamingBoundedLogCapture(
        path,
        cap_bytes=4096,
        stream_name="simulator_stderr",
    )

    for boundary in (encoded[:1], encoded[1:4], encoded[4:7], encoded[7:]):
        capture.feed_bytes(boundary)
    receipt = capture.close()

    assert path.read_bytes() == encoded
    assert receipt["utf8_replacement_count"] == 0


def test_no_newline_prompt_redraw_storm_collapses_but_real_error_survives(tmp_path) -> None:
    path = tmp_path / "stdout.log"
    capture = StreamingBoundedLogCapture(
        path,
        cap_bytes=4096,
        stream_name="simulator_stdout",
    )

    redraw = b"\x1b[2K\rpxh> "
    for offset in range(0, len(redraw) * 100, 7):
        storm = redraw * 100
        capture.feed_bytes(storm[offset : offset + 7])
    capture.feed_bytes(b"\rERROR actuator link failed\n")
    receipt = capture.close()

    retained = path.read_text(encoding="utf-8")
    assert "pxh>" not in retained
    assert "ERROR actuator link failed" in retained
    assert receipt["prompt_redraws_collapsed"] == 100
    assert receipt["ansi_sequence_count"] == 100
    assert any("ERROR actuator link failed" in item["line"] for item in receipt["critical_lines"])


def test_cap_receipt_counts_dropped_bytes_and_keeps_post_cap_critical_line(tmp_path) -> None:
    path = tmp_path / "stdout.log"
    capture = StreamingBoundedLogCapture(
        path,
        cap_bytes=32,
        stream_name="simulator_stdout",
    )

    payload = b"A" * 80 + b"\nFATAL PX4 exited with code 9\n"
    capture.feed_bytes(payload)
    receipt = capture.close()
    retained = path.read_bytes()

    assert len(retained) == 32
    assert receipt["schema_version"] == LOG_CAPTURE_SCHEMA_VERSION
    assert receipt["raw_observed_bytes"] == len(payload)
    assert receipt["normalized_observed_bytes"] == len(payload)
    assert receipt["retained_bytes"] == 32
    assert receipt["dropped_bytes_due_to_cap"] == len(payload) - 32
    assert receipt["truncated"] is True
    assert receipt["truncation_reason"] == "normalized_output_exceeded_cap"
    assert receipt["retained_sha256"] == hashlib.sha256(retained).hexdigest()
    assert any("FATAL PX4 exited with code 9" in item["line"] for item in receipt["critical_lines"])


def test_bounded_append_preserves_cumulative_receipt_and_hash(tmp_path) -> None:
    path = tmp_path / "runner.log"

    append_bounded_log_text(path, "started\n", cap_bytes=64, stream_name="runner_log")
    final = append_bounded_log_text(
        path,
        "exit code 0\n",
        cap_bytes=64,
        stream_name="runner_log",
    )

    expected = b"started\nexit code 0\n"
    assert path.read_bytes() == expected
    assert final["raw_observed_bytes"] == len(expected)
    assert final["retained_sha256"] == hashlib.sha256(expected).hexdigest()
    assert len(final["critical_lines"]) == 2
    assert _receipt(path) == final
    assert validate_log_capture_receipt_payload(final) == []


def test_log_capture_receipt_validator_rejects_inconsistent_truncation(tmp_path) -> None:
    path = tmp_path / "stdout.log"
    capture = StreamingBoundedLogCapture(
        path,
        cap_bytes=16,
        stream_name="simulator_stdout",
    )
    capture.feed_bytes(b"output")
    receipt = capture.close()
    receipt["truncated"] = True

    errors = validate_log_capture_receipt_payload(receipt)

    assert "truncated must match dropped_bytes_due_to_cap" in errors
