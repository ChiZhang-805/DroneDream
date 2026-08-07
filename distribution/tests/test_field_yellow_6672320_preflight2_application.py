from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / (
    "distribution/editions/field/build/"
    "yellow-6672320-preflight2-application.v1.json"
)
PRODUCT = "6672320392f3274a952a7f02a2006aa2bd6e2671"
TOOL_COMMIT = "e3c075f26904c97ca96d730cd30deee73c606c5d"


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


def test_product_source_is_unchanged_and_tool_is_exact() -> None:
    application = _application()
    source = application["source"]
    tool = application["toolBinding"]
    assert source["productCommit"] == PRODUCT
    assert source["productSourceChangedByThisGreenAtom"] is False
    assert _git("rev-parse", f"{PRODUCT}^{{tree}}") == source["productTree"]
    assert tool["sourceCommit"] == TOOL_COMMIT
    blob = _git("rev-parse", f"{TOOL_COMMIT}:{tool['path']}")
    assert blob == tool["gitBlob"]
    content = _git("cat-file", "blob", blob, binary=True)
    assert isinstance(content, bytes)
    assert len(content) == tool["canonicalBlobBytes"]
    assert hashlib.sha256(content).hexdigest() == tool["canonicalBlobSha256"]


def test_owned_paths_are_source_derived_fresh_and_not_historical() -> None:
    application = _application()
    paths = application["ownedPaths"]
    predecessor = application["predecessor"]
    assert paths["sourceRoot"].endswith(r"ddf6672320-preflight2")
    assert paths["cargoTarget"].endswith(r"field-cargo-target\6672320-preflight2")
    assert paths["runRoot"].endswith(
        r"field-yellow-build-6672320-lightweight-installer-preflight2"
    )
    assert paths["outputRoot"] == paths["runRoot"] + r"\artifact"
    assert paths["runRoot"] != predecessor["runRoot"]
    assert paths["reuseHistoricalSourceTargetOrOutputAllowed"] is False
    assert all(
        paths[key + "ExistsAtPreparation"] is False
        for key in ("sourceRoot", "cargoTarget", "runRoot", "outputRoot")
    )


def test_predecessor_failure_is_frozen_and_build_remains_unconsumed() -> None:
    application = _application()
    predecessor = application["predecessor"]
    ordinal = application["attemptOrdinal"]
    assert predecessor["preflightFailureReceiptSha256"] == (
        "489084db5213c503d8049157d5c906e036019c0f0a1131e083b2eb2d06d2fa78"
    )
    assert predecessor["readOnlyPreserved"] is True
    assert predecessor["reuseAllowed"] is False
    assert ordinal["application"] == 2
    assert ordinal["preflight"] == 2
    assert ordinal["buildScript"] == 1
    assert ordinal["frontend"] == 1
    assert ordinal["tauri"] == 1
    assert ordinal["cargo"] == 1
    assert ordinal["nsis"] == 1
    assert ordinal["freshBuild"] == 1
    assert ordinal["retryMaximum"] == 0
    assert ordinal["predecessorBuildWasNotConsumed"] is True


def test_green_authorization_is_plan_only_and_hardware_remains_denied() -> None:
    application = _application()
    authorization = application["authorization"]
    product = application["productContract"]
    assert authorization["currentMessageAuthorizesBuild"] is False
    assert authorization["planOnlyAllowed"] is True
    assert authorization["newExactYellowStartSignalRequired"] is True
    assert authorization["sourceCloneCreationAllowed"] is False
    assert authorization["cargoTargetCreationAllowed"] is False
    assert authorization["runRootCreationAllowed"] is False
    assert authorization["outputCreationAllowed"] is False
    assert product["profile"] == "field-lightweight"
    assert product["fieldRuntimeModePageEnabled"] is False
    assert product["fieldSimulatorPayloadAllowed"] is False
    assert product["validatedHardwarePackCount"] == 0
    assert product["hardwareDecision"] == "deny"
    assert product["frontendIsAuthority"] is False


def test_application_integrity_is_canonical() -> None:
    application = _application()
    assert _canonical_sha(application) == application["integrity"]["canonicalSha256"]
