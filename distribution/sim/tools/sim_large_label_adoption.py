#!/usr/bin/env python3
"""Verify exact canonical large-label adoption without executing build work."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path
from typing import Any

DONOR = "b8e0d0c7093abe9f54fe36f01022deb95852fa39"
DONOR_PARENT = "2d19b045c11f5e78ae1a0b6554aee0d0ad382335"
EVIDENCE = "7482647f1c2fcb92f58aaef009efc99764792297"
ASSET_SHA256 = "d11e727f4024f356a3850271aa3349d7286e2da85f647d145388c5d1eec20233"
ALLOWED_PREFIXES = ("brand/", "frontend/src/assets/brand/", "scripts/build-brand-assets.py")
FORBIDDEN_PREFIXES = (
    "backend/",
    "desktop/",
    "distribution/",
    "engine-pack/",
    "runtime/",
    "website/",
    "worker/",
)
EXPECTED_SURFACES = {
    "application-launcher": "source-wired",
    "application-sidebar": "source-wired",
    "sim-overview": "source-wired",
    "installer-ui": "unchanged-canonical-input-only",
    "desktop-start-menu-taskbar": "unchanged-canonical-input-only",
    "login": "pending-universal-auth-donor",
    "browser-callback": "pending-universal-auth-donor",
    "website-edition-card": "pending-website-consumption",
    "website-download-metadata": "pending-exact-final-handoff",
}


class LargeLabelAdoptionError(ValueError):
    """Raised when donor identity, bytes, or fail-closed state drifts."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LargeLabelAdoptionError(message)


def _git(repo_root: Path, *args: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=not binary,
        encoding=None if binary else "utf-8",
    )
    return result.stdout if binary else result.stdout.strip()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    _require(payload[:16] == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "asset is not PNG")
    return struct.unpack(">II", payload[16:24])


