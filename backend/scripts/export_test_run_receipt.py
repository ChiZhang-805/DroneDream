"""Build a content-addressed test receipt for a frozen DroneDream software commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEST_RUN_RECEIPT_SCHEMA_VERSION = "dronedream.test-run-receipt.v2"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _commit(value: str, *, field: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError(f"{field} must be a full lowercase Git SHA")
    return value


def _utc_timestamp(value: str, *, field: str) -> str:
    if not value.endswith("Z"):
        raise ValueError(f"{field} must be an RFC3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{field} must be UTC")
    return value


def _positive_duration(value: float, *, field: str) -> float:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{field} must be finite and positive")
    return value


def _validate_time_window(
    *,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
    field: str,
) -> float:
    start = datetime.fromisoformat(started_at[:-1] + "+00:00")
    finish = datetime.fromisoformat(finished_at[:-1] + "+00:00")
    elapsed = (finish - start).total_seconds()
    if elapsed <= 0.0:
        raise ValueError(f"{field} finished_at must be later than started_at")
    duration = _positive_duration(duration_seconds, field=f"{field}_duration_seconds")
    # Command-native duration can exclude process startup and final log flush
    # while the surrounding timestamps include both. Permit small overhead,
    # but reject a materially different or invented duration.
    tolerance = max(2.0, elapsed * 0.05)
    if abs(duration - elapsed) > tolerance:
        raise ValueError(
            f"{field}_duration_seconds disagrees with its timestamps by more "
            f"than {tolerance:.3f} seconds"
        )
    return duration


def _repository_log(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(REPOSITORY_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"test log is outside the repository: {path}") from exc
    return {
        "path": relative,
        "sha256": _sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def build_test_run_receipt(
    *,
    source_commit: str,
    base_commit: str,
    generated_at: str,
    platform: str,
    python_version: str,
    pytest_version: str,
    full_suite_log_path: Path,
    full_suite_command: str,
    full_suite_working_directory: str,
    full_suite_started_at: str,
    full_suite_finished_at: str,
    full_suite_duration_seconds: float,
    full_suite_passed: int,
    focused_log_path: Path,
    focused_command: str,
    focused_working_directory: str,
    focused_started_at: str,
    focused_finished_at: str,
    focused_duration_seconds: float,
    focused_passed: int,
    bridge_reason: str,
    exact_final_commit_run: bool = False,
) -> dict[str, Any]:
    """Return one deterministic receipt from explicit metadata and immutable logs."""

    source_commit = _commit(source_commit, field="source_commit")
    base_commit = _commit(base_commit, field="base_commit")
    if exact_final_commit_run and source_commit != base_commit:
        raise ValueError(
            "source_commit must equal base_commit for an exact final commit run"
        )
    generated_at = _utc_timestamp(generated_at, field="generated_at")
    full_suite_started_at = _utc_timestamp(
        full_suite_started_at,
        field="full_suite_started_at",
    )
    full_suite_finished_at = _utc_timestamp(
        full_suite_finished_at,
        field="full_suite_finished_at",
    )
    focused_started_at = _utc_timestamp(
        focused_started_at,
        field="focused_started_at",
    )
    focused_finished_at = _utc_timestamp(
        focused_finished_at,
        field="focused_finished_at",
    )
    full_suite_duration_seconds = _validate_time_window(
        started_at=full_suite_started_at,
        finished_at=full_suite_finished_at,
        duration_seconds=full_suite_duration_seconds,
        field="full_suite",
    )
    focused_duration_seconds = _validate_time_window(
        started_at=focused_started_at,
        finished_at=focused_finished_at,
        duration_seconds=focused_duration_seconds,
        field="focused",
    )
    if full_suite_passed <= 0 or focused_passed <= 0:
        raise ValueError("test receipts require positive passing-test counts")
    if any(
        not value.strip()
        for value in (
            platform,
            python_version,
            pytest_version,
            full_suite_command,
            full_suite_working_directory,
            focused_command,
            focused_working_directory,
            bridge_reason,
        )
    ):
        raise ValueError("test receipt text fields must be non-empty")

    unsigned: dict[str, Any] = {
        "schema_version": TEST_RUN_RECEIPT_SCHEMA_VERSION,
        "source_commit": source_commit,
        "generated_at": generated_at,
        "environment": {
            "platform": platform,
            "python": python_version,
            "pytest": pytest_version,
        },
        "full_suite": {
            "command": full_suite_command,
            "working_directory": full_suite_working_directory,
            "started_at": full_suite_started_at,
            "finished_at": full_suite_finished_at,
            "duration_seconds": full_suite_duration_seconds,
            "result": {
                "status": "passed",
                "passed": full_suite_passed,
                "failed": 0,
            },
            "log": _repository_log(full_suite_log_path),
            "tested_state": {
                "kind": "commit" if exact_final_commit_run else "pre_commit_worktree",
                "base_commit": base_commit,
                "exact_final_commit_run": exact_final_commit_run,
            },
        },
        "focused_checks": [
            {
                "command": focused_command,
                "working_directory": focused_working_directory,
                "started_at": focused_started_at,
                "finished_at": focused_finished_at,
                "duration_seconds": focused_duration_seconds,
                "result": {
                    "status": "passed",
                    "passed": focused_passed,
                    "failed": 0,
                },
                "log": _repository_log(focused_log_path),
            }
        ],
        "validation_bridge": {
            "full_suite_rerun_performed": exact_final_commit_run,
            "focused_rerun_required": not exact_final_commit_run,
            "focused_rerun_performed": True,
            "reason": bridge_reason,
        },
    }
    return {
        **unsigned,
        "receipt_sha256": hashlib.sha256(_canonical_json(unsigned).encode("utf-8")).hexdigest(),
    }


def write_new_test_run_receipt(path: Path, receipt: dict[str, Any]) -> None:
    """Write one frozen receipt without replacing any existing evidence."""

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise FileExistsError(f"refusing to overwrite frozen test receipt: {path}") from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--pytest-version", required=True)
    parser.add_argument("--full-suite-log", type=Path, required=True)
    parser.add_argument("--full-suite-command", required=True)
    parser.add_argument("--full-suite-working-directory", required=True)
    parser.add_argument("--full-suite-started-at", required=True)
    parser.add_argument("--full-suite-finished-at", required=True)
    parser.add_argument("--full-suite-duration-seconds", type=float, required=True)
    parser.add_argument("--full-suite-passed", type=int, required=True)
    parser.add_argument("--focused-log", type=Path, required=True)
    parser.add_argument("--focused-command", required=True)
    parser.add_argument("--focused-working-directory", required=True)
    parser.add_argument("--focused-started-at", required=True)
    parser.add_argument("--focused-finished-at", required=True)
    parser.add_argument("--focused-duration-seconds", type=float, required=True)
    parser.add_argument("--focused-passed", type=int, required=True)
    parser.add_argument("--bridge-reason", required=True)
    parser.add_argument(
        "--exact-final-commit-run",
        action="store_true",
        help="Declare that the full suite ran from a clean checkout of source_commit.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    receipt = build_test_run_receipt(
        source_commit=args.source_commit,
        base_commit=args.base_commit,
        generated_at=args.generated_at,
        platform=args.platform,
        python_version=args.python_version,
        pytest_version=args.pytest_version,
        full_suite_log_path=args.full_suite_log,
        full_suite_command=args.full_suite_command,
        full_suite_working_directory=args.full_suite_working_directory,
        full_suite_started_at=args.full_suite_started_at,
        full_suite_finished_at=args.full_suite_finished_at,
        full_suite_duration_seconds=args.full_suite_duration_seconds,
        full_suite_passed=args.full_suite_passed,
        focused_log_path=args.focused_log,
        focused_command=args.focused_command,
        focused_working_directory=args.focused_working_directory,
        focused_started_at=args.focused_started_at,
        focused_finished_at=args.focused_finished_at,
        focused_duration_seconds=args.focused_duration_seconds,
        focused_passed=args.focused_passed,
        bridge_reason=args.bridge_reason,
        exact_final_commit_run=args.exact_final_commit_run,
    )
    write_new_test_run_receipt(args.output, receipt)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "receipt_sha256": receipt["receipt_sha256"],
                "source_commit": receipt["source_commit"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
