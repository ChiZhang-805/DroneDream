#!/usr/bin/env python3
"""Validate the tracked Sim YELLOW-1 record and optional host-local evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_COMMIT = "1af895287c2c8249acfa581919446e24ec16f575"
COMMON_CORE_COMMIT = "e374d3f8d96b1265fcdb06864208b676566e94d9"
COMMON_CORE_HASH = "8e0e0507f4d9fb3c5567af464df7586520c66c3650457b19724a974f9e7ff82b"
RUN_ROOT = "frontend/artifacts/test-runs/sim-yellow-1-20260805T141813Z-1af8952"
RECORD_PATH = "distribution/sim/frontend/yellow-1-evidence-record.v1.json"
ARTIFACT_REFS = {
    "completionReceipt": {
        "path": f"{RUN_ROOT}/sim-yellow-1-completion-receipt.json",
        "sha256": "04cd0437c4b7b4ff587ec2472fee1d5eea5d8e15a15ab1bd10c22b479a0fa4ff",
    },
    "productionBuildReceipt": {
        "path": f"{RUN_ROOT}/sim-frontend-production-build-receipt.json",
        "sha256": "8630c753257f489f4582dcd63549d1546b27c6ae69abba54b48850b000056496",
    },
    "visualReceipt": {
        "path": f"{RUN_ROOT}/sim-frontend-visual-acceptance-receipt.json",
        "sha256": "e64c065be43bb735c217e51e762ce6854bae59a63f08058bfe1d504b5ca5016c",
    },
    "screenshotInventory": {
        "path": f"{RUN_ROOT}/sim-frontend-screenshot-inventory.json",
        "sha256": "f7b16606a710c995ec3bc0cf462f812ef920c719361519f33ac8fbf12a223254",
    },
    "manualReview": {
        "path": f"{RUN_ROOT}/manual-visual-review.v1.json",
        "sha256": "5f43bcfd891c40cf68a8f483713d72f1eccca5522606bce8556e8337cc9b75ee",
    },
}

RECORD_KEYS = {
    "schemaVersion",
    "kind",
    "recordVersion",
    "editionId",
    "state",
    "source",
    "authorization",
    "bindings",
    "artifactEvidence",
    "results",
    "preservedAttempts",
    "resourceClosure",
    "releaseBoundary",
}
SOURCE_KEYS = {
    "productSourceCommit",
    "branch",
    "upstream",
    "sourceTreeStateAtExecution",
    "commonCoreCommit",
    "commonCoreHash",
    "evidenceRecordCommitIsProductSource",
}
AUTHORIZATION_KEYS = {
    "sourceThreadId",
    "class",
    "scope",
    "apiKeyUseAuthorized",
    "deploymentAuthorized",
    "installationAuthorized",
    "yellow2Authorized",
    "yellow3Authorized",
    "redAuthorized",
}
BINDING_KEYS = {"contract", "visualTool"}
FILE_REF_KEYS = {"path", "sha256"}
ARTIFACT_KEYS = {
    "availability",
    "runRoot",
    "completionReceipt",
    "productionBuildReceipt",
    "visualReceipt",
    "screenshotInventory",
    "manualReview",
}
RESULT_KEYS = {
    "productionBuildExecuted",
    "productionBuildExitCode",
    "buildFileCount",
    "buildTotalBytes",
    "buildInventoryAggregateSha256",
    "edgeCaseCount",
    "screenshotCount",
    "screenshotTotalBytes",
    "screenshotAggregateSha256",
    "manualVisualAcceptance",
    "allForbiddenInteractiveCountsZero",
    "allSetupCommandControlCountsZero",
    "allBlockedRoutesDenied",
    "allDocumentWidthsExact",
    "normalStateSkipLinksOutsideViewport",
}
ATTEMPT_KEYS = {"sourceCommit", "classification", "evidenceDeleted"}
RESOURCE_KEYS = {
    "port5198Released",
    "browserClosed",
    "viteServerClosed",
    "apiKeyRead",
    "deploymentExecuted",
    "installerBuilt",
    "installerExecuted",
    "runtimeStarted",
    "px4Started",
    "gazeboStarted",
}
RELEASE_KEYS = {
    "validatedVehiclePackCount",
    "releaseAssetClaimed",
    "promotionReady",
    "yellow2BlockedPendingFormalDonorAndIcoSync",
    "yellow3Authorized",
    "redAuthorized",
}


class SimYellow1EvidenceError(ValueError):
    """Raised when YELLOW-1 evidence is incomplete or overclaims readiness."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SimYellow1EvidenceError(f"could not read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SimYellow1EvidenceError(f"JSON document must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise SimYellow1EvidenceError(f"not a PNG file: {path}")
    return struct.unpack(">II", header[16:24])


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = set(value) if isinstance(value, dict) else set()
        raise SimYellow1EvidenceError(
            f"{label} keys drifted (missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)})"
        )
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise SimYellow1EvidenceError(f"{label} is not a SHA-256 digest")
    return value


def _repo_file(repo_root: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or relative.startswith(("/", "\\")) or ".." in relative:
        raise SimYellow1EvidenceError(f"{label} is not repository-relative")
    target = (repo_root / relative).resolve()
    try:
        target.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise SimYellow1EvidenceError(f"{label} escapes repository root") from exc
    if not target.is_file():
        raise SimYellow1EvidenceError(f"{label} does not exist: {relative}")
    return target


def _is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
        capture_output=True,
    )
    if completed.returncode not in {0, 1}:
        raise SimYellow1EvidenceError("could not verify YELLOW-1 source ancestry")
    return completed.returncode == 0


def _validate_ref(
    raw_ref: Any,
    *,
    repo_root: Path,
    label: str,
    require_file: bool,
) -> tuple[dict[str, Any], Path | None]:
    ref = _exact_keys(raw_ref, FILE_REF_KEYS, label)
    _sha(ref["sha256"], f"{label} SHA-256")
    if not require_file:
        return ref, None
    path = _repo_file(repo_root, ref["path"], label)
    if sha256_file(path) != ref["sha256"]:
        raise SimYellow1EvidenceError(f"{label} SHA-256 drifted")
    return ref, path


def validate_yellow1_evidence_record(
    document: Any,
    *,
    repo_root: Path,
    require_local_artifacts: bool = False,
) -> dict[str, Any]:
    record = _exact_keys(document, RECORD_KEYS, "Sim YELLOW-1 evidence record")
    if (
        record["schemaVersion"] != 1
        or record["kind"] != "dronedream-sim-yellow-1-evidence-record"
        or record["recordVersion"] != "1.0.0"
        or record["editionId"] != "sim"
        or record["state"] != "yellow-1-passed-not-promotion-ready"
    ):
        raise SimYellow1EvidenceError("YELLOW-1 evidence record identity drifted")

    source = _exact_keys(record["source"], SOURCE_KEYS, "YELLOW-1 source")
    if source != {
        "productSourceCommit": SOURCE_COMMIT,
        "branch": "codex/software-sim",
        "upstream": "origin/codex/software-sim",
        "sourceTreeStateAtExecution": "clean",
        "commonCoreCommit": COMMON_CORE_COMMIT,
        "commonCoreHash": COMMON_CORE_HASH,
        "evidenceRecordCommitIsProductSource": False,
    } or not _is_ancestor(repo_root, SOURCE_COMMIT, "HEAD"):
        raise SimYellow1EvidenceError("YELLOW-1 source/evidence binding drifted")

    authorization = _exact_keys(
        record["authorization"], AUTHORIZATION_KEYS, "YELLOW-1 authorization"
    )
    if authorization != {
        "sourceThreadId": "019fa6ec-e8e6-7222-8c4c-1a064d17a0a9",
        "class": "YELLOW-1",
        "scope": "production-frontend-build-and-microsoft-edge-six-case-visual-acceptance",
        "apiKeyUseAuthorized": False,
        "deploymentAuthorized": False,
        "installationAuthorized": False,
        "yellow2Authorized": False,
        "yellow3Authorized": False,
        "redAuthorized": False,
    }:
        raise SimYellow1EvidenceError("YELLOW-1 authorization scope drifted")

    bindings = _exact_keys(record["bindings"], BINDING_KEYS, "YELLOW-1 bindings")
    for role in ("contract", "visualTool"):
        _validate_ref(
            bindings[role], repo_root=repo_root, label=f"YELLOW-1 {role}", require_file=True
        )

    artifact = _exact_keys(
        record["artifactEvidence"], ARTIFACT_KEYS, "YELLOW-1 artifact evidence"
    )
    if (
        artifact["availability"] != "branch-local-host-evidence-not-git-payload"
        or artifact["runRoot"] != RUN_ROOT
    ):
        raise SimYellow1EvidenceError("YELLOW-1 host evidence boundary drifted")
    artifact_documents: dict[str, dict[str, Any]] = {}
    for role in (
        "completionReceipt",
        "productionBuildReceipt",
        "visualReceipt",
        "screenshotInventory",
        "manualReview",
    ):
        ref, path = _validate_ref(
            artifact[role],
            repo_root=repo_root,
            label=f"YELLOW-1 {role}",
            require_file=require_local_artifacts,
        )
        if ref != ARTIFACT_REFS[role]:
            raise SimYellow1EvidenceError(f"YELLOW-1 {role} binding drifted")
        if path is not None:
            artifact_documents[role] = load_json(path)

    results = _exact_keys(record["results"], RESULT_KEYS, "YELLOW-1 results")
    if results != {
        "productionBuildExecuted": True,
        "productionBuildExitCode": 0,
        "buildFileCount": 54,
        "buildTotalBytes": 7312435,
        "buildInventoryAggregateSha256": (
            "6861a1bcba97f9e317794759804a694cf736c33edfdba304fe97f2208be94b17"
        ),
        "edgeCaseCount": 6,
        "screenshotCount": 18,
        "screenshotTotalBytes": 5460376,
        "screenshotAggregateSha256": (
            "ae3dcf725addaa97262453b6c15d8c2ed54c6a19920d601e5b37d3ddfde7cca2"
        ),
        "manualVisualAcceptance": True,
        "allForbiddenInteractiveCountsZero": True,
        "allSetupCommandControlCountsZero": True,
        "allBlockedRoutesDenied": True,
        "allDocumentWidthsExact": True,
        "normalStateSkipLinksOutsideViewport": True,
    }:
        raise SimYellow1EvidenceError("YELLOW-1 result summary drifted")

    attempts = record["preservedAttempts"]
    expected_attempts = [
        (
            "8f99fed22ea03846c26ed5184eaa8b2f7982741b",
            "playwright-import-failed-before-browser-start",
        ),
        (
            "ae371194e3d3c46e990b6517c93e1981e74dd970",
            "preview-status-selector-failed-after-one-case",
        ),
        (
            "9dbff76b1411b0d31ae59c8ca7ad103a1a394d92",
            "tool-pass-manual-review-rejected-focused-skip-link",
        ),
    ]
    if not isinstance(attempts, list) or len(attempts) != len(expected_attempts):
        raise SimYellow1EvidenceError("YELLOW-1 attempt inventory drifted")
    for index, (commit, classification) in enumerate(expected_attempts):
        attempt = _exact_keys(attempts[index], ATTEMPT_KEYS, f"YELLOW-1 attempt {index}")
        if attempt != {
            "sourceCommit": commit,
            "classification": classification,
            "evidenceDeleted": False,
        } or not _is_ancestor(repo_root, commit, SOURCE_COMMIT):
            raise SimYellow1EvidenceError("YELLOW-1 attempt provenance drifted")

    resources = _exact_keys(
        record["resourceClosure"], RESOURCE_KEYS, "YELLOW-1 resource closure"
    )
    if resources != {
        "port5198Released": True,
        "browserClosed": True,
        "viteServerClosed": True,
        "apiKeyRead": False,
        "deploymentExecuted": False,
        "installerBuilt": False,
        "installerExecuted": False,
        "runtimeStarted": False,
        "px4Started": False,
        "gazeboStarted": False,
    }:
        raise SimYellow1EvidenceError("YELLOW-1 resource closure drifted")
    release = _exact_keys(
        record["releaseBoundary"], RELEASE_KEYS, "YELLOW-1 release boundary"
    )
    if release != {
        "validatedVehiclePackCount": 0,
        "releaseAssetClaimed": False,
        "promotionReady": False,
        "yellow2BlockedPendingFormalDonorAndIcoSync": True,
        "yellow3Authorized": False,
        "redAuthorized": False,
    }:
        raise SimYellow1EvidenceError("YELLOW-1 release boundary drifted")

    if require_local_artifacts:
        completion = artifact_documents["completionReceipt"]
        build = artifact_documents["productionBuildReceipt"]
        visual = artifact_documents["visualReceipt"]
        screenshots = artifact_documents["screenshotInventory"]
        review = artifact_documents["manualReview"]
        expected_source = {
            "commit": SOURCE_COMMIT,
            "branch": "codex/software-sim",
            "upstream": "origin/codex/software-sim",
            "treeState": "clean",
            "commonCoreCommit": COMMON_CORE_COMMIT,
            "commonCoreHash": COMMON_CORE_HASH,
        }
        if (
            completion.get("status") != "pass"
            or completion.get("source") != expected_source
            or build.get("source", {}).get("commit") != SOURCE_COMMIT
            or build.get("build", {}).get("exitCode") != 0
            or build.get("inventory", {}).get("fileCount") != 54
            or visual.get("sourceCommit") != SOURCE_COMMIT
            or visual.get("status") != "pass"
            or len(visual.get("cases", [])) != 6
            or any(case.get("status") != "pass" for case in visual["cases"])
            or screenshots.get("inventory", {}).get("fileCount") != 18
            or review.get("manualAcceptance") is not True
            or review.get("promotionReady") is not False
        ):
            raise SimYellow1EvidenceError("YELLOW-1 host-local evidence content drifted")

        completion_links = {
            "productionBuildReceipt": (
                completion.get("productionBuild", {}).get("receiptPath"),
                completion.get("productionBuild", {}).get("receiptSha256"),
            ),
            "visualReceipt": (
                completion.get("visualAcceptance", {}).get("receiptPath"),
                completion.get("visualAcceptance", {}).get("receiptSha256"),
            ),
            "screenshotInventory": (
                completion.get("screenshots", {}).get("inventoryPath"),
                completion.get("screenshots", {}).get("inventorySha256"),
            ),
            "manualReview": (
                completion.get("manualReview", {}).get("path"),
                completion.get("manualReview", {}).get("sha256"),
            ),
        }
        for role, (path, digest) in completion_links.items():
            expected = ARTIFACT_REFS[role]
            if path != expected["path"] or digest != expected["sha256"]:
                raise SimYellow1EvidenceError(
                    f"YELLOW-1 completion receipt {role} binding drifted"
                )

        build_inventory = build["inventory"]
        build_files = build_inventory.get("files", [])
        if (
            len(build_files) != results["buildFileCount"]
            or sum(item.get("bytes", -1) for item in build_files)
            != results["buildTotalBytes"]
            or build_inventory.get("aggregateSha256")
            != results["buildInventoryAggregateSha256"]
        ):
            raise SimYellow1EvidenceError("YELLOW-1 build inventory summary drifted")
        for item in build_files:
            path = _repo_file(repo_root, item.get("path"), "YELLOW-1 build file")
            if path.stat().st_size != item.get("bytes") or sha256_file(path) != item.get(
                "sha256"
            ):
                raise SimYellow1EvidenceError(
                    f"YELLOW-1 build file drifted: {item.get('path')}"
                )

        screenshot_inventory = screenshots["inventory"]
        screenshot_files = screenshot_inventory.get("files", [])
        if (
            len(screenshot_files) != results["screenshotCount"]
            or sum(item.get("bytes", -1) for item in screenshot_files)
            != results["screenshotTotalBytes"]
            or screenshot_inventory.get("aggregateSha256")
            != results["screenshotAggregateSha256"]
        ):
            raise SimYellow1EvidenceError("YELLOW-1 screenshot inventory summary drifted")
        screenshot_refs: dict[str, str] = {}
        for item in screenshot_files:
            path = _repo_file(
                repo_root, item.get("path"), "YELLOW-1 screenshot inventory file"
            )
            if (
                path.stat().st_size != item.get("bytes")
                or sha256_file(path) != item.get("sha256")
                or png_dimensions(path) != (item.get("width"), item.get("height"))
            ):
                raise SimYellow1EvidenceError(
                    f"YELLOW-1 screenshot drifted: {item.get('path')}"
                )
            screenshot_refs[item["path"]] = item["sha256"]

        visual_refs: dict[str, str] = {}
        for case in visual["cases"]:
            for surface in ("overview", "setup", "blockedRoutes"):
                image = case.get(surface, {}).get("image", {})
                visual_refs[image.get("path")] = image.get("sha256")
        if visual_refs != screenshot_refs:
            raise SimYellow1EvidenceError(
                "YELLOW-1 visual receipt and screenshot inventory drifted"
            )

        if (
            review.get("sourceCommit") != SOURCE_COMMIT
            or review.get("toolReceipt", {}).get("sha256")
            != ARTIFACT_REFS["visualReceipt"]["sha256"]
            or review.get("screenshotInventory", {}).get("sha256")
            != ARTIFACT_REFS["screenshotInventory"]["sha256"]
            or review.get("screenshotInventory", {}).get("aggregateSha256")
            != results["screenshotAggregateSha256"]
        ):
            raise SimYellow1EvidenceError("YELLOW-1 manual review binding drifted")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--require-local-artifacts", action="store_true")
    parser.add_argument("record", type=Path, nargs="?", default=Path(RECORD_PATH))
    args = parser.parse_args()
    try:
        validate_yellow1_evidence_record(
            load_json(args.record),
            repo_root=args.repo_root.resolve(),
            require_local_artifacts=args.require_local_artifacts,
        )
    except SimYellow1EvidenceError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
