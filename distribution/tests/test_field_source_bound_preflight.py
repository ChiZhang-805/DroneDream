from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = (
    ROOT
    / "distribution/editions/field/build/verify-source-bound-driver.ps1"
)
POWERSHELL = Path(
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
)
DRIVER_PATH = "desktop/scripts/release-build-driver.psm1"


def _run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _git(repo: Path, *args: str) -> str:
    return _run("git", *args, cwd=repo).stdout.strip()


def _fixture(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo = tmp_path / "source repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "field-contract@example.invalid")
    _git(repo, "config", "user.name", "Field Contract")
    (repo / ".gitattributes").write_text("*.psm1 text eol=crlf\n", encoding="utf-8")
    driver = repo / DRIVER_PATH
    driver.parent.mkdir(parents=True)
    canonical = b'function Get-FieldDriver {\n    return "canonical"\n}\n'
    driver.write_bytes(canonical)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    driver.unlink()
    _git(repo, "checkout", "--", DRIVER_PATH)
    source = _git(repo, "rev-parse", "HEAD")
    blob = _git(repo, "rev-parse", f"HEAD:{DRIVER_PATH}")
    return repo, source, blob, hashlib.sha256(canonical).hexdigest()


def _verify(
    repo: Path,
    source: str,
    blob: str,
    sha256: str,
    *,
    path: str = DRIVER_PATH,
) -> subprocess.CompletedProcess[str]:
    return _run(
        str(POWERSHELL),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(VERIFIER),
        "-RepoRoot",
        str(repo),
        "-SourceCommit",
        source,
        "-RelativePath",
        path,
        "-ExpectedGitBlob",
        blob,
        "-ExpectedCanonicalSha256",
        sha256,
        cwd=ROOT,
        check=False,
    )


@pytest.mark.skipif(not POWERSHELL.exists(), reason="Windows PowerShell is required")
def test_crlf_worktree_passes_only_via_exact_canonical_blob(tmp_path: Path) -> None:
    repo, source, blob, canonical_sha = _fixture(tmp_path)
    worktree_bytes = (repo / DRIVER_PATH).read_bytes()
    assert b"\r\n" in worktree_bytes
    assert hashlib.sha256(worktree_bytes).hexdigest() != canonical_sha

    result = _verify(repo, source, blob, canonical_sha)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["validationBasis"] == (
        "exact-source-git-blob-and-canonical-blob-bytes"
    )
    assert payload["gitBlob"] == blob
    assert payload["canonicalBlobSha256"] == canonical_sha
    assert payload["workingTreeRepresentationGrantsAuthority"] is False


@pytest.mark.skipif(not POWERSHELL.exists(), reason="Windows PowerShell is required")
def test_real_content_drift_is_denied(tmp_path: Path) -> None:
    repo, _, old_blob, old_sha = _fixture(tmp_path)
    (repo / DRIVER_PATH).write_text("changed content\n", encoding="utf-8")
    _git(repo, "add", DRIVER_PATH)
    _git(repo, "commit", "-m", "drift")
    changed_source = _git(repo, "rev-parse", "HEAD")

    result = _verify(repo, changed_source, old_blob, old_sha)

    assert result.returncode != 0
    assert "Git blob drifted" in result.stderr


@pytest.mark.skipif(not POWERSHELL.exists(), reason="Windows PowerShell is required")
def test_unknown_source_is_denied(tmp_path: Path) -> None:
    repo, _, blob, canonical_sha = _fixture(tmp_path)

    result = _verify(repo, "0" * 40, blob, canonical_sha)

    assert result.returncode != 0
    assert "Git command failed" in result.stderr


@pytest.mark.skipif(not POWERSHELL.exists(), reason="Windows PowerShell is required")
@pytest.mark.parametrize(
    "path",
    ("../release-build-driver.psm1", r"C:\escape\release-build-driver.psm1"),
)
def test_path_escape_is_denied(tmp_path: Path, path: str) -> None:
    repo, source, blob, canonical_sha = _fixture(tmp_path)

    result = _verify(repo, source, blob, canonical_sha, path=path)

    assert result.returncode != 0
    assert "Only the canonical shared release driver" in result.stderr


@pytest.mark.skipif(not POWERSHELL.exists(), reason="Windows PowerShell is required")
def test_dirty_worktree_is_denied(tmp_path: Path) -> None:
    repo, source, blob, canonical_sha = _fixture(tmp_path)
    (repo / DRIVER_PATH).write_text("dirty\n", encoding="utf-8")

    result = _verify(repo, source, blob, canonical_sha)

    assert result.returncode != 0
    assert "working tree is not clean" in result.stderr


def test_verifier_is_field_owned_and_does_not_modify_common_driver() -> None:
    assert VERIFIER.is_file()
    assert shutil.which("git")
    text = VERIFIER.read_text(encoding="utf-8")
    assert "cat-file" in text
    assert "workingTreeRepresentationGrantsAuthority = $false" in text
    assert "desktop/scripts/release-build-driver.psm1" in text
