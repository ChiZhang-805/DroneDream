from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "desktop" / "scripts" / "build-windows-llvm.ps1"
DRIVER = ROOT / "desktop" / "scripts" / "release-build-driver.psm1"
RELEASE_POLICY = ROOT / "desktop" / "scripts" / "verify-release-source-policy.mjs"
SIGNING_POLICY = ROOT / "desktop" / "scripts" / "verify-updater-signing-contract.ps1"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8-sig")


def _run_powershell(script: str, *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_shared_llvm_build_exposes_edition_safe_inputs_without_changing_defaults() -> None:
    script = _script()
    for fragment in (
        '[string]$AdditionalConfigPath',
        '[string]$CargoTargetDir',
        '[string]$LlvmRoot',
        '[string]$ExpectedProductName = "DroneDream"',
        '[string]$EditionId = "universal"',
        '[switch]$AllowUnsignedUpdater',
        '[switch]$PreserveBundleHistory',
        '$env:CARGO_TARGET_DIR = $cargoTargetRoot',
        '${ExpectedProductName}_$($tauriConfig.version)_x64-setup.exe',
        '-EditionId $EditionId',
        'if (-not $AllowUnsignedUpdater)',
        'if (-not $PreserveBundleHistory)',
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
        'status --porcelain=v1 --untracked-files=all',
        'The release source changed while the desktop installer was building.',
        'invoke-tauri-updater-signer.ps1',
        'Unsigned builds require an empty updater-signature slot',
        'The signed Tauri updater artifact is missing',
        'The compiled desktop edition does not match its updater family.',
        'Signed updater builds require an explicit edition config overlay.',
        'Refusing to prune installer artifacts outside the LLVM NSIS bundle directory.',
        'Invoke-CheckedNativeCommand',
        'Resolve-EditionGeneratedFrontendContract',
        'Test-PostBuildSourceStatus',
    ):
        assert fragment in script


def test_field_build_skips_the_runtime_planner_smoke_only_for_field() -> None:
    script = _script()
    field_guard = 'if ($EditionId -ceq "field")'
    skip_message = 'Skipped Runtime installer planner smoke for field-lightweight.'
    planner_call = '& (Join-Path $PSScriptRoot "verify-installer-planner.ps1")'

    guard_index = script.index(field_guard)
    skip_index = script.index(skip_message, guard_index)
    else_index = script.index("} else {", skip_index)
    planner_index = script.index(planner_call, else_index)

    assert guard_index < skip_index < else_index < planner_index
    assert script.count(planner_call) == 1


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
            if edition == "universal"
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
            f"frontend/{edition}-dist" if edition != "universal" else "frontend/dist"
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
        json.dumps(
            {"build": {"frontendDist": str(repo / "frontend" / "field-dist")}}
        ),
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
    assert json.loads(absolute_result.stdout)["relativePath"] == "frontend/field-dist"

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
