from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "distribution/build-profiles/universal-1.0.0.v1.json"
OVERLAY = ROOT / "desktop/src-tauri/tauri.universal.conf.json"
SCRIPT = ROOT / "desktop/scripts/build-universal-installer.ps1"
FINALIZER = ROOT / "desktop/scripts/finalize-existing-universal-candidate.ps1"
LIFECYCLE = ROOT / "desktop/scripts/verify-universal-installer-lifecycle.ps1"
INSTALLER_UI = ROOT / "desktop/scripts/verify-installer-ui.ps1"
HANDOFF = ROOT / "distribution/universal/release/website-exact-exe-handoff.v1.json"
ENGINE_PACK_TOOL = ROOT / "engine-pack/tools/engine_pack.py"
BROWSER_AUTH_VERIFIER = ROOT / "desktop/scripts/verify-browser-auth-config.mjs"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _engine_pack_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "universal_contract_engine_pack",
        ENGINE_PACK_TOOL,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_ci_placeholder_cannot_bypass_oauth_client_registration() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "GITHUB_ACTIONS": "true",
            "VITE_SUPABASE_URL": "https://ci.invalid",
            "VITE_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_ci_contract",
            "DRONEDREAM_RELEASE_SOURCE_COMMIT": "fixture-source",
            "DRONEDREAM_DESKTOP_EDITION_ID": "universal",
        }
    )
    environment.pop("DRONEDREAM_OAUTH_CLIENT_ID", None)
    result = subprocess.run(
        ["node", str(BROWSER_AUTH_VERIFIER)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "registered public DRONEDREAM_OAUTH_CLIENT_ID" in result.stderr


def test_universal_profile_binds_fixed_identity_and_denies_frontend_authority() -> None:
    profile = _json(PROFILE)
    assert profile["artifactFileName"] == "DroneDream-Universal-1.0.0.exe"
    assert profile["enginePackProfile"] == "unified-sim-lab"
    payload = profile["enginePackPayloadContract"]
    assert payload["contractId"] == "dronedream-universal-engine-payload/v1"  # type: ignore[index]
    assert payload["requiredEditionIds"] == ["sim", "lab", "field"]  # type: ignore[index]
    assert payload["profileIdIsCompatibilityIdentity"] is True  # type: ignore[index]
    assert payload["uiModeNeverGrantsCapability"] is True  # type: ignore[index]
    assert profile["workspaceModes"] == ["universal", "sim", "lab", "field"]
    desktop_contracts = profile["desktopContracts"]
    assert desktop_contracts == {  # type: ignore[comparison-overlap]
        "coexistence": "distribution/desktop/edition-coexistence.v1.json",
        "browserAuth": "distribution/desktop/edition-browser-auth.v1.json",
        "runtimeAndUpdaterFamilies": (
            "distribution/desktop/edition-runtime-update-families.v1.json"
        ),
        "editionId": "universal",
        "authClientId": "dronedream-desktop-universal",
        "bundleIdentifier": "io.dronedream.desktop.universal",
        "credentialVaultNamespace": "DroneDream/Auth/universal/v1",
        "updaterMetadataFileName": "latest-universal.json",
    }
    assert profile["brand"]["presentationOnly"] is True  # type: ignore[index]
    assert profile["brand"]["grantsHardwareAuthority"] is False  # type: ignore[index]
    authority = profile["capabilityAuthority"]
    assert authority["frontendCanAuthorize"] is False  # type: ignore[index]
    assert authority["validatedVehiclePackCount"] == 0  # type: ignore[index]
    assert authority["hardwareActionDecision"] == "deny"  # type: ignore[index]


def test_universal_overlay_uses_mother_brand_and_canonical_windows_icon() -> None:
    overlay = _json(OVERLAY)
    assert overlay["productName"] == "DroneDream-Universal"
    assert overlay["app"]["windows"][0]["title"] == "DroneDream"  # type: ignore[index]
    assert "../../brand/generated/universal/windows/icon.ico" in overlay["bundle"]["icon"]  # type: ignore[index]
    resources = overlay["bundle"]["resources"]  # type: ignore[index]
    assert resources["../../distribution/desktop/edition-coexistence.v1.json"] == (  # type: ignore[index]
        "distribution/desktop/edition-coexistence.v1.json"
    )
    assert resources["../../distribution/desktop/edition-browser-auth.v1.json"] == (  # type: ignore[index]
        "distribution/desktop/edition-browser-auth.v1.json"
    )
    assert resources[
        "../../distribution/desktop/edition-runtime-update-families.v1.json"
    ] == "distribution/desktop/edition-runtime-update-families.v1.json"  # type: ignore[index]


def test_universal_engine_payload_contains_all_editions_without_build_plans() -> None:
    engine_pack = _engine_pack_module()
    files = engine_pack.production_files(
        ROOT,
        edition_profile=engine_pack.DEFAULT_EDITION_PROFILE,
    )
    paths = {path for path, _source in files}
    assert {
        "distribution/editions/sim.v1.json",
        "distribution/editions/lab.v1.json",
        "distribution/editions/field.v1.json",
        "distribution/desktop/edition-coexistence.v1.json",
        "distribution/desktop/edition-browser-auth.v1.json",
        "distribution/desktop/edition-runtime-update-families.v1.json",
        "distribution/safety/edition-execution-gate.v1.json",
        "distribution/vehicle-packs/registry.v1.json",
    } <= paths
    assert not any(
        path == prefix or path.startswith(f"{prefix}/")
        for path in paths
        for prefix in (
            "distribution/build-planning",
            "distribution/build-plans",
            "distribution/tests",
        )
    )


def test_universal_build_is_single_source_bound_signed_attempt_with_external_target() -> None:
    script = SCRIPT.read_text(encoding="utf-8-sig")
    for fragment in (
        '[string]$ExpectedSourceCommit',
        'Universal builds require an explicit -ExpectedSourceCommit pin.',
        'Universal HEAD does not match ExpectedSourceCommit.',
        'explicitSourcePinRequiredForBuild = $true',
        '$branch -cne "codex/software"',
        'Universal builds require an exact clean source tree.',
        'DroneDream-Universal-1.0.0.exe',
        'universal-cargo-target',
        '$env:DRONEDREAM_EDITION_PROFILE = "unified-sim-lab"',
        '$env:DRONEDREAM_DESKTOP_EDITION_ID = "universal"',
        '$env:VITE_DRONEDREAM_EDITION = "universal"',
        '$browserAuth.identityBinding.contractSha256 -cne $coexistenceSha256',
        '$browserAuthIdentity.authClientId -cne $coexistenceIdentity.authClientId',
        'Universal browser sign-in requires its registered public DRONEDREAM_OAUTH_CLIENT_ID.',
        'providerOAuthClientIdSha256 = $providerOAuthClientIdSha256',
        'browserAuthStatus = "pending-exact-headed-roundtrip-validation"',
        'Universal updater signing requires TAURI_SIGNING_PRIVATE_KEY_PATH.',
        'buildCount = 1',
        '$buildReceiptPath = "${artifactPath}.receipt.json"',
        '$updaterMetadataPath = Join-Path $releaseMetadataDirectory "latest-universal.json"',
        'desktop-universal-v1\\.0\\.0-build-',
        'publishedWithWebsiteFiles = $false',
        'payloadContractId = "dronedream-universal-engine-payload/v1"',
        'Multiple incompatible Universal Engine Pack manifests were produced.',
        "-AdditionalConfigPath $overlayPath",
        "-CargoTargetDir $cargoTargetFull",
        "-ExpectedProductName ([string]$overlay.productName)",
        '-EditionId "universal"',
        'releaseReady = $false',
        'pending-isolated-red-validation',
    ):
        assert fragment in script
    assert "-AllowUnsignedUpdater" not in script
    assert "$sharedArguments" not in script
    assert '$env:DRONEDREAM_OAUTH_CLIENT_ID =' not in script
    assert script.index('Universal builds require an explicit -ExpectedSourceCommit pin.') < (
        script.index('Universal updater signing requires TAURI_SIGNING_PRIVATE_KEY_PATH.')
    )


def test_website_contract_publishes_exact_four_files_without_rename() -> None:
    handoff = _json(HANDOFF)
    assert handoff["artifactIdentity"]["fileName"] == "DroneDream-Universal-1.0.0.exe"  # type: ignore[index]
    assert handoff["recipient"]["behavior"] == "read-only-receive-no-rebuild-no-rename"  # type: ignore[index]
    assert handoff["publishedFiles"] == [
        "DroneDream-Universal-1.0.0.exe",
        "DroneDream-Universal-1.0.0.exe.sha256",
        "DroneDream-Universal-1.0.0.exe.sig",
        "DroneDream-Universal-1.0.0.exe.receipt.json",
    ]
    assert handoff["consistency"]["updaterSignatureRequired"] is True  # type: ignore[index]
    assert handoff["consistency"]["installerLifecycleAndBrowserAuthReceiptsRequired"] is True  # type: ignore[index]
    assert handoff["consistency"]["crossEditionDesktopSessionReuseAllowed"] is False  # type: ignore[index]
    assert "browserAuthBoundary" in handoff["requiredHandoffFields"]


def test_existing_candidate_finalizer_preserves_product_source_and_never_rebuilds() -> None:
    finalizer = FINALIZER.read_text(encoding="utf-8-sig")
    for fragment in (
        'ValidatePattern("^[0-9a-f]{40}$")',
        'DroneDream-Universal_1.0.0_x64-setup.exe',
        'DroneDream-Universal-1.0.0.exe',
        'finalizerToolHeadIsProductSource = $false',
        'candidate-awaiting-isolated-red-lifecycle-validation',
        'rebuildProhibited -ne $true',
        'exactCleanProductSourceCommit = $ProductSourceCommit',
        'buildCount = 1',
        'releaseReady = $false',
    ):
        assert fragment in finalizer
    assert "tauri build" not in finalizer
    assert "npm.cmd" not in finalizer
    assert "engine_pack.py" not in finalizer


def test_universal_lifecycle_verifier_is_exact_byte_bound_and_isolated() -> None:
    lifecycle = LIFECYCLE.read_text(encoding="utf-8-sig")
    for fragment in (
        'ValidatePattern("^[0-9a-f]{40}$")',
        'ValidatePattern("^[0-9a-f]{64}$")',
        'DroneDream-Universal-1.0.0.exe',
        'DroneDream-Universal',
        'io.dronedream.desktop.universal',
        'install-app-only',
        'hardwareActionDecision -cne "deny"',
        'distribution\\desktop\\edition-coexistence.v1.json',
        'distribution\\desktop\\edition-browser-auth.v1.json',
        'distribution\\desktop\\edition-runtime-update-families.v1.json',
        'browserAuthIdentity[0].authClientId -cne "dronedream-desktop-universal"',
        'dronedream-vehicle-pack-registry',
        '$registry.packs',
        '$_.currentValidationTier',
        'validatedVehiclePackCount = 0',
        '@("/S", "/NS", "/L=1033")',
        '@("/S", "/NS", "/UPDATE", "/L=1033")',
        'Close it before isolated lifecycle validation; the verifier will never terminate it.',
        'Universal lifecycle preflight found pre-existing product state',
        'Protected existing DroneDream, Runtime, shortcut, registry, or WebView2 state changed',
        'releaseReady = $false',
        'installerLifecycleReady = $true',
        'browserAuth = "not-run-separate-headed-gate"',
        'if ($Execute)',
    ):
        assert fragment in lifecycle
    assert "Stop-Process" not in lifecycle
    assert "tauri build" not in lifecycle
    assert "npm.cmd" not in lifecycle
    assert "engine_pack.py" not in lifecycle
    assert "releaseReady = $true" not in lifecycle


def test_visible_locale_verifier_handles_language_selector_in_edition_namespace() -> None:
    verifier = INSTALLER_UI.read_text(encoding="utf-8-sig")
    for fragment in (
        '[ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]',
        '[string]$InstallerProductName = "DroneDream"',
        '"HKCU:\\Software\\DroneDream\\$InstallerProductName"',
        '"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\$InstallerProductName"',
        '[DroneDreamInstallerUi]::GetDlgItem($handle, 1002)',
        '$languageIndex = if ($Language -eq "English") { 0 } else { 1 }',
        'SendMessage($languageCombo, $CB_SETCURSEL',
        'Invoke-DialogButton -Dialog $entryPage.Handle -ControlId 1',
        '$installerArguments += "/DRONEDREAMVALIDATEPATHONLY"',
        'The installer path-only validation did not exit',
    ):
        assert fragment in verifier
    assert 'HKCU:\\Software\\DroneDream\\DroneDream"' not in verifier
