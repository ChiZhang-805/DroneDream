"""Run and freeze the current offline multi-tool Harness fallback campaign."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestration.harness_fallback_contract_campaign import (  # noqa: E402
    HARNESS_FALLBACK_CONTRACT_REFERENCE_ARM,
    build_harness_fallback_contract_campaign,
    verify_harness_fallback_contract_campaign,
)
from scripts.evidence_output import write_new_evidence_files  # noqa: E402

DEFAULT_JSON_OUTPUT = (
    BACKEND_ROOT / "evaluation_artifacts" / "harness-fallback-contract-campaign-v3.json"
)
DEFAULT_CSV_OUTPUT = (
    BACKEND_ROOT / "evaluation_artifacts" / "harness-fallback-contract-campaign-v3.csv"
)
DEFAULT_SHA256_OUTPUT = (
    BACKEND_ROOT / "evaluation_artifacts" / "harness-fallback-contract-campaign-v3.sha256"
)

CSV_FIELDS = (
    "block_id",
    "seed_block",
    "arm",
    "provider_calls",
    "network_calls",
    "terminal_status",
    "optimization_outcome",
    "candidate_count",
    "trial_count",
    "configured_max_total_trials",
    "dispatched_trials",
    "completed_trials",
    "winner_candidate_key",
    "holdout_loss",
    "failure_count",
    "evidence_completeness_rate",
    "outcome_sha256",
    "exact_match_to_deterministic_baseline",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(artifact: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            artifact,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _csv_bytes(artifact: dict[str, Any]) -> bytes:
    rows: list[dict[str, Any]] = []
    for block in artifact["block_rows"]:
        baseline_hash = next(
            arm["outcome_sha256"]
            for arm in block["arms"]
            if arm["arm"] == HARNESS_FALLBACK_CONTRACT_REFERENCE_ARM
        )
        for arm in block["arms"]:
            outcome = arm["outcome"]
            budget = outcome["budget"]
            winner = outcome["winner"]
            rows.append(
                {
                    "block_id": block["block_id"],
                    "seed_block": block["seed_block"],
                    "arm": arm["arm"],
                    "provider_calls": arm["provider_calls"],
                    "network_calls": arm["network_calls"],
                    "terminal_status": outcome["terminal_status"],
                    "optimization_outcome": outcome["optimization_outcome"],
                    "candidate_count": budget["candidate_count"],
                    "trial_count": budget["trial_count"],
                    "configured_max_total_trials": budget["configured_max_total_trials"],
                    "dispatched_trials": budget["dispatched_trials"],
                    "completed_trials": budget["completed_trials"],
                    "winner_candidate_key": (
                        winner["candidate_key"] if isinstance(winner, dict) else ""
                    ),
                    "holdout_loss": outcome["holdout_loss"],
                    "failure_count": outcome["failure_count"],
                    "evidence_completeness_rate": outcome["evidence_completeness"][
                        "completeness_rate"
                    ],
                    "outcome_sha256": arm["outcome_sha256"],
                    "exact_match_to_deterministic_baseline": (
                        arm["outcome_sha256"] == baseline_hash
                    ),
                }
            )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(CSV_FIELDS),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def render_harness_fallback_contract_files(
    artifact: dict[str, Any],
    *,
    json_name: str,
    csv_name: str,
) -> tuple[bytes, bytes, bytes]:
    artifact = verify_harness_fallback_contract_campaign(artifact)
    json_payload = _json_bytes(artifact)
    csv_payload = _csv_bytes(artifact)
    sha256_payload = (
        f"{_sha256(json_payload)}  {json_name}\n{_sha256(csv_payload)}  {csv_name}\n"
    ).encode("ascii")
    return json_payload, csv_payload, sha256_payload


def write_harness_fallback_contract_files(
    *,
    json_path: Path,
    csv_path: Path,
    sha256_path: Path,
    check: bool = False,
    artifact: dict[str, Any] | None = None,
) -> dict[str, str]:
    campaign = build_harness_fallback_contract_campaign() if artifact is None else artifact
    payloads = render_harness_fallback_contract_files(
        campaign,
        json_name=json_path.name,
        csv_name=csv_path.name,
    )
    outputs = tuple(zip((json_path, csv_path, sha256_path), payloads, strict=True))
    if check:
        mismatches = [
            str(path)
            for path, expected in outputs
            if not path.is_file() or path.read_bytes() != expected
        ]
        if mismatches:
            raise ValueError(
                "Harness fallback contract artifacts are stale: " + ", ".join(mismatches)
            )
    else:
        write_new_evidence_files(outputs, label="Harness fallback-contract evidence")
    return {
        "artifact_sha256": str(campaign["artifact_sha256"]),
        "json_file_sha256": _sha256(payloads[0]),
        "csv_file_sha256": _sha256(payloads[1]),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--sha256-output", type=Path, default=DEFAULT_SHA256_OUTPUT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = write_harness_fallback_contract_files(
        json_path=args.json_output.resolve(),
        csv_path=args.csv_output.resolve(),
        sha256_path=args.sha256_output.resolve(),
        check=args.check,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
