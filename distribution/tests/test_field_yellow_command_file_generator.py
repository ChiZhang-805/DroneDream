from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / (
    "distribution/editions/field/build/generate-field-yellow-command-files.ps1"
)
PRODUCT = "6672320392f3274a952a7f02a2006aa2bd6e2671"
PRODUCT_TREE = "46c877553ad751f78849593ea9ba93a1042ace68"
TOOL_COMMIT = "f15110b1670452d4fed4f49a9f88003a739a96aa"
POWERSHELL = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / (
    "System32/WindowsPowerShell/v1.0/powershell.exe"
)

GENERATOR_BINDING = {
    "path": "distribution/editions/field/build/generate-field-yellow-command-files.ps1",
    "sourceCommit": TOOL_COMMIT,
    "gitBlob": "980f3eee9381adee7da4663e1f2ba57d75685b9d",
    "canonicalBlobSha256": (
        "cd44a88a400e79c72a0f83c232435dd3cb0aea56ae895c6427e5d1ff82e34c9f"
    ),
}
TEMPLATE_BINDINGS = [
    {
        "id": "preflight",
        "path": (
            "distribution/editions/field/build/templates/"
            "field-yellow-preflight.ps1.in"
        ),
        "gitBlob": "9878b5ca6183c81e66d004a9d9ca8f07fffb5ece",
        "canonicalBlobSha256": (
            "af856666a80c36952f48c50f5540ee131de740e3961d41ccfa69417fbd85a751"
        ),
    },
    {
        "id": "build",
        "path": (
            "distribution/editions/field/build/templates/"
            "field-yellow-build.ps1.in"
        ),
        "gitBlob": "a2a300f512343e00ca421f25d263a9368299f5a2",
        "canonicalBlobSha256": (
            "d64c65cbe4608e32b789985dad0facf81d157a4dc4d4d63c8eeccf5c4cfb0eec"
        ),
    },
]


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _application(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    source_id = PRODUCT[:7]
    suffix = "-preflight2-generate1"
    run_owner = tmp_path / "run-owner"
    run_owner.mkdir()
    run_root = run_owner / (
        f"field-yellow-build-{source_id}-lightweight-installer{suffix}"
    )
    document: dict[str, object] = {
        "schemaVersion": 1,
        "kind": "dronedream-field-yellow-command-files-application",
        "applicationId": "field-yellow-generator-fixture-v1",
        "editionId": "field",
        "source": {"productCommit": PRODUCT, "productTree": PRODUCT_TREE},
        "generatorBinding": copy.deepcopy(GENERATOR_BINDING),
        "templateBindings": copy.deepcopy(TEMPLATE_BINDINGS),
        "overlayContract": {
            "sourcePath": "desktop/src-tauri/tauri.field.conf.json",
            "sourceGitBlob": "73ddcf9fe9d5349a93c88887bef5c09e322ec204",
            "sourceCanonicalSha256": (
                "923d9499870c6c03837efcc5d7cbe85a2d4947a314a880eda0d440417bba5657"
            ),
        },
        "attemptOrdinal": {
            "preflight": 2,
            "buildScript": 1,
            "retryMaximum": 0,
        },
        "commandBinding": {
            "sourceId": source_id,
            "pathOrdinalSuffix": suffix,
            "sourceOwner": str(tmp_path / "source-owner"),
            "cargoOwner": str(tmp_path / "cargo-owner"),
            "runOwner": str(run_owner),
        },
        "ownedPaths": {
            "sourceRoot": str(
                tmp_path / "source-owner" / f"ddf{source_id}{suffix}"
            ),
            "cargoTarget": str(
                tmp_path / "cargo-owner" / f"{source_id}{suffix}"
            ),
            "runRoot": str(run_root),
            "outputRoot": str(run_root / "artifact"),
            "applicationCopy": str(run_root / "yellow-build-application.json"),
            "authorizationOverlay": str(
                run_root / "tauri-yellow-authorized.json"
            ),
            "preflightScript": str(run_root / "preflight-approved-build.ps1"),
            "buildScript": str(run_root / "invoke-approved-build.ps1"),
            "runFilesReceipt": str(run_root / "run-files-receipt.json"),
        },
        "productContract": {
            "profile": "field-lightweight",
            "fieldRuntimeModePageEnabled": False,
            "fieldSimulatorPayloadAllowed": False,
            "validatedHardwarePackCount": 0,
            "hardwareDecision": "deny",
        },
        "integrity": {"canonicalSha256": "a" * 64},
    }
    application = tmp_path / "application.json"
    application.write_text(json.dumps(document), encoding="utf-8")
    return application, document


def _write(application: Path, document: dict[str, object]) -> None:
    application.write_text(json.dumps(document), encoding="utf-8")


def _run(application: Path, mode: str) -> subprocess.CompletedProcess[str]:
    sha256 = hashlib.sha256(application.read_bytes()).hexdigest()
    return subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(GENERATOR),
            "-Application",
            str(application),
            "-ExpectedApplicationSha256",
            sha256,
            "-ExpectedEvidenceHead",
            _git("rev-parse", "HEAD"),
            "-RepoRoot",
            str(ROOT),
            mode,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_plan_has_zero_side_effects(tmp_path: Path) -> None:
    application, document = _application(tmp_path)
    result = _run(application, "-Plan")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        assert result.returncode != 0
        assert "Evidence worktree is not clean." in result.stderr
        assert not Path(str(document["ownedPaths"]["runRoot"])).exists()
        return
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["decision"] == "pass-plan-zero-write"
    assert all(value == 0 for value in plan["effects"].values())
    paths = document["ownedPaths"]
    assert isinstance(paths, dict)
    assert not Path(str(paths["runRoot"])).exists()


def test_generate_exclusively_creates_five_bound_files(tmp_path: Path) -> None:
    application, document = _application(tmp_path)
    result = _run(application, "-Generate")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        assert result.returncode != 0
        assert "Evidence worktree is not clean." in result.stderr
        assert not Path(str(document["ownedPaths"]["runRoot"])).exists()
        return
    assert result.returncode == 0, result.stderr
    generated = json.loads(result.stdout)
    assert generated["decision"] == "generated-exclusive"
    assert generated["effects"]["filesCreated"] == 5
    paths = document["ownedPaths"]
    assert isinstance(paths, dict)
    run_root = Path(str(paths["runRoot"]))
    assert sorted(path.name for path in run_root.iterdir()) == [
        "invoke-approved-build.ps1",
        "preflight-approved-build.ps1",
        "run-files-receipt.json",
        "tauri-yellow-authorized.json",
        "yellow-build-application.json",
    ]
    receipt = json.loads((run_root / "run-files-receipt.json").read_text())
    assert receipt["decision"] == "generated-exclusive"
    assert receipt["attemptOrdinal"] == {
        "preflight": 2,
        "buildScript": 1,
        "retryMaximum": 0,
    }
    for name in ("preflight-approved-build.ps1", "invoke-approved-build.ps1"):
        script = (run_root / name).read_text(encoding="utf-8")
        assert "560f574" not in script
        assert "6672320-preflight2-generate1" in script


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("historical-leaf", "cargoTarget does not match its source-derived exact path"),
        ("wrong-leaf", "cargoTarget does not match its source-derived exact path"),
        ("escape", "cargoTarget does not match its source-derived exact path"),
    ],
)
def test_wrong_or_historical_cargo_paths_fail_closed(
    tmp_path: Path, mutation: str, error: str
) -> None:
    application, document = _application(tmp_path)
    paths = document["ownedPaths"]
    binding = document["commandBinding"]
    assert isinstance(paths, dict)
    assert isinstance(binding, dict)
    cargo_owner = Path(str(binding["cargoOwner"]))
    if mutation == "historical-leaf":
        paths["cargoTarget"] = str(cargo_owner / "560f574")
    elif mutation == "wrong-leaf":
        paths["cargoTarget"] = str(cargo_owner / "6672320-wrong")
    else:
        paths["cargoTarget"] = str(
            cargo_owner / "6672320-preflight2-generate1" / ".." / "escape"
        )
    _write(application, document)
    result = _run(application, "-Plan")
    assert result.returncode != 0
    assert error in result.stderr


