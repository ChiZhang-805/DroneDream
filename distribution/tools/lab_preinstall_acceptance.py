#!/usr/bin/env python3
"""Offline Lab pre-install acceptance gate.

This tool is deliberately read-only: it never starts an installer, probes
hardware, launches PX4/Gazebo, reads secrets, or mutates release branches.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import verify_lab_preview_artifact as artifact_verifier
import verify_lab_preview_contract as profile_verifier

ROOT = Path(__file__).resolve().parents[2]


class LabPreinstallAcceptanceError(ValueError):
    """Raised when a pre-install request cannot be evaluated safely."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LabPreinstallAcceptanceError(f"cannot read receipt: {path}") from exc
    if not isinstance(value, dict):
        raise LabPreinstallAcceptanceError("receipt must be a JSON object")
    return value


def evaluate_preinstall(
    receipt: dict[str, Any] | None = None,
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Return a deterministic install decision without side effects."""

    profile = profile_verifier.verify_lab_preview_contract()
    blockers = [
        "Lab preview remains unsigned internal-test material.",
        "There are zero validated Vehicle Packs.",
        "Hardware parameter write, arm, HITL, and flight actions are denied.",
        "No release-lab promotion is authorized by pre-install acceptance.",
    ]
    receipt_summary: dict[str, Any] | None = None
    if receipt is None:
        blockers.insert(0, "No Lab artifact receipt was supplied.")
    else:
        try:
            validated = artifact_verifier.validate_receipt(
                receipt,
                artifact_root=artifact_root,
            )
        except artifact_verifier.LabPreviewArtifactError as exc:
            blockers.insert(0, f"Lab artifact receipt failed closed: {exc}")
        else:
            receipt_summary = {
                "testOnly": validated["testOnly"],
                "sourceCommit": validated["sourceCommit"],
                "commonCoreCommit": validated["commonCoreCommit"],
                "commonCoreHash": validated["commonCoreHash"],
                "artifactFileName": validated["artifact"]["fileName"],
            }
            if validated["testOnly"]:
                blockers.insert(0, "Only a fake test fixture receipt was supplied.")
            else:
                blockers = [
                    blocker
                    for blocker in blockers
                    if blocker != "No Lab artifact receipt was supplied."
                ]
    return {
        "schemaVersion": 1,
        "kind": "dronedream-lab-preinstall-acceptance",
        "editionId": "lab",
        "decision": "blocked" if blockers else "acceptable",
        "profile": profile,
        "receipt": receipt_summary,
        "blockers": blockers,
        "sideEffects": {
            "buildExe": False,
            "install": False,
            "hardwareProbe": False,
            "px4Gazebo": False,
            "readSecrets": False,
            "createReleaseBranch": False,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    receipt_path = args.receipt.resolve() if args.receipt else None
    receipt = _load_json(receipt_path) if receipt_path else None
    try:
        result = evaluate_preinstall(
            receipt,
            artifact_root=receipt_path.parent if receipt_path else None,
        )
    except (LabPreinstallAcceptanceError, profile_verifier.LabPreviewContractError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
