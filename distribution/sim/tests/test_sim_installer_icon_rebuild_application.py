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
    / "yellow-build-installer-icon-attempt-1-0d58049-application.v1.json"
)
ENTRY = (
    ROOT
    / "distribution"
    / "sim"
    / "desktop"
    / "invoke-yellow-build-installer-icon-attempt-1-0d58049.ps1"
)
OVERLAY = ROOT / "distribution" / "sim" / "desktop" / "tauri.sim.conf.json"

PRODUCT_SOURCE = "0d58049891cf61ab2de92ff013a563f496fc816e"
PRODUCT_TREE = "f66b9b65aac84d993b2d371928892ff95d6d3b87"
CANONICAL_ICON = "../../distribution/sim/desktop/icons/dronedream-sim.ico"
REJECTED_ARTIFACT_SHA256 = (
    "9c6bf8ae11014693e6e7f723329c05f5a97b2ed359a0a28a3871868f4b65677c"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_installer_icon_rebuild_is_exact_and_not_authorized() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8-sig"))
    source = application["sourceSeparation"]
    assert source["productSourceCommit"] == PRODUCT_SOURCE
    assert source["productSourceTree"] == PRODUCT_TREE
    assert subprocess.run(
        ["git", "show", "-s", "--format=%T", PRODUCT_SOURCE],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == PRODUCT_TREE

    entry = application["executionPlan"]["entryScript"]
    assert entry["path"] == ENTRY.relative_to(ROOT).as_posix()
    assert entry["bytes"] == ENTRY.stat().st_size
    assert entry["sha256"] == sha256(ENTRY)
    assert application["state"] == (
        "green-plan-frozen-awaiting-single-execution-authorization"
    )
    authorization = application["authorization"]
    assert authorization["newExactChiefControlSignalRequired"] is True
    assert authorization["preflightAuthorizedByThisApplication"] is False
    assert authorization["prepareAuthorizedByThisApplication"] is False
    assert authorization["executeAuthorizedByThisApplication"] is False

    maximums = application["executionPlan"]["maximums"]
    for key in ("buildScript", "frontend", "tauri", "cargo", "nsis", "artifact"):
        assert maximums[key] == 1
    assert maximums["retry"] == 0
    assert all(value == 0 for value in application["executedCounts"].values())
    assert all(value is False for value in application["nonClaims"].values())


def test_installer_icon_rebuild_uses_new_absent_owned_roots() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8-sig"))
    roots = [
        application["ownedBuildSurface"]["sourceRoot"],
        application["ownedBuildSurface"]["runRoot"],
        application["ownedBuildSurface"]["cargoTargetDir"],
        application["attemptOwnedCacheSnapshot"]["snapshotRoot"],
        application["dependencyBundle"]["dependencyRoot"],
    ]
    assert len(set(roots)) == 5
    assert all("0d58049" in root or root.endswith("ddsi1") for root in roots)
    assert all(not Path(root).exists() for root in roots)

    history = application["protectedHistory"]
    assert history["latestRejectedInstallerIconArtifactSha256"] == (
        REJECTED_ARTIFACT_SHA256
    )
    assert history["latestRejectedReason"] == (
        "installer-shell-icon-is-nsis-default-not-canonical-sim"
    )


def test_tauri_overlay_binds_all_windows_icon_surfaces() -> None:
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    assert overlay["bundle"]["icon"] == [CANONICAL_ICON]
    nsis = overlay["bundle"]["windows"]["nsis"]
    assert nsis["installerIcon"] == CANONICAL_ICON
    assert nsis["uninstallerIcon"] == CANONICAL_ICON

