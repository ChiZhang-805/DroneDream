from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "desktop" / "scripts" / "build-windows-llvm.ps1"
MSVC_SCRIPT = ROOT / "desktop" / "scripts" / "build-windows-msvc.ps1"
FOUR_EDITION_SCRIPT = ROOT / "desktop" / "scripts" / "build-four-edition-installers.ps1"
PLANNER_VERIFIER = ROOT / "desktop" / "scripts" / "verify-installer-planner.ps1"
RUNTIME_MODE_HOOK = ROOT / "desktop" / "src-tauri" / "nsis" / "runtime-mode.nsh"
INSTALLER_HOOK = ROOT / "desktop" / "src-tauri" / "nsis" / "webview2-health.nsh"
DRIVER = ROOT / "desktop" / "scripts" / "release-build-driver.psm1"
RELEASE_POLICY = ROOT / "desktop" / "scripts" / "verify-release-source-policy.mjs"
SIGNING_POLICY = ROOT / "desktop" / "scripts" / "verify-updater-signing-contract.ps1"
DETACHED_SCHEMA = ROOT / "distribution" / "schemas" / "desktop-node-dependency-bundle.schema.json"
DETACHED_VERIFIER = ROOT / "desktop" / "scripts" / "verify-detached-node-dependencies.ps1"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8-sig")


def _msvc_script() -> str:
    return MSVC_SCRIPT.read_text(encoding="utf-8-sig")


def _four_edition_script() -> str:
    return FOUR_EDITION_SCRIPT.read_text(encoding="utf-8-sig")


def test_four_edition_wrapper_freezes_one_source_and_cleans_only_owned_outputs() -> None:
    script = _four_edition_script()
    for fragment in (
        '[ValidateSet("all", "universal", "sim", "lab", "field")]',
        'throw "The four-edition build requires one exact clean source commit."',
        '"desktop\\src-tauri\\tauri.universal.conf.json"',
        '"desktop\\src-tauri\\tauri.sim.conf.json"',
        '"desktop\\src-tauri\\tauri.lab.conf.json"',
        '"desktop\\src-tauri\\tauri.field.conf.json"',
        '"DRONEDREAM_OAUTH_CLIENT_ID_$($EditionId.ToUpperInvariant())"',
        'Remove-Item Env:\\RUSTFLAGS -ErrorAction SilentlyContinue',
        'Remove-Item Env:\\CARGO_ENCODED_RUSTFLAGS -ErrorAction SilentlyContinue',
        '"DRONEDREAM_RELEASE_SOURCE_COMMIT"',
        '& git -C $repoRoot clean -fdx -- @paths',
        'Refusing to delete a reparse-point root',
        'Refusing to delete a tree containing reparse points',
        'The source tree changed after the $editionId build.',
        '[IO.Path]::GetFileName($builtInstaller)',
        'build-receipt.json',
        '[ValidateSet("msvc", "gnullvm")]',
        'targetTriple = "x86_64-pc-windows-msvc"',
        'compilerFamily = "msvc"',
        'System32\\WindowsPowerShell\\v1.0\\Modules',
        'function Get-ProcessEnvironmentSnapshot',
        'function Restore-ProcessEnvironmentSnapshot',
        '$editionEnvironment = Get-ProcessEnvironmentSnapshot',
        'Restore-ProcessEnvironmentSnapshot -Snapshot $editionEnvironment',
        'VsDevCmd mutates dozens of process-scoped variables.',
        '[Environment]::GetEnvironmentVariable($name, "User")',
        'These VITE values are public browser application identifiers',
    ):
        assert fragment in script
    assert 'Join-Path $editionOutput "$($contract.product)-${version}.exe"' not in script


