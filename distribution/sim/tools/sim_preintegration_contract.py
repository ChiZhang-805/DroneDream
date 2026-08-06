#!/usr/bin/env python3
"""Validate the frozen SIM donor pre-integration surface inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OWNERS = {"universal-common-core", "sim-owned-overlay"}
SIM_OVERLAY_MODES = {
    "preserve-and-reconcile",
    "preserve-approved-byte",
    "replace-only-from-exact-donor",
}
DOMAINS = {
    "authentication",
    "brand",
    "capability",
    "coexistence",
    "runtime",
    "updater",
    "website-handoff",
}


class PreintegrationContractError(ValueError):
    """Raised when the pre-integration contract is incomplete or stale."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PreintegrationContractError(message)


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_contract(
    document: dict[str, Any],
    repo_root: Path,
    *,
    verify_files: bool = True,
    require_current_match: bool = False,
) -> dict[str, Any]:
    _require(document.get("schemaVersion") == 1, "schemaVersion must be 1")
    _require(
        document.get("kind") == "dronedream-sim-final-surface-preintegration",
        "unexpected contract kind",
    )
    _require(document.get("editionId") == "sim", "editionId must be sim")
    _require(document.get("executionClass") == "GREEN-static-only", "not GREEN")

    baseline = document.get("baseline", {})
    for key in ("commit", "tree", "productSourceCommit", "commonCoreCommit"):
        _require(bool(COMMIT_RE.fullmatch(str(baseline.get(key, "")))), f"bad {key}")
    _require(
        bool(SHA256_RE.fullmatch(str(baseline.get("commonCoreHash", "")))),
        "bad commonCoreHash",
    )
    _require(not baseline.get("canonicalDonorReceived"), "donor must remain pending")
    for key in (
        "canonicalDonorCommit",
        "canonicalDonorEvidenceCommit",
        "canonicalDonorManifestSha256",
    ):
        _require(baseline.get(key) is None, f"pending donor {key} must be null")
    _require(not baseline.get("baselineIsReleaseSource"), "baseline cannot be release source")
    if verify_files:
        _require(
            _git(repo_root, "show", "-s", "--format=%T", baseline["commit"])
            == baseline["tree"],
            "baseline tree mismatch",
        )

    policy = document.get("integrationPolicy", {})
    for key in (
        "wholeCommitCherryPickAllowed",
        "manualCommonLogicCopyAllowed",
        "assetCopyBeforeExactDonorAllowed",
        "historicalArtifactRelabelAllowed",
    ):
        _require(policy.get(key) is False, f"{key} must be false")

    surfaces = document.get("localSourceSurfaces")
    _require(isinstance(surfaces, list) and surfaces, "localSourceSurfaces required")
    ids: set[str] = set()
    paths: set[str] = set()
    observed_domains: set[str] = set()
    observed_owners: set[str] = set()
    for row in surfaces:
        surface_id = row.get("id")
        path = row.get("path")
        owner = row.get("owner")
        domain = row.get("domain")
        _require(isinstance(surface_id, str) and surface_id, "surface id required")
        _require(surface_id not in ids, f"duplicate surface id: {surface_id}")
        _require(isinstance(path, str) and path and "\\" not in path, "bad path")
        _require(path not in paths, f"duplicate surface path: {path}")
        _require(owner in OWNERS, f"bad owner for {path}")
        _require(domain in DOMAINS, f"bad domain for {path}")
        _require(bool(COMMIT_RE.fullmatch(str(row.get("gitBlob", "")))), f"bad blob: {path}")
        _require(bool(SHA256_RE.fullmatch(str(row.get("sha256", "")))), f"bad sha: {path}")
        expected_mode = "donor-required" if owner == "universal-common-core" else None
        if expected_mode:
            _require(row.get("integrationMode") == expected_mode, f"bad mode: {path}")
        else:
            _require(
                row.get("integrationMode") in SIM_OVERLAY_MODES,
                f"bad mode: {path}",
            )
        if verify_files:
            baseline_payload = subprocess.run(
                ["git", "-C", str(repo_root), "show", f"{baseline['commit']}:{path}"],
                check=True,
                capture_output=True,
            ).stdout
            _require(
                hashlib.sha256(baseline_payload).hexdigest() == row["sha256"],
                f"baseline SHA mismatch: {path}",
            )
            _require(
                _git(repo_root, "rev-parse", f"{baseline['commit']}:{path}")
                == row["gitBlob"],
                f"baseline blob mismatch: {path}",
            )
            if require_current_match:
                local_path = repo_root / path
                _require(local_path.is_file(), f"missing current surface: {path}")
                _require(
                    _sha256(local_path) == row["sha256"],
                    f"current SHA mismatch: {path}",
                )
        ids.add(surface_id)
        paths.add(path)
        observed_domains.add(domain)
        observed_owners.add(owner)
    _require(observed_domains == DOMAINS, "local domain coverage is incomplete")
    _require(observed_owners == OWNERS, "both ownership classes are required")

    external = document.get("externalSurfaces")
    _require(isinstance(external, list) and external, "external surfaces required")
    for row in external:
        _require(row.get("owner") == "website", "external owner must be website")
        _require(row.get("integrationMode") == "external-read-only", "website must be read-only")
        _require(row.get("domain") == "website-handoff", "bad external domain")

    runtime_requirements = document.get("runtimeSurfaceRequirements")
    _require(
        isinstance(runtime_requirements, list) and runtime_requirements,
        "runtime surfaces required",
    )
    runtime_ids = [row.get("id") for row in runtime_requirements]
    _require(len(runtime_ids) == len(set(runtime_ids)), "duplicate runtime surface id")
    _require(
        all(
            row.get("authority") in OWNERS | {"website"}
            for row in runtime_requirements
        ),
        "bad runtime authority",
    )

    negative = document.get("negativeAcceptanceChecks")
    _require(isinstance(negative, list) and negative, "negative checks required")
    negative_ids = [row.get("id") for row in negative]
    _require(len(negative_ids) == len(set(negative_ids)), "duplicate negative check")
    _require(all(row.get("mustReject") for row in negative), "empty rejection rule")
    required_ids = document.get("requiredNegativeGateIds")
    _require(negative_ids == required_ids, "negative gate list must be exact and ordered")

    evidence = document.get("protectedHistoricalEvidence", {})
    _require(bool(SHA256_RE.fullmatch(str(evidence.get("artifactSha256", "")))), "bad artifact SHA")
    _require(evidence.get("releaseReuseAllowed") is False, "historical EXE reuse forbidden")
    _require(evidence.get("relabelAllowed") is False, "historical EXE relabel forbidden")

    execution = document.get("execution", {})
    _require(
        execution and all(value is False for value in execution.values()),
        "execution flags must be false",
    )
    non_claims = document.get("nonClaims", {})
    _require(
        non_claims and all(value is False for value in non_claims.values()),
        "nonClaims must be false",
    )
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--require-current-match", action="store_true")
    args = parser.parse_args()
    document = json.loads(args.contract.read_text(encoding="utf-8"))
    validate_contract(
        document,
        args.repo_root.resolve(),
        require_current_match=args.require_current_match,
    )
    print(
        json.dumps(
            {
                "valid": True,
                "localSurfaceCount": len(document["localSourceSurfaces"]),
                "externalSurfaceCount": len(document["externalSurfaces"]),
                "negativeGateCount": len(document["negativeAcceptanceChecks"]),
                "releaseAsset": document["execution"]["releaseAsset"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
