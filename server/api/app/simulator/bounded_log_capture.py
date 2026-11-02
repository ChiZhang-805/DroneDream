"""Bounded, evidence-preserving capture for simulator process streams.

The PX4 shell is interactive even in headless SITL.  It can redraw ``pxh>``
with carriage returns and ANSI erase commands indefinitely.  Persisting those
terminal frames byte-for-byte produces multi-gigabyte files with almost no
diagnostic value.  This module normalizes the stream *before* it reaches disk,
while retaining an auditable receipt for every removed or truncated byte.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import re
from contextlib import suppress
from pathlib import Path
from threading import RLock
from typing import Any, BinaryIO

LOG_CAPTURE_SCHEMA_VERSION = "dronedream.log_capture_receipt.v1"

DEFAULT_SIMULATOR_STDOUT_CAP_BYTES = 16 * 1024 * 1024
DEFAULT_SIMULATOR_STDERR_CAP_BYTES = 8 * 1024 * 1024
DEFAULT_AUXILIARY_LOG_CAP_BYTES = 2 * 1024 * 1024

_READ_CHUNK_BYTES = 64 * 1024
_MAX_CRITICAL_LINES = 32
_MAX_CRITICAL_LINE_CHARS = 1024
_MAX_PENDING_LINE_CHARS = 4096
_MAX_RECEIPT_BYTES = 256 * 1024
_PROMPT_REDRAW = re.compile(r"^\s*pxh>\s*$")
_CRITICAL_LINE = re.compile(
    r"(?i)(?:\berror\b|\bfail(?:ed|ure)?\b|\bfatal\b|\bcrash(?:ed)?\b|"
    r"\btimeout\b|timed out|\bexception\b|\btraceback\b|"
    r"\bexit(?:ed|\s+code)?\b|\bstart(?:ing|ed)?\b|\bready\b|"
    r"\blaunch(?:ing|ed|\s+command)?\b|\bterminat(?:e|ed|ing)\b|\bkilled\b)"
)


def receipt_path_for(log_path: Path) -> Path:
    """Return the deterministic sidecar receipt path for a captured log."""

    return log_path.with_name(f"{log_path.name}.capture.json")


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        with suppress(OSError):
            temporary.unlink()


def _utf8_prefix_within_limit(text: str, limit: int) -> bytes:
    if limit <= 0 or not text:
        return b""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return encoded
    low = 0
    high = len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if len(text[:middle].encode("utf-8")) <= limit:
            low = middle
        else:
            high = middle - 1
    return text[:low].encode("utf-8")


class StreamingBoundedLogCapture:
    """Normalize and retain one process stream without unbounded disk growth."""

    def __init__(
        self,
        path: Path,
        *,
        cap_bytes: int,
        stream_name: str,
        append: bool = False,
    ) -> None:
        if isinstance(cap_bytes, bool) or cap_bytes <= 0:
            raise ValueError("log capture cap_bytes must be a positive integer")
        self.path = path
        self.receipt_path = receipt_path_for(path)
        self.cap_bytes = int(cap_bytes)
        self.stream_name = stream_name
        self._lock = RLock()
        self._closed = False
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._ansi_state = "normal"
        self._pending_cr_frame: str | None = None
        self._critical_line_buffer = ""
        self._critical_lines: list[dict[str, str]] = []
        self._critical_hashes: set[str] = set()
        self._observation_complete = True
        self._observation_error: str | None = None
        self._prior_observation_exact = True

        self.raw_observed_bytes = 0
        self.normalized_observed_bytes = 0
        self.retained_bytes = 0
        self.dropped_bytes_due_to_cap = 0
        self.ansi_sequence_count = 0
        self.ansi_control_bytes_removed = 0
        self.prompt_redraws_collapsed = 0
        self.utf8_replacement_count = 0

        path.parent.mkdir(parents=True, exist_ok=True)
        if append and path.exists():
            self._restore_existing_state()
            self._stream = path.open("ab")
        else:
            self._stream = path.open("wb")
        self._retained_hasher = hashlib.sha256()
        if self.retained_bytes:
            with path.open("rb") as existing:
                for chunk in iter(lambda: existing.read(_READ_CHUNK_BYTES), b""):
                    self._retained_hasher.update(chunk)

    def _restore_existing_state(self) -> None:
        existing_bytes = self.path.stat().st_size
        if existing_bytes > self.cap_bytes:
            raise ValueError(f"existing log exceeds its capture cap: {self.path}")
        if not self.receipt_path.is_file():
            self.raw_observed_bytes = existing_bytes
            self.normalized_observed_bytes = existing_bytes
            self.retained_bytes = existing_bytes
            self._prior_observation_exact = False
            return
        if self.receipt_path.stat().st_size > _MAX_RECEIPT_BYTES:
            raise ValueError(f"log capture receipt is oversized: {self.receipt_path}")
        payload = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != LOG_CAPTURE_SCHEMA_VERSION:
            raise ValueError(f"unsupported log capture receipt: {self.receipt_path}")
        if payload.get("stream") != self.stream_name:
            raise ValueError(f"log capture stream identity changed: {self.path}")
        if payload.get("captured_file_name") != self.path.name:
            raise ValueError(f"log capture file identity changed: {self.path}")
        if payload.get("cap_bytes") != self.cap_bytes:
            raise ValueError(f"log capture cap changed within one run: {self.path}")
        if payload.get("retained_bytes") != existing_bytes:
            raise ValueError(f"log capture receipt size does not match file: {self.path}")
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        if payload.get("retained_sha256") != digest:
            raise ValueError(f"log capture receipt hash does not match file: {self.path}")
        for field in (
            "raw_observed_bytes",
            "normalized_observed_bytes",
            "retained_bytes",
            "dropped_bytes_due_to_cap",
            "ansi_sequence_count",
            "ansi_control_bytes_removed",
            "prompt_redraws_collapsed",
            "utf8_replacement_count",
        ):
            value = payload.get(field, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"log capture receipt field {field} is invalid")
            setattr(self, field, value)
        self._prior_observation_exact = bool(payload.get("prior_observation_exact", True))
        self._observation_complete = bool(payload.get("observation_complete", True))
        for item in payload.get("critical_lines", []):
            if not isinstance(item, dict):
                continue
            line = item.get("line")
            critical_digest = item.get("sha256")
            if isinstance(line, str) and isinstance(critical_digest, str):
                self._critical_lines.append({"line": line, "sha256": critical_digest})
                self._critical_hashes.add(critical_digest)

    def _strip_ansi(self, data: bytes) -> bytes:
        output = bytearray()
        for byte in data:
            state = self._ansi_state
            if state == "normal":
                if byte == 0x1B:
                    self._ansi_state = "esc"
                    self.ansi_sequence_count += 1
                    self.ansi_control_bytes_removed += 1
                elif byte == 0x9B:
                    self._ansi_state = "csi"
                    self.ansi_sequence_count += 1
                    self.ansi_control_bytes_removed += 1
                else:
                    output.append(byte)
                continue

            self.ansi_control_bytes_removed += 1
            if state == "esc":
                if byte == ord("["):
                    self._ansi_state = "csi"
                elif byte == ord("]"):
                    self._ansi_state = "osc"
                elif byte in {ord("P"), ord("^"), ord("_")}:
                    self._ansi_state = "string"
                else:
                    self._ansi_state = "normal"
            elif state == "csi":
                if 0x40 <= byte <= 0x7E:
                    self._ansi_state = "normal"
            elif state == "osc":
                if byte == 0x07:
                    self._ansi_state = "normal"
                elif byte == 0x1B:
                    self._ansi_state = "osc_esc"
            elif state == "osc_esc":
                self._ansi_state = "normal" if byte == ord("\\") else "osc"
            elif state == "string":
                if byte == 0x1B:
                    self._ansi_state = "string_esc"
            elif state == "string_esc":
                self._ansi_state = "normal" if byte == ord("\\") else "string"
        return bytes(output)

    def _resolve_cr_frame(self, frame: str) -> str:
        if _PROMPT_REDRAW.fullmatch(frame):
            self.prompt_redraws_collapsed += 1
            return ""
        return "\r" + frame

    def _normalize_redraws(self, text: str, *, final: bool = False) -> str:
        output: list[str] = []
        for char in text:
            if self._pending_cr_frame is None:
                if char == "\r":
                    self._pending_cr_frame = ""
                else:
                    output.append(char)
                continue
            if char == "\r":
                output.append(self._resolve_cr_frame(self._pending_cr_frame))
                self._pending_cr_frame = ""
            elif char == "\n":
                output.append(self._resolve_cr_frame(self._pending_cr_frame))
                output.append("\n")
                self._pending_cr_frame = None
            else:
                self._pending_cr_frame += char
                if (
                    len(self._pending_cr_frame) > 64
                    and _PROMPT_REDRAW.fullmatch(self._pending_cr_frame) is None
                ):
                    output.append("\r" + self._pending_cr_frame)
                    self._pending_cr_frame = None
        if final and self._pending_cr_frame is not None:
            output.append(self._resolve_cr_frame(self._pending_cr_frame))
            self._pending_cr_frame = None
        return "".join(output)

    def _record_critical_line(self, line: str) -> None:
        normalized = line.strip()
        if not normalized or _CRITICAL_LINE.search(normalized) is None:
            return
        normalized = normalized[:_MAX_CRITICAL_LINE_CHARS]
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if digest in self._critical_hashes or len(self._critical_lines) >= _MAX_CRITICAL_LINES:
            return
        self._critical_hashes.add(digest)
        self._critical_lines.append({"line": normalized, "sha256": digest})

    def _observe_critical_text(self, text: str, *, final: bool = False) -> None:
        combined = self._critical_line_buffer + text.replace("\r", "\n")
        pieces = combined.split("\n")
        for line in pieces[:-1]:
            self._record_critical_line(line)
        self._critical_line_buffer = pieces[-1]
        if len(self._critical_line_buffer) > _MAX_PENDING_LINE_CHARS:
            self._record_critical_line(self._critical_line_buffer)
            self._critical_line_buffer = self._critical_line_buffer[-_MAX_PENDING_LINE_CHARS:]
        if final:
            self._record_critical_line(self._critical_line_buffer)
            self._critical_line_buffer = ""

    def _retain_text(self, text: str) -> None:
        if not text:
            return
        encoded = text.encode("utf-8")
        self.normalized_observed_bytes += len(encoded)
        self._observe_critical_text(text)
        remaining = max(0, self.cap_bytes - self.retained_bytes)
        retained = _utf8_prefix_within_limit(text, remaining)
        if retained:
            self._stream.write(retained)
            self._stream.flush()
            self._retained_hasher.update(retained)
            self.retained_bytes += len(retained)
        self.dropped_bytes_due_to_cap += len(encoded) - len(retained)

    def feed_bytes(self, data: bytes) -> None:
        if not isinstance(data, bytes):
            raise TypeError("log capture feed_bytes requires bytes")
        if not data:
            return
        with self._lock:
            if self._closed:
                raise RuntimeError("log capture is closed")
            self.raw_observed_bytes += len(data)
            stripped = self._strip_ansi(data)
            decoded = self._decoder.decode(stripped, final=False)
            self.utf8_replacement_count += decoded.count("\ufffd")
            self._retain_text(self._normalize_redraws(decoded))

    def feed_text(self, text: str) -> None:
        self.feed_bytes(text.encode("utf-8"))

    def copy_from(self, stream: BinaryIO, *, chunk_bytes: int = _READ_CHUNK_BYTES) -> None:
        try:
            while True:
                chunk = stream.read(chunk_bytes)
                if not chunk:
                    break
                self.feed_bytes(chunk)
        except (OSError, ValueError) as exc:
            with self._lock:
                self._observation_complete = False
                self._observation_error = type(exc).__name__

    def mark_observation_incomplete(self, reason: str) -> None:
        with self._lock:
            self._observation_complete = False
            self._observation_error = reason[:128]

    def close(self, *, write_receipt: bool = True) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                return self.receipt()
            decoded = self._decoder.decode(b"", final=True)
            self.utf8_replacement_count += decoded.count("\ufffd")
            self._retain_text(self._normalize_redraws(decoded, final=True))
            self._observe_critical_text("", final=True)
            with suppress(AttributeError, OSError):
                self._stream.flush()
            self._stream.close()
            self._closed = True
            payload = self.receipt()
            if write_receipt:
                _write_json_atomic(self.receipt_path, payload)
            return payload

    def receipt(self) -> dict[str, Any]:
        truncated = self.dropped_bytes_due_to_cap > 0
        return {
            "schema_version": LOG_CAPTURE_SCHEMA_VERSION,
            "stream": self.stream_name,
            "captured_file_name": self.path.name,
            "cap_bytes": self.cap_bytes,
            "raw_observed_bytes": self.raw_observed_bytes,
            "normalized_observed_bytes": self.normalized_observed_bytes,
            "retained_bytes": self.retained_bytes,
            "dropped_bytes_due_to_cap": self.dropped_bytes_due_to_cap,
            "ansi_sequence_count": self.ansi_sequence_count,
            "ansi_control_bytes_removed": self.ansi_control_bytes_removed,
            "incomplete_ansi_sequence": self._ansi_state != "normal",
            "prompt_redraws_collapsed": self.prompt_redraws_collapsed,
            "utf8_replacement_count": self.utf8_replacement_count,
            "truncated": truncated,
            "truncation_reason": "normalized_output_exceeded_cap" if truncated else None,
            "observation_complete": self._observation_complete,
            "observation_error": self._observation_error,
            "prior_observation_exact": self._prior_observation_exact,
            "critical_lines": list(self._critical_lines),
            "retained_sha256": self._retained_hasher.hexdigest(),
        }

    def __enter__(self) -> StreamingBoundedLogCapture:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


def append_bounded_log_text(
    path: Path,
    text: str,
    *,
    cap_bytes: int,
    stream_name: str,
) -> dict[str, Any]:
    capture = StreamingBoundedLogCapture(
        path,
        cap_bytes=cap_bytes,
        stream_name=stream_name,
        append=True,
    )
    try:
        capture.feed_text(text)
    except Exception:
        capture.close()
        raise
    return capture.close()


def write_bounded_log_bytes(
    path: Path,
    data: bytes,
    *,
    cap_bytes: int,
    stream_name: str,
) -> dict[str, Any]:
    capture = StreamingBoundedLogCapture(
        path,
        cap_bytes=cap_bytes,
        stream_name=stream_name,
        append=False,
    )
    try:
        capture.feed_bytes(data)
    except Exception:
        capture.close()
        raise
    return capture.close()


__all__ = [
    "DEFAULT_AUXILIARY_LOG_CAP_BYTES",
    "DEFAULT_SIMULATOR_STDERR_CAP_BYTES",
    "DEFAULT_SIMULATOR_STDOUT_CAP_BYTES",
    "LOG_CAPTURE_SCHEMA_VERSION",
    "StreamingBoundedLogCapture",
    "append_bounded_log_text",
    "receipt_path_for",
    "write_bounded_log_bytes",
]
