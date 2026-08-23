from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "desktop/scripts/verify-universal-icon-surfaces.ps1"


def test_icon_surface_verifier_is_exact_source_bound_and_bounded() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for required in (
        "ProductSourceCommit",
        "ExpectedSha256",
        "ExpectedBytes",
        "brand\\generated\\universal\\windows\\icon.ico",
        "d607a304ef09156ec7041744726791dedc9f96625f081676ace654e652536090",
        "brand\\generated\\universal\\windows\\32x32.png",
        "01080f8fd17fdcc793bfb6bead1b6cc0ca535a29d92b79c3501bf96c7d5d74a7",
        "Test-ImagePixelEquality",
        "$receipt.surfaces = @($surfaces | ForEach-Object { $_ })",
        "git -C $repoRoot diff --quiet $ProductSourceCommit",
        'Arguments @("/S", "/L=1033")',
        'Arguments @("/S", "/L=1033") -Stage "icon-audit-uninstall"',
        "protectedShortcutParity",
        "(Test-Path -LiteralPath $uninstallKey) -or",
        "Refusing to replace an existing icon evidence directory",
    ):
        assert required in text


def test_icon_surface_verifier_does_not_expand_product_scope() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for forbidden in (
        "Start runtime",
        "DroneDreamRuntime",
        "PX4",
        "Gazebo",
        "OAuth",
    ):
        assert forbidden not in text
    assert "Remove-Item -Recurse" not in text
    assert "Get-ChildItem -Recurse" not in text
    assert "Test-Path -LiteralPath $uninstallKey -or" not in text
    assert "$receipt.surfaces = @($surfaces)" not in text
