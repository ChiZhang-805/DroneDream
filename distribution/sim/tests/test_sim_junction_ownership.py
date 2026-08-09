from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "distribution" / "sim" / "desktop" / "junction-ownership.psm1"


def run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def quoted(path: Path) -> str:
    return str(path).replace("'", "''")


def test_exact_owned_junction_is_removed_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    link = tmp_path / "link"
    target.mkdir()
    marker = target / "marker.txt"
    marker.write_text("owned target", encoding="utf-8")
    result = run_powershell(
        f"Import-Module '{quoted(MODULE)}' -Force; "
        f"New-Item -ItemType Junction -Path '{quoted(link)}' -Target "
        f"'{quoted(target)}' | Out-Null; "
        f"$removed=Remove-ExactOwnedJunction -LinkPath '{quoted(link)}' "
        f"-ExpectedTarget '{quoted(target)}'; "
        "if(-not $removed -or (Test-Path -LiteralPath '"
        f"{quoted(link)}') -or -not (Test-Path -LiteralPath '{quoted(marker)}'))"
        "{exit 17}"
    )
    assert result.returncode == 0, result.stderr


def test_target_mismatch_fails_closed_and_preserves_junction(tmp_path: Path) -> None:
    target = tmp_path / "target"
    other = tmp_path / "other"
    link = tmp_path / "link"
    target.mkdir()
    other.mkdir()
    result = run_powershell(
        f"Import-Module '{quoted(MODULE)}' -Force; "
        f"New-Item -ItemType Junction -Path '{quoted(link)}' -Target "
        f"'{quoted(target)}' | Out-Null; "
        "$failed=$false; try { Remove-ExactOwnedJunction "
        f"-LinkPath '{quoted(link)}' -ExpectedTarget '{quoted(other)}' | Out-Null "
        "} catch { $failed=$true }; "
        f"if(-not $failed -or -not (Test-Path -LiteralPath '{quoted(link)}'))"
        "{exit 18}; [IO.Directory]::Delete('"
        f"{quoted(link)}',$false)"
    )
    assert result.returncode == 0, result.stderr


def test_non_junction_directory_and_file_are_never_deleted(tmp_path: Path) -> None:
    directory = tmp_path / "ordinary"
    file_path = tmp_path / "ordinary.txt"
    directory.mkdir()
    file_path.write_text("preserve", encoding="utf-8")
    for candidate in (directory, file_path):
        result = run_powershell(
            f"Import-Module '{quoted(MODULE)}' -Force; "
            "$failed=$false; try { Remove-ExactOwnedJunction "
            f"-LinkPath '{quoted(candidate)}' -ExpectedTarget '{quoted(directory)}' "
            "| Out-Null } catch { $failed=$true }; "
            f"if(-not $failed -or -not (Test-Path -LiteralPath '{quoted(candidate)}'))"
            "{exit 19}"
        )
        assert result.returncode == 0, result.stderr


def test_absent_path_is_an_idempotent_noop(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    result = run_powershell(
        f"Import-Module '{quoted(MODULE)}' -Force; "
        f"if(Remove-ExactOwnedJunction -LinkPath '{quoted(missing)}' "
        f"-ExpectedTarget '{quoted(tmp_path)}'){{exit 20}}"
    )
    assert result.returncode == 0, result.stderr
