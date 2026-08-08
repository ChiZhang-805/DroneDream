from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "distribution/build-profiles/universal-1.0.0.v1.json"
INTEGRATED_WORKSPACES = ROOT / "distribution/universal/integrated-workspaces.v2.json"
OVERLAY = ROOT / "desktop/src-tauri/tauri.universal.conf.json"
SCRIPT = ROOT / "desktop/scripts/build-universal-installer.ps1"
FINALIZER = ROOT / "desktop/scripts/finalize-existing-universal-candidate.ps1"
LIFECYCLE = ROOT / "desktop/scripts/verify-universal-installer-lifecycle.ps1"
LIFECYCLE_CONTRACT = ROOT / "desktop/scripts/edition-installer-lifecycle-contract.ps1"
INSTALLER_UI = ROOT / "desktop/scripts/verify-installer-ui.ps1"
VISIBLE_INSTALLER_UI = ROOT / "desktop/scripts/verify-universal-visible-installer-ui.ps1"
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


def test_visible_installer_receipt_is_exact_source_bound_and_never_commits() -> None:
    text = VISIBLE_INSTALLER_UI.read_text(encoding="utf-8")
    for fragment in (
        'ValidatePattern("^[0-9a-f]{40}$")',
        'ValidatePattern("^[0-9a-f]{64}$")',
        'Get-GitText @("status", "--porcelain")',
        "Product source is not an ancestor",
        "Frozen Universal artifact drifted",
        "Refusing to overwrite an existing visible installer receipt",
        'foreach ($language in @("English", "SimpChinese"))',
        '"-SimulateFreshInstall", "-ValidatePathGuard"',
        'installationCommits = 0',
        'visibleInstallerUiReady = $true',
    ):
        assert fragment in text
    assert "-RedirectStandardOutput" in text
    assert "-RedirectStandardError" in text


