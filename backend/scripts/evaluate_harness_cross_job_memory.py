"""Write or verify deterministic cross-Job Harness memory evaluation evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
while str(BACKEND_ROOT) in sys.path:
    sys.path.remove(str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestration.harness_cross_job_memory_evaluation import (  # noqa: E402
    build_harness_cross_job_memory_artifact,
    build_harness_cross_job_memory_manifest,
    cross_job_memory_csv_rows,
    verify_harness_cross_job_memory_artifact,
    verify_harness_cross_job_memory_manifest,
)

DEFAULT_ROOT = BACKEND_ROOT / "evaluation_artifacts"
DEFAULT_STEM = "harness-cross-job-memory-contract-v1"


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _csv_bytes(rows: list[dict[str, object]]) -> bytes:
    import io

    output = io.StringIO(newline="")
    fieldnames = list(rows[0]) if rows else []
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def write_harness_cross_job_memory_files(
    *,
    json_path: Path,
    csv_path: Path,
    manifest_path: Path,
    sha256_path: Path,
    check: bool = False,
    artifact: dict[str, object] | None = None,
    manifest: dict[str, object] | None = None,
) -> dict[str, Any]:
    resolved_manifest = verify_harness_cross_job_memory_manifest(
        build_harness_cross_job_memory_manifest() if manifest is None else manifest
    )
    resolved_artifact = verify_harness_cross_job_memory_artifact(
        build_harness_cross_job_memory_artifact() if artifact is None else artifact,
        manifest=resolved_manifest,
    )
    payloads = {
        json_path: _json_bytes(resolved_artifact),
        csv_path: _csv_bytes(cross_job_memory_csv_rows(resolved_artifact)),
        manifest_path: _json_bytes(resolved_manifest),
    }
    checksum_lines = [
        f"{hashlib.sha256(data).hexdigest()}  {path.name}" for path, data in payloads.items()
    ]
    payloads[sha256_path] = ("\n".join(checksum_lines) + "\n").encode("ascii")
    if check:
        mismatches = [
            str(path)
            for path, expected in payloads.items()
            if not path.exists() or path.read_bytes() != expected
        ]
        if mismatches:
            raise ValueError("cross-Job memory evidence drifted: " + ", ".join(mismatches))
    else:
        for path, data in payloads.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    return {
        "artifact_sha256": resolved_artifact["artifact_sha256"],
        "manifest_sha256": resolved_manifest["manifest_sha256"],
        "summary": resolved_artifact["summary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    root = args.output_dir
    result = write_harness_cross_job_memory_files(
        json_path=root / f"{DEFAULT_STEM}.json",
        csv_path=root / f"{DEFAULT_STEM}.csv",
        manifest_path=root / f"{DEFAULT_STEM}.manifest.json",
        sha256_path=root / f"{DEFAULT_STEM}.sha256",
        check=args.check,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
