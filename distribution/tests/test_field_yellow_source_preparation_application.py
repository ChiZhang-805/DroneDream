from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / (
    "distribution/editions/field/build/"
    "source-preparation-6672320-application.v1.json"
)
PRODUCT = "6672320392f3274a952a7f02a2006aa2bd6e2671"
TOOL_COMMIT = "d1bf90091b7ba5567eaf2fd214b1a254ab6f9d71"


def _git(*args: str, binary: bool = False) -> str | bytes:
    output = subprocess.check_output(["git", *args], cwd=ROOT, text=not binary)
    return output if binary else output.strip()


def _application() -> dict[str, object]:
    return json.loads(APPLICATION.read_text(encoding="utf-8"))


def _canonical_sha(document: dict[str, object]) -> str:
    payload = {key: value for key, value in document.items() if key != "integrity"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_product_tool_and_build_evidence_are_exact() -> None:
    application = _application()
    source = application["source"]
    tool = application["toolBinding"]
    assert source["productCommit"] == PRODUCT
    assert _git("rev-parse", f"{PRODUCT}^{{tree}}") == source["productTree"]
    assert source["boundBuildEvidenceHead"] == (
        "b96aa8491e2e6bbb6436632e704dcb024d4b15bd"
    )
    assert tool["sourceCommit"] == TOOL_COMMIT
    blob = _git("rev-parse", f"{TOOL_COMMIT}:{tool['path']}")
    assert blob == tool["gitBlob"]
    content = _git("cat-file", "blob", blob, binary=True)
    assert isinstance(content, bytes)
    assert len(content) == tool["canonicalBlobBytes"]
    assert hashlib.sha256(content).hexdigest() == tool["canonicalBlobSha256"]


def test_frozen_run_files_remain_exact() -> None:
    application = _application()
    for binding in application["frozenRunFiles"]:
        path = Path(binding["path"])
        assert path.stat().st_size == binding["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"]


def test_only_source_root_and_two_exact_junctions_are_prepared() -> None:
    application = _application()
    paths = application["ownedPaths"]
    junctions = application["junctions"]
    assert paths["sourceRoot"].endswith("ddf6672320-preflight2-generate1")
    assert paths["sourceRootExistsAtPreparation"] is False
    assert paths["cargoTargetExistsAtPreparation"] is False
    assert paths["outputRootExistsAtPreparation"] is False
    assert paths["runRootExistsAndIsFrozen"] is True
    assert junctions["desktop"]["target"] == str(ROOT / "desktop/node_modules")
    assert junctions["frontend"]["target"] == str(ROOT / "frontend/node_modules")


def test_attempt_and_authorization_are_fail_closed() -> None:
    application = _application()
    ordinal = application["attemptOrdinal"]
    authorization = application["authorization"]
    assert ordinal == {
        "application": 1,
        "sourcePreparation": 1,
        "retryMaximum": 0,
        "generateConsumed": 1,
        "preflightConsumed": 0,
        "buildConsumed": 0,
    }
    assert authorization["currentMessageAuthorizesPrepare"] is False
    assert authorization["planAllowed"] is True
    assert authorization["preflightAllowed"] is False
    assert authorization["buildAllowed"] is False
    assert authorization["cargoRunOutputCreationAllowed"] is False
    assert authorization["runFilesModificationAllowed"] is False


def test_application_integrity_is_canonical() -> None:
    application = _application()
    assert _canonical_sha(application) == application["integrity"]["canonicalSha256"]