def test_shared_msvc_build_is_pinned_native_and_fail_closed() -> None:
    script = _msvc_script()
    for fragment in (
        '1.97.0-x86_64-pc-windows-msvc',
        'stable-x86_64-pc-windows-msvc',
        '$requiredRustVersion = "1.97.0"',
        'x86_64-pc-windows-msvc',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
        'VsDevCmd.bat',
        '"cl.exe", "link.exe", "rc.exe", "dumpbin.exe"',
        'dumpbin.exe /dependents $application',
        'The desktop release source must be an exact clean Git commit.',
        'invoke-tauri-updater-signer.ps1',
        'Refusing to prune installer artifacts outside the MSVC NSIS bundle directory.',
        'Resolve-EditionGeneratedFrontendContract',
        'Test-PostBuildSourceStatus',
        'System32\\WindowsPowerShell\\v1.0\\Modules',
        'Programs\\Python\\Python311\\python.exe',
        "'^Python 3\\.11\\.[0-9]+$'",
        "Could not clear the stale updater-signature slot",
        "Unsigned builds require an empty updater-signature slot",
    ):
        assert fragment in script
    assert script.index("[IO.File]::Delete($expectedUpdaterSignature)") < script.index(
        'Invoke-CheckedNativeCommand `'
    )
    assert 'tauri.llvm.conf.json' not in script
    assert 'WebView2Loader.dll' not in script


