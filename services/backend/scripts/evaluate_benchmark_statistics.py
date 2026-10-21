"""Validate and atomically freeze a preregistered benchmark statistics output."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.benchmarking.statistics import (  # noqa: E402
    BenchmarkStatisticalInputV1,
    evaluate_benchmark_statistics,
)


def _write_new_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite frozen statistics output: {path}")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def evaluate_file(input_path: Path, output_path: Path) -> dict[str, object]:
    input_bytes = input_path.read_bytes()
    raw = json.loads(input_bytes)
    value = BenchmarkStatisticalInputV1.model_validate(raw)
    input_file_sha256 = hashlib.sha256(input_bytes).hexdigest()
    result = evaluate_benchmark_statistics(value, input_file_sha256=input_file_sha256)
    output_payload = result.model_dump(mode="json")
    encoded = (
        json.dumps(output_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    _write_new_atomic(output_path, encoded)
    return {
        "outputPath": str(output_path),
        "outputBytes": len(encoded),
        "outputSha256": hashlib.sha256(encoded).hexdigest(),
        "phase": result.phase,
        "blinded": result.blinded,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a complete frozen benchmark grid without provider or simulator access."
        )
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    summary = evaluate_file(args.input, args.output)
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
