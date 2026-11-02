"""Freeze or verify the baseline-calibrated pre-final v2 scenario registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.optimization.prefinal_calibrated_scenario_registry import (  # noqa: E402
    PREFINAL_CALIBRATED_MANIFEST_SCHEMA_VERSION,
    build_prefinal_calibrated_scenario_registry,
    verify_prefinal_calibrated_scenario_registry,
)
from scripts.evidence_output import write_new_evidence_files  # noqa: E402
from scripts.freeze_prefinal_scenario_registry import (  # noqa: E402
    render_prefinal_scenario_registry_files,
)

_STEM = "prefinal-realistic-scenario-registry-v2"
DEFAULT_JSON_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.json"
DEFAULT_CSV_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.csv"
DEFAULT_MANIFEST_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.manifest.json"
DEFAULT_SHA256_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.sha256"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_prefinal_calibrated_scenario_registry_files(
    *,
    json_path: Path = DEFAULT_JSON_OUTPUT,
    csv_path: Path = DEFAULT_CSV_OUTPUT,
    manifest_path: Path = DEFAULT_MANIFEST_OUTPUT,
    sha256_path: Path = DEFAULT_SHA256_OUTPUT,
    check: bool = False,
) -> dict[str, Any]:
    registry = build_prefinal_calibrated_scenario_registry()
    payloads = render_prefinal_scenario_registry_files(
        registry,
        json_name=json_path.name,
        csv_name=csv_path.name,
        manifest_name=manifest_path.name,
        verify_registry=verify_prefinal_calibrated_scenario_registry,
        manifest_schema_version=PREFINAL_CALIBRATED_MANIFEST_SCHEMA_VERSION,
    )
    outputs = (
        (json_path, payloads[0]),
        (csv_path, payloads[1]),
        (manifest_path, payloads[2]),
        (sha256_path, payloads[3]),
    )
    if check:
        mismatches = [
            str(path)
            for path, expected in outputs
            if not path.is_file() or path.read_bytes() != expected
        ]
        if mismatches:
            raise ValueError("Calibrated scenario registry is stale: " + ", ".join(mismatches))
    else:
        write_new_evidence_files(outputs, label="calibrated pre-final scenario registry")
    return {
        "registry_sha256": registry["registry_sha256"],
        "manifest_sha256": payloads[4]["manifest_sha256"],
        "json_file_sha256": _sha256(payloads[0]),
        "csv_file_sha256": _sha256(payloads[1]),
        "manifest_file_sha256": _sha256(payloads[2]),
        "problem_count": registry["problem_count"],
        "status": registry["status"],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST_OUTPUT)
    parser.add_argument("--sha256-output", type=Path, default=DEFAULT_SHA256_OUTPUT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = write_prefinal_calibrated_scenario_registry_files(
        json_path=args.json_output.resolve(),
        csv_path=args.csv_output.resolve(),
        manifest_path=args.manifest_output.resolve(),
        sha256_path=args.sha256_output.resolve(),
        check=args.check,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
