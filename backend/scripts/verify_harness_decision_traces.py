"""Verify exported Harness decision-start traces without database access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
while str(BACKEND_ROOT) in sys.path:
    sys.path.remove(str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

import app  # noqa: E402
from app.orchestration.decision_harness import verify_harness_decision_trace  # noqa: E402

REPORT_SCHEMA_VERSION = "1.0"
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_INPUT_RECORDS = 10_000
_TRACE_EVENT_TYPE = "harness_decision_started"


class TraceInputError(ValueError):
    """Raised when an exported trace file cannot be safely decoded."""


def _assert_local_backend_import() -> None:
    app_path = Path(app.__file__).resolve()
    if not app_path.is_relative_to(BACKEND_ROOT):
        raise RuntimeError(f"imported app from {app_path}, expected it under {BACKEND_ROOT}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify current-version Harness decision-start trace hashes from a "
            "JSON object, JSON array, or JSONL export."
        )
    )
    parser.add_argument("input", type=Path)
    return parser


def _bounded_records(value: object) -> list[object]:
    records = value if isinstance(value, list) else [value]
    if len(records) > MAX_INPUT_RECORDS:
        raise TraceInputError(f"input contains more than {MAX_INPUT_RECORDS} records")
    return records


def load_trace_records(path: Path) -> list[object]:
    """Load a bounded JSON object, JSON array, or JSONL export."""

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise TraceInputError(f"cannot stat input: {type(exc).__name__}") from exc
    if size > MAX_INPUT_BYTES:
        raise TraceInputError(f"input exceeds the {MAX_INPUT_BYTES}-byte safety limit")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise TraceInputError(f"cannot read UTF-8 input: {type(exc).__name__}") from exc
    if not text.strip():
        raise TraceInputError("input is empty")

    try:
        return _bounded_records(json.loads(text))
    except json.JSONDecodeError:
        records: list[object] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise TraceInputError(f"invalid JSONL record at line {line_number}") from exc
            if len(records) > MAX_INPUT_RECORDS:
                raise TraceInputError(
                    f"input contains more than {MAX_INPUT_RECORDS} records"
                ) from None
        if not records:
            raise TraceInputError("input contains no records") from None
        return records


def _safe_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:128]


def verify_trace_records(records: list[object]) -> dict[str, object]:
    """Verify trace records and return a bounded machine-readable report."""

    results: list[dict[str, object]] = []
    ignored_event_count = 0
    for index, record in enumerate(records):
        event_id: str | None = None
        job_id: str | None = None
        payload: object = record
        if isinstance(record, dict) and "event_type" in record:
            if record.get("event_type") != _TRACE_EVENT_TYPE:
                ignored_event_count += 1
                continue
            event_id = _safe_identifier(record.get("id"))
            job_id = _safe_identifier(record.get("job_id"))
            payload = record.get("payload_json")

        verification = verify_harness_decision_trace(payload)
        result: dict[str, object] = {
            "record_index": index,
            "valid": verification.valid,
            "failures": list(verification.failures),
            "computed_hashes": {
                "evidence_sha256": verification.evidence_sha256,
                "tool_manifest_sha256": verification.tool_manifest_sha256,
                "prompt_sha256": verification.prompt_sha256,
            },
        }
        if event_id is not None:
            result["event_id"] = event_id
        if job_id is not None:
            result["job_id"] = job_id
        results.append(result)

    valid_count = sum(bool(result["valid"]) for result in results)
    invalid_count = len(results) - valid_count
    input_failures: list[str] = []
    if not results:
        input_failures.append("no_harness_decision_started_traces")
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "record_count": len(records),
        "trace_count": len(results),
        "ignored_event_count": ignored_event_count,
        "valid_trace_count": valid_count,
        "invalid_trace_count": invalid_count,
        "all_traces_valid": bool(results) and invalid_count == 0,
        "input_failures": input_failures,
        "traces": results,
    }


def main() -> int:
    _assert_local_backend_import()
    args = _parser().parse_args()
    try:
        records = load_trace_records(args.input)
        report = verify_trace_records(records)
    except TraceInputError as exc:
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "all_traces_valid": False,
            "input_failures": [str(exc)],
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_traces_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