def test_existing_run_root_is_rejected_without_overwrite(tmp_path: Path) -> None:
    application, document = _application(tmp_path)
    paths = document["ownedPaths"]
    assert isinstance(paths, dict)
    run_root = Path(str(paths["runRoot"]))
    run_root.mkdir()
    sentinel = run_root / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    result = _run(application, "-Generate")
    assert result.returncode != 0
    assert "A fresh owned path already exists" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert list(run_root.iterdir()) == [sentinel]


def test_reparse_run_owner_is_rejected(tmp_path: Path) -> None:
    application, document = _application(tmp_path)
    binding = document["commandBinding"]
    paths = document["ownedPaths"]
    assert isinstance(binding, dict)
    assert isinstance(paths, dict)
    original_owner = Path(str(binding["runOwner"]))
    original_owner.rmdir()
    target = tmp_path / "junction-target"
    target.mkdir()
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(original_owner), str(target)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"junction fixture unavailable: {result.stderr}")
    generate = _run(application, "-Generate")
    assert generate.returncode != 0
    assert "runOwner must not be a reparse point" in generate.stderr
    assert not Path(str(paths["runRoot"])).exists()


def test_generator_and_templates_parse_with_windows_powershell_51() -> None:
    files = [GENERATOR]
    files.extend(ROOT / binding["path"] for binding in TEMPLATE_BINDINGS)
    quoted = ",".join(f"'{path}'" for path in files)
    result = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                f"foreach($p in @({quoted}))"
                "{$e=$null;$t=$null;"
                "[Management.Automation.Language.Parser]::ParseFile("
                "$p,[ref]$t,[ref]$e)|Out-Null;"
                "if($e.Count){$e|ForEach-Object{$_.ToString()};exit 1}}"
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