def validate_adoption(document: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    _require(document.get("schemaVersion") == 1, "schemaVersion must be 1")
    _require(
        document.get("kind") == "dronedream-sim-canonical-large-label-adoption-receipt",
        "unexpected receipt kind",
    )
    _require(document.get("editionId") == "sim", "editionId must be sim")
    source = document.get("source", {})
    _require(source.get("productDonorCommit") == DONOR, "product donor drifted")
    _require(source.get("donorParentCommit") == DONOR_PARENT, "donor parent drifted")
    _require(source.get("evidenceCommit") == EVIDENCE, "evidence commit drifted")
    _require(source.get("evidenceCommitIsProductSource") is False, "evidence relabeled")
    _require(source.get("commonCoreUpdated") is False, "common core must remain unchanged")
    _require(
        _git(repo_root, "rev-parse", f"{DONOR}^") == DONOR_PARENT,
        "observed donor parent drifted",
    )
    _require(_git(repo_root, "rev-parse", f"{EVIDENCE}^") == DONOR, "evidence parent drifted")

    receipt_bytes = _git(
        repo_root,
        "show",
        f"{EVIDENCE}:{source['universalReceiptPath']}",
        binary=True,
    )
    _require(_sha256(receipt_bytes) == source.get("universalReceiptSha256"), "receipt SHA drifted")
    evidence_paths = _git(repo_root, "diff-tree", "--no-commit-id", "--name-only", "-r", EVIDENCE)
    _require(
        evidence_paths.splitlines() == [source["universalReceiptPath"]],
        "evidence is not receipt-only",
    )

    for path_key, sha_key in (
        ("brandContractPath", "brandContractSha256"),
        ("brandManifestPath", "brandManifestSha256"),
    ):
        payload = _git(repo_root, "show", f"{DONOR}:{source[path_key]}", binary=True)
        _require(_sha256(payload) == source.get(sha_key), f"{path_key} SHA drifted")

    changed_paths = str(
        _git(repo_root, "diff-tree", "--no-commit-id", "--name-only", "-r", DONOR)
    ).splitlines()
    audit = document.get("productAudit", {})
    _require(len(changed_paths) == audit.get("changedPathCount") == 24, "donor path count drifted")
    _require(
        all(path.startswith(ALLOWED_PREFIXES) for path in changed_paths),
        "donor is not brand-only",
    )
    _require(
        not any(path.startswith(FORBIDDEN_PREFIXES) for path in changed_paths),
        "forbidden donor path",
    )
    _require(audit.get("brandOnly") is True, "brand-only classification missing")
    _require(
        audit.get("benchmarkBackendInstallerOrDeployPathsAdopted") is False,
        "forbidden adoption overclaim",
    )

    binding = document.get("assetBinding", {})
    _require(binding.get("displayName") == "DroneDream \u00b7 SIM", "display name drifted")
    _require(binding.get("separatorCodePoint") == "U+00B7", "separator drifted")
    _require(binding.get("naturalEditionLabelWidth") is True, "natural width required")
    _require(binding.get("editionLabelHeightRatio") == 0.9, "label ratio drifted")
    _require(binding.get("redrawnOrReencoded") is False, "redraw or re-encode forbidden")
    donor_asset = _git(repo_root, "show", f"{DONOR}:{binding['approvedSourcePath']}", binary=True)
    mirror_asset = (repo_root / binding["editionPath"]).read_bytes()
    _require(donor_asset == mirror_asset, "edition lockup is not exact donor bytes")
    _require(len(mirror_asset) == binding.get("bytes") == 122340, "asset bytes drifted")
    _require(_sha256(mirror_asset) == binding.get("sha256") == ASSET_SHA256, "asset SHA drifted")
    _require(_png_dimensions(mirror_asset) == (2337, 218), "asset dimensions drifted")

    preserved = document.get("preservedAssets", {})
    for path_key, sha_key in (
        ("markPath", "markSha256"),
        ("windowsIcoPath", "windowsIcoSha256"),
        ("supersededSmallLabelPath", "supersededSmallLabelSha256"),
    ):
        payload = (repo_root / preserved[path_key]).read_bytes()
        _require(_sha256(payload) == preserved.get(sha_key), f"preserved {path_key} drifted")
    _require(preserved.get("supersededSmallLabelDeleted") is False, "old lockup must remain")

    sync = document.get("pathLimitedSync", {})
    _require(sync.get("wholeCommitCherryPicked") is False, "whole commit claim is wrong")
    _require(sync.get("donorPaths") == [binding["donorMirrorPath"]], "donor path set drifted")
    _require(sync.get("lockedEdition") == "sim", "edition lock drifted")
    for key in ("editionRadioPresent", "labOrFieldSwitchPresent", "hardwareAuthorityGranted"):
        _require(sync.get(key) is False, f"{key} must remain false")
    component = (
        repo_root / "frontend/src/editions/sim/SimEditionExperience.tsx"
    ).read_text(encoding="utf-8")
    _require(
        './assets/dronedream-sim-large-label-lockup.png' in component,
        "SIM component not wired",
    )
    _require('data-brand-edition="sim"' in component, "SIM brand marker missing")

    mappings = document.get("surfaceMappings", [])
    observed_mappings = {row.get("surface"): row.get("status") for row in mappings}
    _require(observed_mappings == EXPECTED_SURFACES, "surface mapping drifted")
    _require(len(observed_mappings) == len(mappings), "duplicate surface mapping")
    execution = document.get("execution", {})
    _require(
        execution and all(value is False for value in execution.values()),
        "execution must remain false",
    )
    non_claims = document.get("nonClaims", {})
    _require(
        non_claims and all(value is False for value in non_claims.values()),
        "nonClaims must remain false",
    )
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.receipt.read_text(encoding="utf-8"))
    validate_adoption(document, args.repo_root.resolve())
    print(
        json.dumps(
            {
                "valid": True,
                "productDonorCommit": DONOR,
                "assetSha256": ASSET_SHA256,
                "releaseAsset": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
