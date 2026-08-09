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
        "88223fab6c2b0d493aaedab932c04d40def4da58e28f6d670adbfd745a6ca8ba",
        "brand\\generated\\universal\\windows\\32x32.png",
        "acd4ef1fc198bf157c73c26edfb6c2814d46286857b69bfbd857a7328243d19f",
        "Test-ImagePixelEquality",
        "git -C $repoRoot diff --quiet $ProductSourceCommit",
        'Arguments @("/S", "/L=1033")',
        'Arguments @("/S", "/L=1033") -Stage "icon-audit-uninstall"',
        "protectedShortcutParity",
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
