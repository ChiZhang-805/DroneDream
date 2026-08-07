from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APPLICATION = (
    ROOT
    / "distribution"
    / "sim"
    / "desktop"
    / "yellow-build-attempt-16-4c0021b-application.v1.json"
)
ASSET = (
    ROOT
    / "frontend"
    / "src"
    / "editions"
    / "sim"
    / "assets"
    / "dronedream-sim-centered-separator-lockup.png"
)
ADOPTION = (
    ROOT
    / "distribution"
    / "sim"
    / "brand"
    / "centered-separator-adoption-receipt.v1.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_application() -> dict:
    return json.loads(APPLICATION.read_text(encoding="utf-8"))


def test_rebuild_binds_exact_product_source_and_entry() -> None:
    application = load_application()
    source = application["sourceSeparation"]
    assert source["productSourceCommit"] == (
        "4c0021b28161a9fa2210e6deab0edab2e4f8372d"
    )
    tree = subprocess.run(
        ["git", "show", "-s", "--format=%T", source["productSourceCommit"]],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert tree == source["productSourceTree"]
    assert source["applicationEvidenceIsProductSource"] is False

    entry = application["executionPlan"]["entryScript"]
    entry_path = ROOT / entry["path"]
    assert entry_path.stat().st_size == entry["bytes"]
    assert sha256(entry_path) == entry["sha256"]
    command = application["executionPlan"]["exactCommands"][
        "futureAuthorizedSequence"
    ]
    assert entry["sha256"] in command
    assert str(entry_path) in command


def test_rebuild_is_single_attempt_and_uses_new_owned_roots() -> None:
    application = load_application()
    accounting = application["attemptAccounting"]
    assert accounting["globalCommandApplicationOrdinal"] == 16
    assert accounting["sourceBuildInvocationOrdinal"] == 1
    assert accounting["sourceBuildInvocationMaximum"] == 1
    assert accounting["maximumBuildInvocations"] == 1
    assert accounting["retryMaximum"] == 0
    assert accounting["ordinalFifteenPermanentlyConsumed"] is True

    maximums = application["executionPlan"]["maximums"]
    for key in ("buildScript", "frontend", "tauri", "cargo", "nsis", "artifact"):
        assert maximums[key] == 1
    assert maximums["retry"] == 0

    owned = application["ownedBuildSurface"]
    roots = (
        owned["sourceRoot"],
        owned["runRoot"],
        owned["cargoTargetDir"],
        application["attemptOwnedCacheSnapshot"]["snapshotRoot"],
        application["dependencyBundle"]["dependencyRoot"],
    )
    assert len(set(roots)) == len(roots)
    assert all(
        "ordinal16" in value
        or value.endswith("dds16")
        or value.endswith("4c0021b28161a9fa")
        for value in roots
    )
    assert all(not Path(value).exists() for value in roots)


def test_rebuild_preserves_sim_authority_and_supersedes_old_artifact() -> None:
    application = load_application()
    identity = application["buildIdentity"]
    assert identity["fileName"] == "DroneDream-Sim-1.0.0.exe"
    assert identity["displayName"] == "DroneDream · SIM"
    assert identity["runtimeProfileId"] == "sim-only"
    assert identity["validatedVehiclePackCount"] == 0
    assert identity["hardwareHitlLabFieldPayloadAllowed"] is False

    history = application["protectedHistory"]
    assert history["ordinalFifteenArtifactSha256"] == (
        "fcabd99fcd3add8c4a19ca429b05faafc2a6ad8f5989cf32b62549ec0ec3299e"
    )
    assert history["ordinalFifteenBrandState"] == (
        "superseded-by-centered-separator-source-change"
    )
    assert history["ordinalFifteenReuseRelabelOrWebsiteHandoffAllowed"] is False
    assert application["executionPlan"]["failurePolicy"][
        "ordinalFifteenReuseAllowed"
    ] is False
    assert application["nonClaims"]["artifactCreated"] is False
    assert application["nonClaims"]["releaseReady"] is False


def test_rebuild_uses_exact_centered_separator_brand_asset() -> None:
    adoption = json.loads(ADOPTION.read_text(encoding="utf-8"))
    assert sha256(ASSET) == (
        "f3dd34d3e1a546e4299370d6cbe21d9f03b07a5910dcae061a322ba6c548fd6e"
    )
    assert adoption["source"]["productDonorCommit"] == (
        "6de4f1343c0239a916949f0486fa63d3f460d6a8"
    )
    asset = adoption["assetBinding"]
    geometry = asset["separatorGeometry"]
    assert asset["sha256"] == sha256(ASSET)
    assert geometry["leftGapPx"] == 53
    assert geometry["rightGapPx"] == 53
    assert geometry["tolerancePx"] == 0