def test_shared_msvc_build_is_valid_windows_powershell() -> None:
    script_path = str(MSVC_SCRIPT).replace("'", "''")
    result = _run_powershell(
        textwrap.dedent(
            f"""
            $tokens = $null
            $errors = $null
            [void][Management.Automation.Language.Parser]::ParseFile(
              '{script_path}', [ref]$tokens, [ref]$errors)
            if ($errors.Count -ne 0) {{
              $errors | ForEach-Object {{ Write-Error $_.Message }}
              exit 1
            }}
            Write-Output 'msvc-ast-ok'
            """
        ),
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "msvc-ast-ok" in result.stdout


def test_four_edition_wrapper_is_valid_windows_powershell() -> None:
    script_path = str(FOUR_EDITION_SCRIPT).replace("'", "''")
    result = _run_powershell(
        textwrap.dedent(
            f"""
            $tokens = $null
            $errors = $null
            [void][Management.Automation.Language.Parser]::ParseFile(
              '{script_path}', [ref]$tokens, [ref]$errors)
            if ($errors.Count -ne 0) {{
              $errors | ForEach-Object {{ Write-Error $_.Message }}
              exit 1
            }}
            Write-Output 'four-edition-ast-ok'
            """
        ),
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "four-edition-ast-ok" in result.stdout


def test_planner_verifier_waits_for_exit_and_retries_only_its_exact_temp_tree() -> None:
    script = PLANNER_VERIFIER.read_text(encoding="utf-8-sig")
    for fragment in (
        "function Remove-PlannerSmokeSandbox",
        '$process.WaitForExit()',
        '$process.StandardOutput.ReadToEndAsync()',
        '$process.StandardError.ReadToEndAsync()',
        '[string]$EditionId = "universal"',
        '"--clear-installer-handoff"',
        'The FIELD app-only command unexpectedly created a Runtime plan.',
        'StartsWith("DroneDream-Planner-Smoke-"',
        "Refusing to remove a reparse-point planner smoke directory",
        '[int]$MaximumAttempts = 40',
        "Start-Sleep -Milliseconds $RetryDelayMilliseconds",
    ):
        assert fragment in script
    assert script.index("ReadToEndAsync()") < script.index("WaitForExit(90000)")

    script_path = str(PLANNER_VERIFIER).replace("'", "''")
    result = _run_powershell(
        textwrap.dedent(
            f"""
            $tokens = $null
            $errors = $null
            [void][Management.Automation.Language.Parser]::ParseFile(
              '{script_path}', [ref]$tokens, [ref]$errors)
            if ($errors.Count -ne 0) {{
              $errors | ForEach-Object {{ Write-Error $_.Message }}
              exit 1
            }}
            Write-Output 'planner-verifier-ast-ok'
            """
        ),
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "planner-verifier-ast-ok" in result.stdout


def test_field_installer_is_app_only_and_never_advertises_runtime_protocol() -> None:
    runtime_mode = RUNTIME_MODE_HOOK.read_text(encoding="utf-8-sig")
    installer_hook = INSTALLER_HOOK.read_text(encoding="utf-8-sig")
    page = "Page custom DroneDreamRuntimeModePageCreate DroneDreamRuntimeModePageLeave"
    field_guard = '!if "${DRONEDREAM_EDITION_ID}" != "field"'
    assert field_guard in runtime_mode
    assert runtime_mode.index(field_guard) < runtime_mode.index(page)
    assert '!if "${DRONEDREAM_EDITION_ID}" == "field"' in installer_hook
    assert (
        'DeleteRegValue SHCTX "${MANUPRODUCTKEY}" '
        '"DroneDreamRuntimeOperationProtocol"'
    ) in installer_hook


def _run_powershell(script: str, *, cwd: Path) -> subprocess.CompletedProcess[str]:
    utf8_script = (
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); "
        "$OutputEncoding = [Console]::OutputEncoding; "
        + script
    )
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    env = os.environ.copy()
    env["PSModulePath"] = os.pathsep.join(
        (
            str(Path.home() / "Documents" / "WindowsPowerShell" / "Modules"),
            str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WindowsPowerShell" / "Modules"),
            str(system_root / "System32" / "WindowsPowerShell" / "v1.0" / "Modules"),
        )
    )
    return subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            utf8_script,
        ],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def test_shared_llvm_build_exposes_edition_safe_inputs_without_changing_defaults() -> None:
    script = _script()
    for fragment in (
        "[string]$AdditionalConfigPath",
        "[string]$CargoTargetDir",
        "[string]$LlvmRoot",
        "[string]$DetachedNodeDependencyManifest",
        '[string]$ExpectedProductName = "DroneDream"',
        '[string]$EditionId = "universal"',
        "[switch]$AllowUnsignedUpdater",
        "[switch]$PreserveBundleHistory",
        "$env:CARGO_TARGET_DIR = $cargoTargetRoot",
        "${ExpectedProductName}_$($tauriConfig.version)_x64-setup.exe",
        "-EditionId $EditionId",
        "if (-not $AllowUnsignedUpdater)",
        "if (-not $PreserveBundleHistory)",
        "Detached release sources require an exact attested Node dependency manifest.",
        "verify-detached-node-dependencies.ps1",
        '$env:npm_config_offline = "true"',
        'System32\\WindowsPowerShell\\v1.0\\Modules',
    ):
        assert fragment in script


def test_shared_llvm_build_merges_edition_before_llvm_resources_on_cli() -> None:
    script = _script()
    edition_index = script.index('"--config", $additionalConfig')
    llvm_index = script.index('"--config", $llvmBundleConfig', edition_index)
    assert edition_index < llvm_index
    assert "$env:TAURI_CONFIG" not in script


def test_shared_llvm_build_keeps_signing_and_source_guards_fail_closed() -> None:
    script = _script()
    for fragment in (
        "status --porcelain=v1 --untracked-files=all",
        "The release source changed while the desktop installer was building.",
        "invoke-tauri-updater-signer.ps1",
        "Unsigned builds require an empty updater-signature slot",
        "The signed Tauri updater artifact is missing",
        "The compiled desktop edition does not match its updater family.",
        "Signed updater builds require an explicit edition config overlay.",
        "Refusing to prune installer artifacts outside the LLVM NSIS bundle directory.",
        "Invoke-CheckedNativeCommand",
        "Resolve-EditionGeneratedFrontendContract",
        "Test-PostBuildSourceStatus",
    ):
        assert fragment in script
    assert script.index("[IO.File]::Delete($expectedUpdaterSignature)") < script.index(
        'Invoke-CheckedNativeCommand `'
    )


def test_release_policies_anchor_the_wrapped_native_build_boundary() -> None:
    expected_anchor = "Invoke-CheckedNativeCommand `"
    assert expected_anchor in RELEASE_POLICY.read_text(encoding="utf-8-sig")
    assert expected_anchor in SIGNING_POLICY.read_text(encoding="utf-8-sig")


def test_native_driver_allows_informational_stderr_but_rejects_nonzero(tmp_path: Path) -> None:
    module = str(DRIVER).replace("'", "''")
    success = _run_powershell(
        textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            Import-Module '{module}' -Force
            Invoke-CheckedNativeCommand -FilePath $env:ComSpec -DisplayName 'fixture' `
              -ArgumentList @('/d', '/c', 'echo Info: normal progress 1>&2 & exit /b 0')
            Write-Output 'native-success'
            """
        ),
        cwd=tmp_path,
    )
    assert success.returncode == 0, success.stderr
    assert "normal progress" in success.stderr
    assert "NativeCommandError" not in success.stderr
    assert "native-success" in success.stdout

    failure = _run_powershell(
        textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            Import-Module '{module}' -Force
            Invoke-CheckedNativeCommand -FilePath $env:ComSpec -DisplayName 'fixture' `
              -ArgumentList @('/d', '/c', 'echo fatal build error 1>&2 & exit /b 23')
            """
        ),
        cwd=tmp_path,
    )
    assert failure.returncode != 0
    assert "native exit code 23" in failure.stderr


def test_generated_frontend_contract_is_parameterized_and_fail_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    config_dir = repo / "desktop" / "src-tauri"
    config_dir.mkdir(parents=True)
    base = config_dir / "tauri.conf.json"
    base.write_text(
        json.dumps({"build": {"frontendDist": "../../frontend/dist"}}),
        encoding="utf-8",
    )

    external_overlays = tmp_path / "approved-overlays"
    external_overlays.mkdir()
    cases = {
        "universal": config_dir / "tauri.universal.conf.json",
        "sim": config_dir / "target" / "tauri.sim.authorized.json",
        "lab": external_overlays / "tauri.lab.authorized.json",
        "field": external_overlays / "tauri.field.authorized.json",
    }
    module = str(DRIVER).replace("'", "''")
    for edition, overlay in cases.items():
        overlay.parent.mkdir(parents=True, exist_ok=True)
        frontend_dist = (
            "../../frontend/dist"
            if edition in {"universal", "field"}
            else f"../../frontend/{edition}-dist"
        )
        overlay_payload = (
            {"productName": "DroneDream-Universal"}
            if edition == "universal"
            else {"build": {"frontendDist": frontend_dist}}
        )
        overlay.write_text(json.dumps(overlay_payload), encoding="utf-8")
        command = textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            Import-Module '{module}' -Force
            Resolve-EditionGeneratedFrontendContract `
              -RepoRoot '{repo}' -BaseConfigPath '{base}' `
              -AdditionalConfigPath '{overlay}' -EditionId '{edition}' |
              ConvertTo-Json -Compress
            """
        )
        result = _run_powershell(command, cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        expected_path = (
            "frontend/dist"
            if edition in {"universal", "field"}
            else f"frontend/{edition}-dist"
        )
        assert payload["relativePath"] == expected_path

        status_result = _run_powershell(
            textwrap.dedent(
                f"""
                $ErrorActionPreference = 'Stop'
                Import-Module '{module}' -Force
                Test-PostBuildSourceStatus `
                  -AllowedGeneratedPath '{expected_path}' `
                  -StatusLines @('?? {expected_path}/index.html') |
                  ConvertTo-Json -Compress
                """
            ),
            cwd=tmp_path,
        )
        assert status_result.returncode == 0, status_result.stderr
        status_payload = json.loads(status_result.stdout)
        assert status_payload["allowedGeneratedCount"] == 1
        assert status_payload["unexpectedCount"] == 0

    absolute = external_overlays / "tauri.field.absolute.json"
    absolute.write_text(
        json.dumps({"build": {"frontendDist": str(repo / "frontend" / "dist")}}),
        encoding="utf-8",
    )
    absolute_result = _run_powershell(
        textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            Import-Module '{module}' -Force
            Resolve-EditionGeneratedFrontendContract `
              -RepoRoot '{repo}' -BaseConfigPath '{base}' `
              -AdditionalConfigPath '{absolute}' -EditionId 'field' |
              ConvertTo-Json -Compress
            """
        ),
        cwd=tmp_path,
    )
    assert absolute_result.returncode == 0, absolute_result.stderr
    assert json.loads(absolute_result.stdout)["relativePath"] == "frontend/dist"

    absolute_outside = external_overlays / "tauri.field.absolute-outside.json"
    absolute_outside.write_text(
        json.dumps({"build": {"frontendDist": str(tmp_path / "outside-dist")}}),
        encoding="utf-8",
    )
    absolute_outside_result = _run_powershell(
        textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            Import-Module '{module}' -Force
            Resolve-EditionGeneratedFrontendContract `
              -RepoRoot '{repo}' -BaseConfigPath '{base}' `
              -AdditionalConfigPath '{absolute_outside}' -EditionId 'field'
            """
        ),
        cwd=tmp_path,
    )
    assert absolute_outside_result.returncode != 0
    assert "inside the repository" in absolute_outside_result.stderr

    invalid = config_dir / "tauri.field.invalid.conf.json"
    invalid.write_text(
        json.dumps({"build": {"frontendDist": "../../artifacts/field-dist"}}),
        encoding="utf-8",
    )
    result = _run_powershell(
        textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            Import-Module '{module}' -Force
            Resolve-EditionGeneratedFrontendContract `
              -RepoRoot '{repo}' -BaseConfigPath '{base}' `
              -AdditionalConfigPath '{invalid}' -EditionId 'field'
            """
        ),
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "outside the explicit generated-output contract" in result.stderr

    escaped = external_overlays / "tauri.field.escape.json"
    escaped.write_text(
        json.dumps({"build": {"frontendDist": "../../../frontend/field-dist"}}),
        encoding="utf-8",
    )
    escape_result = _run_powershell(
        textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            Import-Module '{module}' -Force
            Resolve-EditionGeneratedFrontendContract `
              -RepoRoot '{repo}' -BaseConfigPath '{base}' `
              -AdditionalConfigPath '{escaped}' -EditionId 'field'
            """
        ),
        cwd=tmp_path,
    )
    assert escape_result.returncode != 0
    assert "inside the repository" in escape_result.stderr

    unknown_result = _run_powershell(
        textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            Import-Module '{module}' -Force
            Resolve-EditionGeneratedFrontendContract `
              -RepoRoot '{repo}' -BaseConfigPath '{base}' `
              -AdditionalConfigPath '{absolute}' -EditionId 'unknown'
            """
        ),
        cwd=tmp_path,
    )
    assert unknown_result.returncode != 0
    assert "ValidateSet" in unknown_result.stderr


def test_postbuild_status_allows_only_exact_untracked_generated_files(tmp_path: Path) -> None:
    module = str(DRIVER).replace("'", "''")
    command = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        Import-Module '{module}' -Force
        Test-PostBuildSourceStatus `
          -AllowedGeneratedPath 'frontend/field-dist' `
          -StatusLines @(
            '?? frontend/field-dist/index.html',
            '?? frontend/field-dist/assets/app.js',
            ' M frontend/field-dist/tracked.js',
            '?? frontend/field-dist-escape/file.js',
            '?? unexpected.txt'
          ) | ConvertTo-Json -Compress
        """
    )
    result = _run_powershell(command, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["allowedGeneratedCount"] == 2
    assert payload["unexpectedCount"] == 3
    assert " M frontend/field-dist/tracked.js" in payload["unexpected"]
    assert "?? unexpected.txt" in payload["unexpected"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _detached_fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    owned_base = tmp_path / "owned-dependencies"
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    node_version = subprocess.run(
        ["node.exe", "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    npm_version = subprocess.run(
        ["npm.cmd", "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    source_inputs = []
    for relative in (
        "desktop/package.json",
        "desktop/package-lock.json",
        "frontend/package.json",
        "frontend/package-lock.json",
    ):
        source_inputs.append(
            {"sourcePath": relative, "bundlePath": relative, "sha256": _sha256(ROOT / relative)}
        )
    identity_lines = [
        commit,
        *(str(item["sha256"]) for item in source_inputs),
        node_version,
        npm_version,
        "windows",
        "x64",
    ]
    bundle_id = (
        "npm-win32-x64-" + hashlib.sha256("\n".join(identity_lines).encode()).hexdigest()[:16]
    )
    bundle_root = owned_base / bundle_id
    for relative in (
        "desktop/node_modules/@tauri-apps/cli",
        "desktop/node_modules/@tauri-apps/cli-win32-x64-msvc",
        "frontend/node_modules/vite",
    ):
        (bundle_root / relative).mkdir(parents=True, exist_ok=True)
    for relative in (
        "desktop/package.json",
        "desktop/package-lock.json",
        "frontend/package.json",
        "frontend/package-lock.json",
    ):
        destination = bundle_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)

    tauri_package = bundle_root / "desktop/node_modules/@tauri-apps/cli/package.json"
    tauri_entrypoint = bundle_root / "desktop/node_modules/@tauri-apps/cli/tauri.js"
    native_package = (
        bundle_root / "desktop/node_modules/@tauri-apps/cli-win32-x64-msvc/package.json"
    )
    native_binary = (
        bundle_root / "desktop/node_modules/@tauri-apps/cli-win32-x64-msvc/cli.win32-x64-msvc.node"
    )
    vite_package = bundle_root / "frontend/node_modules/vite/package.json"
    tauri_package.write_text(json.dumps({"version": "2.11.4"}), encoding="utf-8")
    tauri_entrypoint.write_text("// attested fixture\n", encoding="utf-8")
    native_package.write_text(json.dumps({"version": "2.11.4"}), encoding="utf-8")
    native_binary.write_bytes(b"attested-native-fixture")
    vite_package.write_text(json.dumps({"version": "7.3.6"}), encoding="utf-8")

    entries: list[dict[str, object]] = []
    for item in sorted(bundle_root.rglob("*"), key=lambda value: value.as_posix()):
        relative = item.relative_to(bundle_root).as_posix()
        if relative == "manifest.json":
            continue
        if item.is_dir():
            entries.append(
                {"path": relative, "type": "directory", "bytes": 0, "sha256": None, "target": None}
            )
        else:
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "bytes": item.stat().st_size,
                    "sha256": _sha256(item),
                    "target": None,
                }
            )
    entries.sort(key=lambda entry: str(entry["path"]))
    lines = [
        "|".join(
            (
                str(entry["path"]),
                str(entry["type"]),
                str(entry["bytes"]),
                str(entry["sha256"] or ""),
                str(entry["target"] or ""),
            )
        )
        for entry in entries
    ]
    fingerprint = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "kind": "dronedream-desktop-node-dependency-bundle",
        "bundleVersion": "1.0.0",
        "bundleId": bundle_id,
        "state": "attested-offline",
        "editionScope": ["universal", "sim", "lab", "field"],
        "productSource": {"commit": commit, "tree": tree},
        "ownedBase": owned_base.as_posix(),
        "dependencyRoot": bundle_root.as_posix(),
        "sourceInputs": source_inputs,
        "toolchain": {
            "operatingSystem": "windows",
            "architecture": "x64",
            "nodeVersion": node_version,
            "npmVersion": npm_version,
            "tauriCli": {
                "version": "2.11.4",
                "packageJsonPath": "desktop/node_modules/@tauri-apps/cli/package.json",
                "packageJsonSha256": _sha256(tauri_package),
                "entrypointPath": "desktop/node_modules/@tauri-apps/cli/tauri.js",
                "entrypointSha256": _sha256(tauri_entrypoint),
            },
            "platformCli": {
                "packageName": "@tauri-apps/cli-win32-x64-msvc",
                "version": "2.11.4",
                "packageJsonPath": (
                    "desktop/node_modules/@tauri-apps/cli-win32-x64-msvc/package.json"
                ),
                "packageJsonSha256": _sha256(native_package),
                "binaryPath": (
                    "desktop/node_modules/@tauri-apps/cli-win32-x64-msvc/cli.win32-x64-msvc.node"
                ),
                "binarySha256": _sha256(native_binary),
            },
            "vite": {
                "version": "7.3.6",
                "packageJsonPath": "frontend/node_modules/vite/package.json",
                "packageJsonSha256": _sha256(vite_package),
            },
        },
        "mounts": [
            {
                "linkPath": "desktop/node_modules",
                "targetPath": "desktop/node_modules",
                "linkType": "junction",
            },
            {
                "linkPath": "frontend/node_modules",
                "targetPath": "frontend/node_modules",
                "linkType": "junction",
            },
        ],
        "inventory": {
            "algorithm": "sha256-lines-v1",
            "excludedPaths": ["manifest.json"],
            "entries": entries,
            "treeFingerprint": fingerprint,
        },
        "policies": {
            "networkAllowed": False,
            "systemTauriAllowed": False,
            "arbitraryPathInjectionAllowed": False,
            "dependencyMutationAllowed": False,
            "dependencyPayloadAllowed": False,
            "preparationAuthorizedSeparately": True,
        },
        "attestation": {
            "createdAt": "2026-08-07T00:00:00Z",
            "preparationReceiptSha256": "1" * 64,
            "offlineCacheSha256": "2" * 64,
            "lifecycleScriptsAudited": True,
        },
    }
    manifest_path = bundle_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path, manifest


def _verify_detached(
    manifest_path: Path,
    manifest: dict[str, object],
    *,
    edition: str = "universal",
    frontend_dist: Path | None = None,
    installer_bundle: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    product_source = manifest["productSource"]
    assert isinstance(product_source, dict)
    frontend_dist_value = str(frontend_dist or ROOT / "frontend" / "dist").replace("'", "''")
    installer_bundle_value = str(
        installer_bundle or manifest_path.parent.parent / "installer"
    ).replace("'", "''")
    command = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        & '{str(DETACHED_VERIFIER).replace("'", "''")}' `
          -ManifestPath '{str(manifest_path).replace("'", "''")}' `
          -RepoRoot '{str(ROOT).replace("'", "''")}' `
          -EditionId '{edition}' `
          -ExpectedSourceCommit '{product_source["commit"]}' `
          -ExpectedSourceTree '{product_source["tree"]}' `
          -FrontendDistPath '{frontend_dist_value}' `
          -InstallerBundlePath '{installer_bundle_value}' `
          -ContractOnly | ConvertTo-Json -Depth 8 -Compress
        """
    )
    return _run_powershell(command, cwd=ROOT)


def test_detached_dependency_schema_freezes_tools_mounts_and_offline_policy() -> None:
    schema = json.loads(DETACHED_SCHEMA.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert (
        schema["properties"]["toolchain"]["properties"]["tauriCli"]["properties"]["version"][
            "const"
        ]
        == "2.11.4"
    )
    assert (
        schema["properties"]["toolchain"]["properties"]["vite"]["properties"]["version"]["const"]
        == "7.3.6"
    )
    assert schema["properties"]["mounts"]["maxItems"] == 2
    policies = schema["properties"]["policies"]["properties"]
    assert policies["networkAllowed"]["const"] is False
    assert policies["systemTauriAllowed"]["const"] is False
    assert policies["dependencyPayloadAllowed"]["const"] is False


def test_detached_dependency_contract_accepts_all_editions_without_live_junctions(
    tmp_path: Path,
) -> None:
    manifest_path, manifest = _detached_fixture(tmp_path)
    for edition in ("universal", "sim", "lab", "field"):
        result = _verify_detached(manifest_path, manifest, edition=edition)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["editionId"] == edition
        assert payload["mountCount"] == 2
        assert payload["liveMountValidated"] is False
        assert payload["networkAllowed"] is False
        assert payload["systemTauriAllowed"] is False


def test_detached_dependency_contract_rejects_source_hash_tool_tree_mount_and_policy_drift(
    tmp_path: Path,
) -> None:
    mutators = {
        "source": lambda value: value["productSource"].update(commit="0" * 40),
        "package-hash": lambda value: value["sourceInputs"][0].update(sha256="0" * 64),
        "tool-version": lambda value: value["toolchain"]["tauriCli"].update(version="2.11.3"),
        "tauri-entrypoint": lambda value: value["toolchain"]["tauriCli"].update(
            entrypointSha256="0" * 64
        ),
        "platform-binary": lambda value: value["toolchain"]["platformCli"].update(
            binarySha256="0" * 64
        ),
        "vite-version": lambda value: value["toolchain"]["vite"].update(version="7.3.5"),
        "tree": lambda value: value["inventory"].update(treeFingerprint="0" * 64),
        "third-mount": lambda value: value["mounts"].append(
            {
                "linkPath": "extra/node_modules",
                "targetPath": "extra/node_modules",
                "linkType": "junction",
            }
        ),
        "mount-escape": lambda value: value["mounts"][0].update(
            targetPath="../escaped/node_modules"
        ),
        "network": lambda value: value["policies"].update(networkAllowed=True),
    }
    for name, mutate in mutators.items():
        case_root = tmp_path / name
        manifest_path, manifest = _detached_fixture(case_root)
        mutate(manifest)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        result = _verify_detached(manifest_path, manifest)
        assert result.returncode != 0, name


def test_detached_dependency_contract_rejects_owned_root_and_output_overlap(tmp_path: Path) -> None:
    manifest_path, manifest = _detached_fixture(tmp_path / "root")
    manifest["ownedBase"] = (tmp_path / "different-owned-base").as_posix()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    assert _verify_detached(manifest_path, manifest).returncode != 0

    manifest_path, manifest = _detached_fixture(tmp_path / "overlap")
    result = _verify_detached(
        manifest_path,
        manifest,
        frontend_dist=manifest_path.parent / "frontend" / "dist",
    )
    assert result.returncode != 0

    unknown = _verify_detached(manifest_path, manifest, edition="unknown")
    assert unknown.returncode != 0
    assert "ParameterArgumentValidationError" in unknown.stderr


def test_dependency_payload_isolation_rejects_node_modules_and_dependency_manifest(
    tmp_path: Path,
) -> None:
    clean_output = tmp_path / "clean-output"
    clean_output.mkdir()
    (clean_output / "index.html").write_text("ok", encoding="utf-8")
    (clean_output / "manifest.json").write_text(
        json.dumps({"name": "DroneDream"}), encoding="utf-8"
    )
    dirty_output = tmp_path / "dirty-output"
    (dirty_output / "assets" / "node_modules").mkdir(parents=True)
    (dirty_output / "desktop-node-dependency-bundle.json").write_text("{}", encoding="utf-8")
    (dirty_output / "manifest.json").write_text(
        json.dumps({"kind": "dronedream-desktop-node-dependency-bundle"}),
        encoding="utf-8",
    )
    module = str(DRIVER).replace("'", "''")
    clean = _run_powershell(
        textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            Import-Module '{module}' -Force
            Test-DetachedDependencyPayloadIsolation `
              -OutputPaths @('{str(clean_output).replace("'", "''")}') |
              ConvertTo-Json -Compress
            """
        ),
        cwd=tmp_path,
    )
    assert clean.returncode == 0, clean.stderr
    assert json.loads(clean.stdout)["violationCount"] == 0
    dirty = _run_powershell(
        textwrap.dedent(
            f"""
            $ErrorActionPreference = 'Stop'
            Import-Module '{module}' -Force
            Test-DetachedDependencyPayloadIsolation `
              -OutputPaths @('{str(dirty_output).replace("'", "''")}') |
              ConvertTo-Json -Compress
            """
        ),
        cwd=tmp_path,
    )
    assert dirty.returncode == 0, dirty.stderr
    assert json.loads(dirty.stdout)["violationCount"] == 3


def test_detached_dependency_scripts_never_provision_or_hide_dependencies() -> None:
    verifier = DETACHED_VERIFIER.read_text(encoding="utf-8-sig")
    driver = DRIVER.read_text(encoding="utf-8-sig")
    build = _script()
    combined = "\n".join((verifier, driver, build)).lower()
    assert "new-item -itemtype junction" not in combined
    assert "npm ci" not in combined
    assert "npm install" not in combined
    assert "dependency root must not overlap frontenddist or installer output" in combined
    assert "detached dependency bytes or links entered a product output" in combined
    assert "get-command tauri" not in combined
    assert "desktoplockfileversion -ne 3" in combined
    assert "nested dependency bundle reparse point escapes" in combined
    assert "detached node dependency bundle changed during the release build" in combined
