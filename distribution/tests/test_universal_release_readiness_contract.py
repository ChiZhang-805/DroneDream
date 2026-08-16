from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINALIZER = ROOT / "desktop" / "scripts" / "finalize-universal-release-readiness.ps1"


def test_finalizer_requires_every_same_artifact_gate() -> None:
    text = FINALIZER.read_text(encoding="utf-8")
    for parameter in (
        "BuildReceipt",
        "BuildManifest",
        "LifecycleReceipt",
        "VisibleInstallerReceipt",
        "InstalledAppReceipt",
        "OAuthReceipt",
        "IconReceipt",
    ):
        assert f"[string]${parameter}" in text
        assert f"Expected{parameter}Sha256" in text
    assert text.count("Assert-ArtifactIdentity") >= 6
    assert '$Artifact.PSObject.Properties["absolutePath"]' in text
    assert '$Artifact.PSObject.Properties["path"]' in text
    assert 'buildCount -ne 1' in text
    assert 'authenticode.Status -cne "NotSigned"' in text


def test_finalizer_preserves_atomic_receipts_and_emits_new_immutable_outputs() -> None:
    text = FINALIZER.read_text(encoding="utf-8")
    assert "$boundBuildManifest = Read-BoundJson $BuildManifest" in text
    assert "$buildManifest = Read-BoundJson $BuildManifest" not in text
    assert "Set-Content -LiteralPath $BuildManifest" not in text
    assert "Set-Content -LiteralPath $BuildReceipt" not in text
    assert '"universal-final-readiness-receipt.json"' in text
    assert '"universal-final-handoff-manifest.json"' in text
    assert '"website-exact-exe-handoff.final.v1.json"' in text
    assert 'releaseReady = $true' in text
    assert 'deploymentPerformed = $false' in text
    assert 'websiteMustNotRebuildOrRename = $true' in text
    assert '$finalReadinessRecord = [ordered]@{' in text
    assert '$finalManifestRecord = [ordered]@{' in text
    assert 'readinessReceipt = $finalReadinessRecord' in text
    assert 'receiptPath = $finalReadinessRecord.path' in text
    assert 'manifestPath = $finalManifestRecord.path' in text
    assert '.Replace($stagingRoot, $outputRootFull)' not in text
    assert 'if ($pendingJson.Contains(".staging-"))' in text
    assert 'Final handoff output failed its post-move path and hash verification.' in text


def test_finalizer_verifies_real_oauth_ui_cleanup_and_icon_surfaces() -> None:
    text = FINALIZER.read_text(encoding="utf-8")
    assert '$oauth.Document.PSObject.Properties["failure"]' in text
    assert "$oauth.Document.failure" not in text
    for fragment in (
        "$oauth.Document.counts.credentialVaultRestoreProbe -ne 1",
        "$oauth.Document.counts.authorizationCodeExchange -ne 1",
        "$oauth.Document.counts.authenticatedUiCases -ne 16",
        "$oauth.Document.counts.settingsTabActivations -ne 64",
        "$oauth.Document.authEvidence.rawCallbackRecorded -ne $false",
        "$oauth.Document.authEvidence.credentialsRecorded -ne $false",
        "$oauth.Document.runtimeRestoreObserved -ne $true",
        "protectedStateBefore",
        "protectedStateAfter",
        "@($icons.Document.surfaces).Count -ne 4",
        "$icons.Document.protectedShortcutParity -ne $true",
        'iconInstallerAppDesktopStartMenu = "passed"',
    ):
        assert fragment in text


def test_finalizer_keeps_hardware_and_publication_fail_closed() -> None:
    text = FINALIZER.read_text(encoding="utf-8")
    assert 'validatedVehiclePackCount = 0' in text
    assert 'hardwareActionDecision = "deny"' in text
    assert 'presentationSwitchGrantsAuthority = $false' in text
    assert 'publicWebsiteDeployment = "not-performed-awaiting-user-command"' in text
    assert 'state = "release-ready-awaiting-website-deployment-command"' in text
