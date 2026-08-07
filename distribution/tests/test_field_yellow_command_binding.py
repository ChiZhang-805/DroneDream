from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = (
    ROOT
    / "distribution/editions/field/build/resolve-field-yellow-command-binding.ps1"
)
PRODUCT = "6672320392f3274a952a7f02a2006aa2bd6e2671"
PRODUCT_TREE = "46c877553ad751f78849593ea9ba93a1042ace68"
POWERSHELL = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / (
    "System32/WindowsPowerShell/v1.0/powershell.exe"
)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _application(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    source_id = PRODUCT[:7]
    run_owner = tmp_path / "run-owner"
    document: dict[str, object] = {
        "schemaVersion": 1,
        "kind": "dronedream-field-yellow-command-binding-application",
        "editionId": "field",
        "source": {"productCommit": PRODUCT, "productTree": PRODUCT_TREE},
        "attemptOrdinal": {
            "preflight": 2,
            "buildScript": 1,
            "retryMaximum": 0,
        },
        "commandBinding": {
            "sourceId": source_id,
            "pathOrdinalSuffix": "-preflight2",
            "sourceOwner": str(tmp_path / "source-owner"),
            "cargoOwner": str(tmp_path / "cargo-owner"),
            "runOwner": str(run_owner),
        },
        "ownedPaths": {
            "sourceRoot": str(tmp_path / "source-owner" / f"ddf{source_id}-preflight2"),
            "cargoTarget": str(tmp_path / "cargo-owner" / f"{source_id}-preflight2"),
            "runRoot": str(
                run_owner
                / f"field-yellow-build-{source_id}-lightweight-installer-preflight2"
            ),
        },
    }
    paths = document["ownedPaths"]
    assert isinstance(paths, dict)
    run_root = Path(str(paths["runRoot"]))
    paths.update(
        {
            "outputRoot": str(run_root / "artifact"),
            "preflightScript": str(run_root / "preflight-approved-build.ps1"),
            "buildScript": str(run_root / "invoke-approved-build.ps1"),
        }
    )
    application = tmp_path / "application.json"
    application.write_text(json.dumps(document), encoding="utf-8")
    return application, document


def _run(application: Path) -> subprocess.CompletedProcess[str]:
    sha256 = hashlib.sha256(application.read_bytes()).hexdigest()
    return subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(TOOL),
            "-Application",
            str(application),
            "-ExpectedApplicationSha256",
            sha256,
            "-ExpectedEvidenceHead",
            _git("rev-parse", "HEAD"),
            "-RepoRoot",
            str(ROOT),
            "-PlanOnly",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _rewrite(application: Path, document: dict[str, object]) -> None:
    application.write_text(json.dumps(document), encoding="utf-8")


def test_exact_6672320_binding_passes_without_creating_paths(tmp_path: Path) -> None:
    application, document = _application(tmp_path)
    result = _run(application)
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        assert result.returncode != 0
        assert "Evidence worktree is not clean." in result.stderr
        paths = document["ownedPaths"]
        assert isinstance(paths, dict)
        assert all(not Path(str(value)).exists() for value in paths.values())
        return
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["decision"] == "pass-plan-only"
    assert receipt["sourceId"] == "6672320"
    assert receipt["attemptOrdinal"] == {
        "preflight": 2,
        "buildScript": 1,
        "retryMaximum": 0,
    }
    assert all(value == 0 for value in receipt["effects"].values())
    paths = document["ownedPaths"]
    assert isinstance(paths, dict)
    assert all(
        not Path(str(paths[key])).exists()
        for key in ("sourceRoot", "cargoTarget", "runRoot", "outputRoot")
    )


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("historical-leaf", "cargoTarget does not match its source-derived exact path"),
        ("arbitrary-leaf", "cargoTarget does not match its source-derived exact path"),
        ("path-escape", "cargoTarget does not match its source-derived exact path"),
        ("source-id-drift", "Command binding source ID does not match product source"),
    ],
)
def test_contamination_and_path_drift_fail_closed(
    tmp_path: Path, mutation: str, error: str
) -> None:
    application, original = _application(tmp_path)
    document = copy.deepcopy(original)
    paths = document["ownedPaths"]
    binding = document["commandBinding"]
    assert isinstance(paths, dict)
    assert isinstance(binding, dict)
    cargo_owner = Path(str(binding["cargoOwner"]))
    if mutation == "historical-leaf":
        paths["cargoTarget"] = str(cargo_owner / "560f574")
    elif mutation == "arbitrary-leaf":
        paths["cargoTarget"] = str(cargo_owner / "6672320-other")
    elif mutation == "path-escape":
        paths["cargoTarget"] = str(cargo_owner / "6672320-preflight2" / ".." / "escape")
    else:
        binding["sourceId"] = "560f574"
    _rewrite(application, document)

    result = _run(application)
    assert result.returncode != 0
    assert error in result.stderr


def test_powershell_51_ast_parses() -> None:
    result = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$e=$null;$t=$null;"
                "[Management.Automation.Language.Parser]::ParseFile("
                f"'{TOOL}',[ref]$t,[ref]$e)|Out-Null;"
                "if($e.Count){$e|ForEach-Object{$_.ToString()};exit 1}"
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
