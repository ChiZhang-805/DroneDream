from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "distribution/editions/field/build/prepare-field-yellow-source.ps1"
PRODUCT = "6672320392f3274a952a7f02a2006aa2bd6e2671"
TREE = "46c877553ad751f78849593ea9ba93a1042ace68"
EVIDENCE = "b96aa8491e2e6bbb6436632e704dcb024d4b15bd"
POWERSHELL = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / (
    "System32/WindowsPowerShell/v1.0/powershell.exe"
)
RUN = Path(
    r"C:\Users\zju20\.codex\visualizations\2026\08\05"
    r"\019fd0e2-71cc-7742-bfab-612510f37c39"
    r"\field-yellow-build-6672320-lightweight-installer-preflight2-generate1"
)
FILES = [
    (
        "application",
        "yellow-build-application.json",
        10956,
        "bed1a83ed616ce571e201598d400ff1ab2c9c49b8f568f5b1c280ed47f5d5fb7",
    ),
    (
        "overlay",
        "tauri-yellow-authorized.json",
        3675,
        "dfbfddb4dc50f856f97f3f33112a9e62f0c1359a93afbfe950970e802961d586",
    ),
    (
        "preflight",
        "preflight-approved-build.ps1",
        10663,
        "06a661d30f7fef518e35cd8679043fab48cfb790060968d2bf601cebcab3105f",
    ),
    (
        "build",
        "invoke-approved-build.ps1",
        9635,
        "0c165bb6423888c7a5cff5aee27340b2f65a3f501ca46dcff1522a7826c10c66",
    ),
    (
        "receipt",
        "run-files-receipt.json",
        4404,
        "20c943eae00f1617859e62d32e7711215de65fc95bf35ad3975e0410c9372748",
    ),
]


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _application(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    source_owner = tmp_path / "source-owner"
    source_owner.mkdir()
    source_root = source_owner / "ddf6672320-preflight2-generate1"
    document: dict[str, object] = {
        "schemaVersion": 1,
        "kind": "dronedream-field-yellow-source-preparation-application",
        "editionId": "field",
        "source": {
            "productCommit": PRODUCT,
            "productTree": TREE,
            "originUrl": "https://github.com/ChiZhang-805/DroneDream.git",
        },
        "attemptOrdinal": {"sourcePreparation": 1, "retryMaximum": 0},
        "ownedPaths": {
            "sourceOwner": str(source_owner),
            "sourceRoot": str(source_root),
            "cargoTarget": str(tmp_path / "cargo" / "6672320-preflight2-generate1"),
            "outputRoot": str(RUN / "artifact"),
        },
        "junctions": {
            "desktop": {"target": str(ROOT / "desktop/node_modules")},
            "frontend": {"target": str(ROOT / "frontend/node_modules")},
        },
        "frozenRunFiles": [
            {"id": file_id, "path": str(RUN / name), "bytes": size, "sha256": sha}
            for file_id, name, size, sha in FILES
        ],
    }
    application = tmp_path / "source-prep.json"
    application.write_text(json.dumps(document), encoding="utf-8")
    return application, document


def _write(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def _run(application: Path, mode: str) -> subprocess.CompletedProcess[str]:
    sha = hashlib.sha256(application.read_bytes()).hexdigest()
    return subprocess.run(
        [
            str(POWERSHELL), "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(TOOL),
            "-Application", str(application),
            "-ExpectedApplicationSha256", sha,
            "-ExpectedEvidenceHead", _git("rev-parse", "HEAD"),
            "-BoundBuildEvidenceHead", EVIDENCE,
            "-RepoRoot", str(ROOT), mode,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_plan_is_zero_write(tmp_path: Path) -> None:
    application, document = _application(tmp_path)
    result = _run(application, "-Plan")
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["decision"] == "pass-plan-zero-write"
    assert all(value == 0 for value in plan["effects"].values())
    assert not Path(str(document["ownedPaths"]["sourceRoot"])).exists()


def test_prepare_creates_exact_detached_source_and_junctions(tmp_path: Path) -> None:
    application, document = _application(tmp_path)
    result = _run(application, "-Prepare")
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    source_root = Path(str(document["ownedPaths"]["sourceRoot"]))
    assert receipt["decision"] == "prepared-once"
    assert _git_at(source_root, "rev-parse", "HEAD") == PRODUCT
    assert _git_at(source_root, "rev-parse", "HEAD^{tree}") == TREE
    assert (
        _git_at(source_root, "rev-parse", "refs/remotes/origin/codex/software-field")
        == EVIDENCE
    )
    assert _git_at(source_root, "status", "--porcelain=v1") == ""
    for area in ("desktop", "frontend"):
        item = source_root / area / "node_modules"
        assert item.is_dir()


def _git_at(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.mark.parametrize("mutation", ["commit", "tree", "junction"])
def test_wrong_commit_tree_or_junction_target_fails_closed(
    tmp_path: Path, mutation: str
) -> None:
    application, document = _application(tmp_path)
    if mutation == "commit":
        document["source"]["productCommit"] = "0" * 40
    elif mutation == "tree":
        document["source"]["productTree"] = "0" * 40
    else:
        document["junctions"]["desktop"]["target"] = str(tmp_path / "wrong")
    _write(application, document)
    result = _run(application, "-Plan")
    assert result.returncode != 0
    assert not Path(str(document["ownedPaths"]["sourceRoot"])).exists()


def test_existing_source_root_is_rejected(tmp_path: Path) -> None:
    application, document = _application(tmp_path)
    source_root = Path(str(document["ownedPaths"]["sourceRoot"]))
    source_root.mkdir()
    sentinel = source_root / "sentinel"
    sentinel.write_text("preserve")
    result = _run(application, "-Prepare")
    assert result.returncode != 0
    assert sentinel.read_text() == "preserve"


def test_reparse_source_root_is_rejected(tmp_path: Path) -> None:
    application, document = _application(tmp_path)
    source_root = Path(str(document["ownedPaths"]["sourceRoot"]))
    target = tmp_path / "junction-target"
    target.mkdir()
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(source_root), str(target)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"junction fixture unavailable: {result.stderr}")
    prepare = _run(application, "-Prepare")
    assert prepare.returncode != 0
    assert "sourceRoot must not be a reparse point" in prepare.stderr
