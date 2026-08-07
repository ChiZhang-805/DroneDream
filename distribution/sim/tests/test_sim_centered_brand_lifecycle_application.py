from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APPLICATION = (
    ROOT
    / "distribution"
    / "sim"
    / "lifecycle"
    / "red-54bc1bb9-final-application.v1.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_centered_brand_lifecycle_application_is_exact_and_single_execution() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    artifact = application["artifact"]
    runner = application["runner"]
    runner_path = ROOT / runner["path"]
    static_path = ROOT / artifact["staticAcceptancePath"]

    assert application["sourceSeparation"]["productSourceCommit"] == (
        "4c0021b28161a9fa2210e6deab0edab2e4f8372d"
    )
    assert artifact["sha256"] == (
        "54bc1bb939786bbc26f7f9c05a1c831b13b9434338ed62c5a88a59a4f72faf80"
    )
    assert static_path.stat().st_size == artifact["staticAcceptanceBytes"]
    assert sha256(static_path) == artifact["staticAcceptanceSha256"]
    assert runner_path.stat().st_size == runner["bytes"]
    assert sha256(runner_path) == runner["sha256"]
    assert runner["maximumExecuteInvocations"] == 1
    assert runner["automaticRetryAllowed"] is False
    assert application["priorArtifact"]["reuseRelabelOrWebsiteHandoffAllowed"] is False


def test_centered_brand_lifecycle_matrix_remains_fail_closed() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    counts = application["acceptanceMatrix"]["exactMaximumCounts"]
    for key in (
        "freshInstallerInvocations",
        "overlayInstallerInvocations",
        "applicationLaunches",
        "uninstallerInvocations",
        "pkceBoundaryChecks",
        "installerLanguagePreferenceCleanupWrites",
    ):
        assert counts[key] == 1
    for key in (
        "browserLoginTransactions",
        "realTokenExchanges",
        "credentialReads",
        "runtimeStarts",
        "px4Starts",
        "gazeboStarts",
        "hardwareActions",
        "artifactBuilds",
        "automaticRetries",
    ):
        assert counts[key] == 0
    assert application["ownedSurface"]["installRoot"] == "%LOCALAPPDATA%/DroneDream-Sim"
    assert application["ownedSurface"]["desktopShortcut"].endswith(
        "DroneDream · SIM.lnk"
    )
    assert application["protectedState"]["parityAfterEveryPhase"] is True
    assert application["rollback"]["manualProtectedStateDeletionAllowed"] is False
    assert application["oauthBoundary"]["callback"].endswith(
        "/desktop-auth/sim/callback"
    )
    assert application["oauthBoundary"]["realTokenExchangeAllowed"] is False
    assert application["authorization"]["websiteDeploymentAuthorized"] is False
