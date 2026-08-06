#!/usr/bin/env python3
"""Verify the frozen SIM artifact's app-only RED lifecycle plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

PRODUCT_SOURCE = "f24eb3a1e383c83b8a0b5bed4c044148146f4153"
ARTIFACT_SHA256 = "f23987bac2af03fd085f981ecd730948e0fe0e831acf639e2bffcb7c31ffbece"
ARTIFACT_BYTES = 11686921
PLAN_KIND = "dronedream-sim-red-app-only-lifecycle-plan"
RECEIPT_KIND = "dronedream-sim-red-app-only-readiness"


class SimRedReadinessError(ValueError):
    """Raised when the app-only lifecycle boundary drifts."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SimRedReadinessError(message)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _git_json(root: Path, commit: str, path: str) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{path}"],
        check=True,
        capture_output=True,
    )
    return json.loads(result.stdout.decode("utf-8"))


def _normalized(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").casefold()


def _assert_false_values(value: Any, label: str) -> None:
    _require(
        isinstance(value, dict)
        and bool(value)
        and all(item is False for item in value.values()),
        f"{label} must remain false",
    )


def validate_plan(
    plan: dict[str, Any], root: Path, *, require_local_evidence: bool = False
) -> dict[str, Any]:
    _require(plan.get("schemaVersion") == 1, "plan schema drifted")
    _require(plan.get("kind") == PLAN_KIND, "plan kind drifted")
    _require(plan.get("planVersion") == "1.0.0", "plan version drifted")
    _require(plan.get("editionId") == "sim", "plan edition drifted")
    _require(
        plan.get("state") == "green-plan-only-awaiting-red-authorization",
        "plan state drifted",
    )

    source = plan["sourceSeparation"]
    _require(source["productSourceCommit"] == PRODUCT_SOURCE, "product source drifted")
    _require(source["toolEvidenceIsProductSource"] is False, "source relabelled")

    artifact = plan["artifact"]
    _require(artifact["fileName"] == "DroneDream-Sim-1.0.0.exe", "filename drifted")
    _require(artifact["sha256"] == ARTIFACT_SHA256, "artifact SHA drifted")
    _require(artifact["bytes"] == ARTIFACT_BYTES, "artifact bytes drifted")

    donor = plan["universalDonorComparison"]
    donor_refs = (
        (
            donor["lifecycleProductSource"],
            donor["lifecycleVerifierPath"],
            donor["lifecycleVerifierBlob"],
        ),
        (
            donor["editionIdentityToolHead"],
            donor["editionIdentityVerifierPath"],
            donor["editionIdentityVerifierBlob"],
        ),
    )
    for commit, path, blob in donor_refs:
        _require(_git(root, "rev-parse", f"{commit}:{path}") == blob, f"donor drifted: {path}")
    _require(donor["consumedAsProductSource"] is False, "donor relabelled")
    _require(donor["commonExecutionLogicCopied"] is False, "common logic copied")

    compiled = plan["compiledEvidence"]
    source_refs = (
        (compiled["overlayPath"], compiled["overlayBlobAtProductSource"]),
        (
            compiled["editionIdentityPath"],
            compiled["editionIdentityBlobAtProductSource"],
        ),
        (
            compiled["installerTemplatePath"],
            compiled["installerTemplateBlobAtProductSource"],
        ),
        (
            compiled["coexistenceManifestPath"],
            compiled["coexistenceManifestBlobAtProductSource"],
        ),
    )
    for path, blob in source_refs:
        _require(
            _git(root, "rev-parse", f"{PRODUCT_SOURCE}:{path}") == blob,
            f"product-source blob drifted: {path}",
        )

    identity = plan["identity"]
    expected_identity = {
        "internalProductName": "DroneDream-Sim",
        "installMode": "currentUser",
        "defaultInstallRoot": "%LOCALAPPDATA%/DroneDream-Sim",
        "uninstallRegistryKey": (
            "HKCU/Software/Microsoft/Windows/CurrentVersion/Uninstall/DroneDream-Sim"
        ),
        "productRegistryKey": "HKCU/Software/DroneDream/DroneDream-Sim",
        "displayName": "DroneDream · SIM",
        "displayVersion": "1.0.0",
        "mainBinaryName": "drone-dream-desktop.exe",
        "desktopShortcut": "%USERPROFILE%/Desktop/DroneDream · SIM.lnk",
        "startMenuShortcut": (
            "%APPDATA%/Microsoft/Windows/Start Menu/Programs/DroneDream · SIM.lnk"
        ),
        "shortcutTarget": (
            "%LOCALAPPDATA%/DroneDream-Sim/drone-dream-desktop.exe"
        ),
        "artifactBundleIdentifier": "io.dronedream.sim",
        "artifactAppUserModelId": "io.dronedream.sim",
        "artifactAppDataRoots": [
            "%APPDATA%/io.dronedream.sim",
            "%LOCALAPPDATA%/io.dronedream.sim",
        ],
        "runtimeProfileId": "sim-only",
    }
    _require(identity == expected_identity, "compiled SIM identity drifted")
    expected_vs_artifact = plan["expectedVsArtifact"]
    _require(
        set(expected_vs_artifact)
        == {
            "internalProductName",
            "uninstallRegistryKey",
            "displayName",
            "installLocation",
            "mainBinaryName",
            "visibleShortcut",
        },
        "expected/actual identity inventory drifted",
    )
    for field, comparison_row in expected_vs_artifact.items():
        _require(
            comparison_row.get("contractExpected")
            == comparison_row.get("artifactCompiledActual"),
            f"expected/actual identity mismatch: {field}",
        )

    overlay = _git_json(root, PRODUCT_SOURCE, compiled["overlayPath"])
    _require(overlay["productName"] == identity["internalProductName"], "overlay product drifted")
    _require(
        overlay["identifier"] == identity["artifactBundleIdentifier"],
        "overlay bundle identity drifted",
    )
    _require(
        overlay["app"]["windows"][0]["title"] == identity["displayName"],
        "overlay display identity drifted",
    )
    coexistence = _git_json(root, PRODUCT_SOURCE, compiled["coexistenceManifestPath"])
    sim_rows = [row for row in coexistence["editions"] if row["editionId"] == "sim"]
    _require(len(sim_rows) == 1, "coexistence SIM row drifted")
    sim_row = sim_rows[0]
    _require(
        sim_row["installerProductName"] == identity["internalProductName"]
        and sim_row["displayName"] == identity["displayName"]
        and sim_row["installRoot"] == identity["defaultInstallRoot"]
        and sim_row["uninstallRegistryKey"] == identity["uninstallRegistryKey"]
        and sim_row["productRegistryKey"] == identity["productRegistryKey"]
        and sim_row["runtimeProfileId"] == "sim-only",
        "coexistence installer identity drifted",
    )

    comparison = plan["manifestComparison"]
    _require(
        comparison == {
            "manifestBundleIdentifier": "io.dronedream.desktop.sim",
            "manifestAppUserModelId": "io.dronedream.desktop.sim",
            "artifactBundleIdentifier": "io.dronedream.sim",
            "classification": (
                "artifact-specific-sim-alias-isolated-from-all-other-editions"
            ),
            "crossEditionCollision": False,
            "redLifecycleBlocking": False,
            "futureProductSourceMustReconcileBeforePromotion": True,
        },
        "manifest comparison drifted",
    )
    _require(
        sim_row["bundleIdentifier"] == comparison["manifestBundleIdentifier"]
        and sim_row["appUserModelId"] == comparison["manifestAppUserModelId"],
        "manifest alias evidence drifted",
    )

    isolation = plan["sameHostIsolation"]
    _require(
        isolation["mode"]
        == "app-only-edition-namespace-with-protected-state-parity"
        and isolation["traditionalVmProviderRequired"] is False
        and isolation["hostSnapshotRequired"] is False
        and isolation["protectedStateParityRequiredAfterEveryPhase"] is True
        and isolation["failClosedBeforeMutationOnPreconditionMismatch"] is True,
        "same-host isolation boundary drifted",
    )
    _require(
        isolation["temporaryEnvironment"]["TEMP"]
        == isolation["temporaryEnvironment"]["TMP"],
        "temporary roots diverged",
    )
    _require(
        "{runId}" in isolation["temporaryEnvironment"]["TEMP"],
        "temporary root is not owned",
    )

    owned = plan["ownedWriteSurface"]
    protected = plan["protectedSnapshot"]
    owned_names = {_normalized(item) for item in owned["paths"] + owned["registryKeys"]}
    protected_names = {
        _normalized(item)
        for item in protected["installAndDataPaths"] + protected["registryKeys"]
    }
    _require(not owned_names.intersection(protected_names), "owned/protected overlap")
    _require(
        identity["defaultInstallRoot"] in owned["paths"]
        and identity["uninstallRegistryKey"] in owned["registryKeys"]
        and identity["productRegistryKey"] in owned["registryKeys"],
        "owned SIM identity is incomplete",
    )
    _require(
        protected["captureRequiredImmediatelyBeforeExecution"] is True
        and protected["parityRequiredAfterFreshOverlayLaunchAndUninstall"] is True
        and protected["runtimeStartAllowed"] is False
        and protected["webView2InstallOrRepairAllowed"] is False
        and protected["protectedStateDeletionAllowed"] is False,
        "protected snapshot boundary drifted",
    )

    counts = plan["exactCounts"]
    _require(
        counts
        == {
            "freshInstallerInvocations": 1,
            "overlayInstallerInvocations": 1,
            "applicationLaunches": 1,
            "uninstallerInvocations": 1,
            "pkceBoundaryChecks": 1,
            "realTokenExchanges": 0,
            "runtimeStarts": 0,
            "px4Starts": 0,
            "gazeboStarts": 0,
            "hardwareActions": 0,
            "artifactBuilds": 0,
        },
        "exact RED counts drifted",
    )
    rollback = plan["rollback"]
    _require(
        rollback["mechanism"]
        == "verified-sim-uninstaller-then-owned-surface-reverification"
        and rollback["uninstallerPath"]
        == "%LOCALAPPDATA%/DroneDream-Sim/uninstall.exe"
        and rollback["uninstallerMustBelongToExactInstallRoot"] is True
        and rollback["maximumRollbackUninstallerInvocations"] == 1
        and rollback["manualProtectedStateDeletionAllowed"] is False
        and rollback["stopAfterFailureWithoutRetry"] is True,
        "rollback boundary drifted",
    )
    _require(
        plan["authorization"]
        == {
            "planOnlyAuthorized": True,
            "redExecutionAuthorizedByThisRecord": False,
            "newChiefControlRedSignalRequired": True,
        },
        "RED authorization overclaim",
    )
    _assert_false_values(plan["nonClaims"], "plan nonClaims")

    if require_local_evidence:
        artifact_path = Path(artifact["path"])
        receipt_path = Path(artifact["buildReceiptPath"])
        nsi_path = Path(compiled["generatedNsiPath"])
        _require(artifact_path.is_file(), "frozen artifact missing")
        _require(artifact_path.stat().st_size == ARTIFACT_BYTES, "local artifact bytes drifted")
        _require(_sha256(artifact_path) == ARTIFACT_SHA256, "local artifact SHA drifted")
        _require(
            _sha256(receipt_path) == artifact["buildReceiptSha256"],
            "build receipt SHA drifted",
        )
        build_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        _require(
            build_receipt["productSourceCommit"] == PRODUCT_SOURCE,
            "build receipt product source drifted",
        )
        _require(nsi_path.is_file(), "generated NSI evidence missing")
        _require(
            nsi_path.stat().st_size == compiled["generatedNsiBytes"],
            "generated NSI bytes drifted",
        )
        _require(_sha256(nsi_path) == compiled["generatedNsiSha256"], "generated NSI SHA drifted")
        nsi = nsi_path.read_text(encoding="utf-8")
        for required in (
            '!define PRODUCTNAME "DroneDream-Sim"',
            '!define INSTALLMODE "currentUser"',
            '!define MAINBINARYNAME "drone-dream-desktop"',
            '!define BUNDLEID "io.dronedream.sim"',
            'WriteRegStr SHCTX "${UNINSTKEY}" "MainBinaryName" "${MAINBINARYNAME}.exe"',
            'WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${DRONEDREAM_DISPLAYNAME}"',
            'WriteRegStr SHCTX "${UNINSTKEY}" "InstallLocation" "$\\"$INSTDIR$\\""',
            "DRONEDREAM_CREATE_OR_UPDATE_STARTMENU_SHORTCUT",
            "DRONEDREAM_CREATE_OR_UPDATE_DESKTOP_SHORTCUT",
        ):
            _require(required in nsi, f"generated NSI identity drifted: {required}")
    return plan


def validate_receipt(
    receipt: dict[str, Any], plan: dict[str, Any], plan_path: Path
) -> dict[str, Any]:
    _require(receipt.get("schemaVersion") == 1, "receipt schema drifted")
    _require(receipt.get("kind") == RECEIPT_KIND, "receipt kind drifted")
    _require(receipt.get("editionId") == "sim", "receipt edition drifted")
    _require(
        receipt.get("state") == "green-plan-only-ready-for-red-request",
        "receipt state drifted",
    )
    _require(receipt["plan"]["path"] == plan_path.as_posix(), "receipt plan path drifted")
    _require(receipt["plan"]["sha256"] == _sha256(plan_path), "receipt plan SHA drifted")
    _require(receipt["sourceSeparation"] == plan["sourceSeparation"], "receipt source relabelled")
    _require(receipt["artifact"] == plan["artifact"], "receipt artifact drifted")
    _require(receipt["plannedExactCounts"] == plan["exactCounts"], "receipt counts drifted")
    _require(
        receipt["executedExactCounts"]
        == {key: 0 for key in plan["exactCounts"]},
        "execution count overclaim",
    )
    _require(receipt["installationCount"] == 0, "installation count overclaim")
    _require(receipt["remainingGate"] == "new-chief-control-red-signal", "remaining gate drifted")
    _assert_false_values(receipt["nonClaims"], "receipt nonClaims")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--require-local-evidence", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    plan_path = args.plan.resolve()
    plan = validate_plan(
        json.loads(plan_path.read_text(encoding="utf-8")),
        root,
        require_local_evidence=args.require_local_evidence,
    )
    if args.receipt:
        validate_receipt(
            json.loads(args.receipt.read_text(encoding="utf-8")),
            plan,
            plan_path.relative_to(root),
        )
    print(
        json.dumps(
            {
                "artifactSha256": ARTIFACT_SHA256,
                "installationCount": 0,
                "planOnly": True,
                "valid": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
