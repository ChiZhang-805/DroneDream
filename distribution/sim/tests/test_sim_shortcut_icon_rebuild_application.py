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
    / "yellow-build-shortcut-icon-attempt-1-8014750-application.v1.json"
)
ENTRY = (
    ROOT
    / "distribution"
    / "sim"
    / "desktop"
    / "invoke-yellow-build-shortcut-icon-attempt-1-8014750.ps1"
)
OVERLAY = ROOT / "distribution" / "sim" / "desktop" / "tauri.sim.conf.json"

PRODUCT_SOURCE = "801475050d8b50ec6981f46e282712e02eace243"
PRODUCT_TREE = "bfb563eb2aeb3dd457228510ec6239243caa6cd5"
SHORTCUT_DONOR = "7b9ac353b157ab0a7d03da54c1156e23f81d7cdf"
SUPERSEDED_APPLICATION_SHA256 = (
    "09beafbbb8067449a1bfce5fdce1e7fe20d86676ddff2d42bf6b0a7c214abb71"
)
CANONICAL_ICON = "../../distribution/sim/desktop/icons/dronedream-sim.ico"
REJECTED_ARTIFACT_SHA256 = (
    "9c6bf8ae11014693e6e7f723329c05f5a97b2ed359a0a28a3871868f4b65677c"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_shortcut_icon_rebuild_is_exact_and_not_authorized() -> None:
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


def test_shortcut_icon_rebuild_uses_new_absent_owned_roots() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8-sig"))
    roots = [
        application["ownedBuildSurface"]["sourceRoot"],
        application["ownedBuildSurface"]["runRoot"],
        application["ownedBuildSurface"]["cargoTargetDir"],
        application["attemptOwnedCacheSnapshot"]["snapshotRoot"],
        application["dependencyBundle"]["dependencyRoot"],
    ]
    assert len(set(roots)) == 5
    assert roots[0].endswith("ddss1")
    assert all("8014750" in root for root in roots[1:4])
    assert roots[4].endswith("npm-win32-x64-334b3bf8a3f774ff")
    assert all(not Path(root).exists() for root in roots)

    history = application["protectedHistory"]
    assert history["latestRejectedInstallerIconArtifactSha256"] == (
        REJECTED_ARTIFACT_SHA256
    )
    assert history["latestRejectedReason"] == (
        "installer-shell-icon-is-nsis-default-not-canonical-sim"
    )
    assert history["supersededInstallerIconApplicationSha256"] == (
        SUPERSEDED_APPLICATION_SHA256
    )
    assert history["supersededInstallerIconApplicationPreserved"] is True
    assert history["supersededInstallerIconApplicationExecutionAllowed"] is False


def test_shortcut_icon_donor_is_exact_and_legacy_ico_is_denied() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8-sig"))
    donor = application["shortcutIconDonor"]
    assert donor["commit"] == SHORTCUT_DONOR
    assert donor["syncMode"] == "path-limited-semantic"
    assert donor["shortcutIconSource"] == "$INSTDIR\\${MAINBINARYNAME}.exe"
    assert donor["sharedLegacyIcoShortcutSourceAllowed"] is False

    identity = (ROOT / "desktop/src-tauri/nsis/edition-identity.nsh").read_text(
        encoding="utf-8"
    )
    webview = (ROOT / "desktop/src-tauri/nsis/webview2-health.nsh").read_text(
        encoding="utf-8"
    )
    expected = (
        'CreateShortcut "${SHORTCUT_PATH}" "$INSTDIR\\${MAINBINARYNAME}.exe" '
        '"" "$INSTDIR\\${MAINBINARYNAME}.exe" 0'
    )
    assert expected in identity
    assert expected in webview
    assert not any(
        "CreateShortcut" in line and "DroneDream.ico" in line
        for line in (identity + "\n" + webview).splitlines()
    )

    dependency = application["dependencyBundle"]
    assert dependency["bundleId"] == "npm-win32-x64-334b3bf8a3f774ff"
    assert dependency["dependencyRoot"].endswith(dependency["bundleId"])

    identity_lines = [PRODUCT_SOURCE]
    identity_lines.extend(
        item["sha256"] for item in application["stableCacheContract"]["sourceInputs"]
    )
    identity_lines.extend(["v24.14.1", "11.11.0", "windows", "x64"])
    derived = hashlib.sha256("\n".join(identity_lines).encode()).hexdigest()[:16]
    assert dependency["bundleId"] == f"npm-win32-x64-{derived}"


def test_tauri_overlay_binds_all_windows_icon_surfaces() -> None:
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    assert overlay["bundle"]["icon"] == [CANONICAL_ICON]
    nsis = overlay["bundle"]["windows"]["nsis"]
    assert nsis["installerIcon"] == CANONICAL_ICON
    assert nsis["uninstallerIcon"] == CANONICAL_ICON