def test_universal_profile_binds_fixed_identity_and_denies_frontend_authority() -> None:
    profile = _json(PROFILE)
    assert profile["artifactFileName"] == "DroneDream-Universal-1.0.0.exe"
    assert profile["enginePackProfile"] == "unified-sim-lab"
    payload = profile["enginePackPayloadContract"]
    assert payload["contractId"] == "dronedream-universal-engine-payload/v1"  # type: ignore[index]
    assert payload["requiredEditionIds"] == ["sim", "lab", "field"]  # type: ignore[index]
    assert payload["profileIdIsCompatibilityIdentity"] is True  # type: ignore[index]
    assert payload["uiModeNeverGrantsCapability"] is True  # type: ignore[index]
    assert profile["workspaceModes"] == ["sim", "lab", "field"]
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
    shared_ui = profile["sharedUiContract"]
    assert shared_ui["contractId"] == "dronedream-shared-edition-ui/v1"  # type: ignore[index]
    assert shared_ui["donorCommit"] == (  # type: ignore[index]
        "62ac2345828f50a221c1aaed0ea7273a628c9d5d"
    )
    assert shared_ui["minimumDesktopViewport"] == {  # type: ignore[index]
        "width": 390,
        "height": 700,
        "scalePercent": 100,
    }
    assert shared_ui["settingsDialogVerticalOverflowAllowed"] is False  # type: ignore[index]
    assert shared_ui["activeSettingsPanelVerticalOverflowAllowed"] is False  # type: ignore[index]
    assert shared_ui["presentationOnly"] is True  # type: ignore[index]
    assert shared_ui["grantsHardwareAuthority"] is False  # type: ignore[index]
    assert shared_ui["fieldLightweightEntryIntegrationStatus"] == (  # type: ignore[index]
        "integrated-in-universal"
    )
    visual = shared_ui["visualEvidence"]  # type: ignore[index]
    assert visual["subjectCommit"] == "4933e214a57a048099d8f0bdd11c9748b620ac3e"
    assert visual["subjectCommit"] != shared_ui["donorCommit"]
    assert visual["caseCount"] == 6
    assert visual["locales"] == ["en", "zh-CN"]
    assert visual["viewportWidths"] == [390, 760, 1440]
    assert visual["coveredSettingsTabs"] == ["general", "memory", "model"]
    assert visual["runtimePanelHeadedValidationStatus"] == (
        "pending-exact-desktop-runtime-red-validation"
    )
    source_files = shared_ui["sourceFiles"]  # type: ignore[index]
    assert len(source_files) == 7
    for source_file in source_files:
        path = ROOT / source_file["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source_file["sha256"]
    integrated_ui = profile["integratedWorkspaceUiContract"]
    assert integrated_ui == {  # type: ignore[comparison-overlap]
        "contractId": "dronedream-universal-integrated-workspaces/v2",
        "manifest": "distribution/universal/integrated-workspaces.v2.json",
        "sha256": hashlib.sha256(INTEGRATED_WORKSPACES.read_bytes()).hexdigest(),
        "sourceFileCount": 12,
        "workspaceModes": ["sim", "lab", "field"],
        "createsCrossEditionHarnessOrchestrator": False,
        "presentationOnly": True,
        "grantsHardwareAuthority": False,
    }
    integrated_manifest = _json(INTEGRATED_WORKSPACES)
    assert integrated_manifest["workspaceSwitchMeaning"] == (
        "presentation-and-module-selection-only"
    )
    assert integrated_manifest["createsCrossEditionHarnessOrchestrator"] is False
    assert integrated_manifest["validatedVehiclePackCount"] == 0
    assert integrated_manifest["hardwareActionDecision"] == "deny"
    assert integrated_manifest["donors"]["lab"]["productSource"] == (  # type: ignore[index]
        "b3c5f90948f206472e3e12504d8205cb563ac9dc"
    )
    assert integrated_manifest["donors"]["lab"]["evidenceHeadIsProductSource"] is False  # type: ignore[index]
    assert integrated_manifest["donors"]["field"]["productSource"] == (  # type: ignore[index]
        "7d3d0c34d0e385d88312db34601667a384ecc9c5"
    )
    integrated_sources = integrated_manifest["sourceFiles"]  # type: ignore[index]
    assert len(integrated_sources) == 12
    integration_by_path = {item["path"]: item["integration"] for item in integrated_sources}
    assert integration_by_path["frontend/src/field/FieldApp.tsx"] == (
        "semantic-universal-shared-locale-adapter"
    )
    assert integration_by_path["frontend/src/router.tsx"] == (
        "semantic-universal-workspace-routing-and-shared-locale"
    )
    for source_file in integrated_sources:
        path = ROOT / source_file["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source_file["sha256"]
        if source_file["integration"] == "byte-exact":
            actual_blob = subprocess.run(
                ["git", "hash-object", "--", source_file["path"]],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            assert actual_blob == source_file["donorBlob"]
    vehicle_studio = profile["universalExclusiveCapabilities"]["vehicleStudio"]
    assert vehicle_studio["ownerEdition"] == "universal"
    assert vehicle_studio["shareTargets"] == ["sim", "lab", "field"]
    assert vehicle_studio["automaticReceiverInstallation"] is False
    assert vehicle_studio["modelHarnessStartsOnExchange"] is False
    assert vehicle_studio["grantsSimulationExecution"] is False
    assert vehicle_studio["grantsHardwareAuthority"] is False
    assert vehicle_studio["productSourceCommit"] == (
        "81550b94270ee4e47eed7d520fb8280bd3a8ee7b"
    )
    for source_file in vehicle_studio["sourceFiles"]:
        path = ROOT / source_file["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source_file["sha256"]
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
        'dronedream-shared-edition-ui/v1',
        'Invoke-GitText @("merge-base", "--is-ancestor"',
        'visualEvidenceSubjectCommit = [string]$sharedUi.visualEvidence.subjectCommit',
        'Universal shared UI source binding drifted:',
        'Universal shared UI visual evidence hash drifted.',
        'dronedream-universal-integrated-workspaces/v2',
        '$integratedUi.sourceFileCount -ne 12',
        'Universal integrated workspace manifest hash drifted.',
        'Universal integrated workspace source binding drifted:',
        'Universal integrated workspace byte-exact donor drifted:',
        'createsCrossEditionHarnessOrchestrator = $false',
        'integratedWorkspaceUi = [ordered]@{',
        'Universal Vehicle Studio identity or safety policy drifted.',
        'Universal Vehicle Studio source binding drifted:',
        'Universal Vehicle Studio contract must bind exactly ten source files.',
        'vehicleStudio = [ordered]@{',
        'dialogScrollHeight -gt $measurement.dialogClientHeight',
        'panelScrollHeight -gt $measurement.panelClientHeight',
        'runtimePanelHeadedValidationStatus',
        'fieldLightweightEntryIntegrationStatus',
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
        'edition-installer-lifecycle-contract.ps1',
        'productRegistrationAfterStandardUninstall = "retained-unless-delete-app-data-selected"',
    ):
        assert fragment in lifecycle
    assert "Stop-Process" not in lifecycle
    assert "tauri build" not in lifecycle
    assert "npm.cmd" not in lifecycle
    assert "engine_pack.py" not in lifecycle
    assert "releaseReady = $true" not in lifecycle


def _run_lifecycle_contract(expression: str) -> subprocess.CompletedProcess[str]:
    command = (
        f". '{LIFECYCLE_CONTRACT}'; "
        "$ErrorActionPreference='Stop'; "
        f"{expression}"
    )
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "edition",
    _json(ROOT / "distribution/desktop/edition-coexistence.v1.json")["editions"],
)
def test_shared_lifecycle_contract_accepts_all_edition_identities(
    edition: dict[str, object],
) -> None:
    display_name = str(edition["displayName"]).replace("'", "''")
    product_name = str(edition["installerProductName"])
    install_directory = f"C:\\Users\\Example\\AppData\\Local\\{product_name}"
    result = _run_lifecycle_contract(
        f"$e=[ordered]@{{DisplayName='{display_name}';DisplayVersion='1.0.0';"
        f"InstallLocation='{install_directory}';"
        "MainBinaryName='drone-dream-desktop.exe'};"
        f"$a=[ordered]@{{DisplayName='{display_name}';DisplayVersion='1.0.0';"
        f"InstallLocation='\"{install_directory.lower()}\\\"';"
        "MainBinaryName='drone-dream-desktop.exe'};"
        "$r=Compare-DroneDreamUninstallRegistration -Expected $e -Actual $a;"
        "if(-not $r.passed -or $r.mismatches.Count -ne 0){exit 9}"
    )
    assert result.returncode == 0, result.stderr


def test_shared_lifecycle_contract_reports_fields_before_failure() -> None:
    result = _run_lifecycle_contract(
        "$e=[ordered]@{DisplayName='DroneDream · LAB';DisplayVersion='1.0.0';"
        "InstallLocation='C:\\Users\\Example\\AppData\\Local\\DroneDream-Lab';"
        "MainBinaryName='drone-dream-desktop.exe'};"
        "$a=[ordered]@{DisplayName='DroneDream-Lab';DisplayVersion='1.0.0';"
        "InstallLocation='C:\\Users\\Example\\AppData\\Local\\DroneDream-Lab';"
        "MainBinaryName='drone-dream-desktop.exe'};"
        "$r=Compare-DroneDreamUninstallRegistration -Expected $e -Actual $a;"
        "if($r.passed -or $r.mismatches.Count -ne 1 "
        "-or $r.mismatches[0] -cne 'DisplayName'){exit 9}"
    )
    assert result.returncode == 0, result.stderr

    unknown = _run_lifecycle_contract(
        "$e=[ordered]@{DisplayName='DroneDream';DisplayVersion='1.0.0';"
        "InstallLocation='C:\\Users\\Example\\AppData\\Local\\DroneDream-Universal';"
        "MainBinaryName='drone-dream-desktop.exe';Unexpected='value'};"
        "$a=[ordered]@{DisplayName='DroneDream';DisplayVersion='1.0.0';"
        "InstallLocation='C:\\Users\\Example\\AppData\\Local\\DroneDream-Universal';"
        "MainBinaryName='drone-dream-desktop.exe'};"
        "Compare-DroneDreamUninstallRegistration -Expected $e -Actual $a"
    )
    assert unknown.returncode != 0
    assert "fields drifted" in unknown.stderr


def test_shared_lifecycle_contract_allows_only_owned_product_key_residue() -> None:
    accepted = _run_lifecycle_contract(
        "$v=[ordered]@{'(default)'='C:\\Users\\Example\\AppData\\Local\\DroneDream-Field';"
        "'DroneDreamRuntimeInstallMode'='install-app-only';"
        "'DroneDreamRuntimeDrive'='';'DroneDreamRuntimeOperationProtocol'=2};"
        "$r=Get-DroneDreamProductRegistrationDisposition -Values $v "
        "-ExpectedInstallDirectory 'c:\\users\\example\\appdata\\local\\DroneDream-Field' "
        "-PreflightProductKeyAbsent $true;"
        "if($r.state -cne 'retained-by-standard-uninstaller' "
        "-or -not $r.testHarnessRemovalAllowed){exit 9}"
    )
    assert accepted.returncode == 0, accepted.stderr

    rejected = _run_lifecycle_contract(
        "$v=[ordered]@{'(default)'='C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim';"
        "'ForeignValue'='do-not-delete'};"
        "Get-DroneDreamProductRegistrationDisposition -Values $v "
        "-ExpectedInstallDirectory 'C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim' "
        "-PreflightProductKeyAbsent $true"
    )
    assert rejected.returncode != 0
    assert "unowned values" in rejected.stderr

    wrong_owner = _run_lifecycle_contract(
        "$v=[ordered]@{'(default)'='C:\\Users\\Example\\AppData\\Local\\DroneDream-Lab';"
        "'DroneDreamRuntimeInstallMode'='install-app-only'};"
        "Get-DroneDreamProductRegistrationDisposition -Values $v "
        "-ExpectedInstallDirectory 'C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim' "
        "-PreflightProductKeyAbsent $true"
    )
    assert wrong_owner.returncode != 0
    assert "different install directory" in wrong_owner.stderr

    preexisting = _run_lifecycle_contract(
        "$v=[ordered]@{'(default)'='C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim'};"
        "Get-DroneDreamProductRegistrationDisposition -Values $v "
        "-ExpectedInstallDirectory 'C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim' "
        "-PreflightProductKeyAbsent $false"
    )
    assert preexisting.returncode != 0
    assert "existed at preflight" in preexisting.stderr


def test_visible_locale_verifier_handles_language_selector_in_edition_namespace() -> None:
    verifier = INSTALLER_UI.read_text(encoding="utf-8-sig")
    for fragment in (
        '[ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]',
        '[string]$InstallerProductName = "DroneDream"',
        '"HKCU:\\Software\\DroneDream\\$InstallerProductName"',
        '"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\$InstallerProductName"',
        '"Registry::HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\$InstallerProductName"',
        '"Registry::HKEY_CURRENT_USER\\Software\\DroneDream\\$InstallerProductName"',
        "Test-Path -LiteralPath $entry.ProviderPath",
        "& reg.exe export $key $backup /y *> $null",
        "& reg.exe delete $key /f *> $null",
        'throw "Could not back up installer registration \'$key\'"',
        'throw "Could not suspend installer registration \'$key\'"',
        '[DroneDreamInstallerUi]::GetDlgItem($handle, 1002)',
        '$languageIndex = if ($Language -eq "English") { 0 } else { 1 }',
        'SendMessage($languageCombo, $CB_SETCURSEL',
        'Invoke-DialogButton -Dialog $entryPage.Handle -ControlId 1',
        '$installerArguments += "/DRONEDREAMVALIDATEPATHONLY"',
        'The installer path-only validation did not exit',
    ):
        assert fragment in verifier
    assert 'HKCU:\\Software\\DroneDream\\DroneDream"' not in verifier
    assert "reg.exe query" not in verifier


def _run_installer_ui_registration_guard(body: str) -> subprocess.CompletedProcess[str]:
    verifier_path = str(INSTALLER_UI).replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop';"
        "$tokens=$null;$parseErrors=$null;"
        f"$ast=[Management.Automation.Language.Parser]::ParseFile('{verifier_path}',"
        "[ref]$tokens,[ref]$parseErrors);"
        "if($parseErrors.Count -ne 0){exit 8};"
        "$wanted=@('Suspend-DroneDreamRegistration','Restore-DroneDreamRegistration');"
        "$functions=$ast.FindAll({param($node) "
        "$node -is [Management.Automation.Language.FunctionDefinitionAst] "
        "-and $wanted -contains $node.Name},$true);"
        "if($functions.Count -ne 2){exit 8};"
        "$functions | ForEach-Object { Invoke-Expression $_.Extent.Text };"
        "$InstallerProductName=('DroneDream-UiGuard-' + [Guid]::NewGuid().ToString('N'));"
        "$script:registryBackups=@();"
        + body
    )
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_visible_locale_registration_guard_accepts_absent_fresh_state() -> None:
    result = _run_installer_ui_registration_guard(
        "Suspend-DroneDreamRegistration;"
        "if($script:registryBackups.Count -ne 0){exit 9}"
    )
    assert result.returncode == 0, result.stderr


def test_visible_locale_registration_guard_round_trips_owned_registration() -> None:
    result = _run_installer_ui_registration_guard(
        "$owned=('HKCU:\\Software\\DroneDream\\' + $InstallerProductName);"
        "try {"
        "New-Item -Path $owned -Force | Out-Null;"
        "New-ItemProperty -Path $owned -Name 'ContractSentinel' -Value 'preserve' "
        "-PropertyType String -Force | Out-Null;"
        "Suspend-DroneDreamRegistration;"
        "if(Test-Path -LiteralPath $owned){exit 9};"
        "if($script:registryBackups.Count -ne 1){exit 9};"
        "Restore-DroneDreamRegistration;"
        "if(-not (Test-Path -LiteralPath $owned)){exit 9};"
        "$value=Get-ItemPropertyValue -LiteralPath $owned -Name 'ContractSentinel';"
        "if($value -cne 'preserve'){exit 9}"
        "} finally {"
        "Remove-Item -LiteralPath $owned -Recurse -Force -ErrorAction SilentlyContinue;"
        "$script:registryBackups | ForEach-Object {"
        "Remove-Item -LiteralPath $_.Backup -Force -ErrorAction SilentlyContinue"
        "}"
        "}"
    )
    assert result.returncode == 0, result.stderr
