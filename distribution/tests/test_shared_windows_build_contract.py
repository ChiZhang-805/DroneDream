from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "desktop" / "scripts" / "build-windows-llvm.ps1"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8-sig")


def test_shared_llvm_build_exposes_edition_safe_inputs_without_changing_defaults() -> None:
    script = _script()
    for fragment in (
        '[string]$AdditionalConfigPath',
        '[string]$CargoTargetDir',
        '[string]$LlvmRoot',
        '[string]$ExpectedProductName = "DroneDream"',
        '[switch]$AllowUnsignedUpdater',
        '[switch]$PreserveBundleHistory',
        '$env:CARGO_TARGET_DIR = $cargoTargetRoot',
        '${ExpectedProductName}_$($tauriConfig.version)_x64-setup.exe',
        'if (-not $AllowUnsignedUpdater)',
        'if (-not $PreserveBundleHistory)',
    ):
        assert fragment in script


def test_shared_llvm_build_merges_edition_before_llvm_resources_on_cli() -> None:
    script = _script()
    edition_index = script.index("--config $additionalConfig")
    llvm_index = script.index("--config $llvmBundleConfig", edition_index)
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
        'Refusing to prune installer artifacts outside the LLVM NSIS bundle directory.',
    ):
        assert fragment in script
