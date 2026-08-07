from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / (
    "distribution/editions/field/build/"
    "yellow-6672320-command-files-application.v2.json"
)
PRODUCT = "6672320392f3274a952a7f02a2006aa2bd6e2671"
GENERATOR_COMMIT = "f15110b1670452d4fed4f49a9f88003a739a96aa"


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


def test_product_and_generator_blobs_are_exact() -> None:
    application = _application()
    source = application["source"]
    generator = application["generatorBinding"]
    assert source["productCommit"] == PRODUCT
    assert source["productSourceChangedByThisGreenAtom"] is False
    assert _git("rev-parse", f"{PRODUCT}^{{tree}}") == source["productTree"]
    assert generator["sourceCommit"] == GENERATOR_COMMIT
    for binding in [generator, *application["templateBindings"]]:
        blob = _git("rev-parse", f"{GENERATOR_COMMIT}:{binding['path']}")
        assert blob == binding["gitBlob"]
        content = _git("cat-file", "blob", blob, binary=True)
        assert isinstance(content, bytes)
        assert len(content) == binding["canonicalBlobBytes"]
        assert hashlib.sha256(content).hexdigest() == binding["canonicalBlobSha256"]


def test_previous_application_is_superseded_but_preserved() -> None:
    supersedes = _application()["supersedes"]
    path = ROOT / supersedes["path"]
    assert path.stat().st_size == supersedes["fileBytes"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == supersedes["fileSha256"]
    assert supersedes["readOnlyPreserved"] is True
    assert supersedes["executionAllowed"] is False
    assert supersedes["reuseAllowed"] is False


def test_new_paths_and_attempt_ordinals_are_exact() -> None:
    application = _application()
    paths = application["ownedPaths"]
    ordinal = application["attemptOrdinal"]
    suffix = "preflight2-generate1"
    assert paths["sourceRoot"].endswith(f"ddf6672320-{suffix}")
    assert paths["cargoTarget"].endswith(f"6672320-{suffix}")
    assert paths["runRoot"].endswith(
        f"field-yellow-build-6672320-lightweight-installer-{suffix}"
    )
    assert paths["outputRoot"] == paths["runRoot"] + r"\artifact"
    assert all(
        paths[key + "ExistsAtPreparation"] is False
        for key in ("sourceRoot", "cargoTarget", "runRoot", "outputRoot")
    )
    assert ordinal["application"] == 3
    assert ordinal["commandFileGeneration"] == 1
    assert ordinal["preflight"] == 2
    assert ordinal["buildScript"] == 1
    assert ordinal["frontend"] == 1
    assert ordinal["tauri"] == 1
    assert ordinal["cargo"] == 1
    assert ordinal["nsis"] == 1
    assert ordinal["freshBuild"] == 1
    assert ordinal["retryMaximum"] == 0


def test_generate_is_the_frozen_yellow_first_step() -> None:
    application = _application()
    commands = application["exactCommands"]
    generated = application["generatedFilesContract"]
    assert commands["yellowFirstStepGenerateTemplate"].endswith("-Generate")
    assert commands["planTemplate"].endswith("-Plan")
    assert commands["generateRequiresNewYellowStartSignal"] is True
    assert commands["preflightRequiresSuccessfulGenerationReceipt"] is True
    assert commands["buildRequiresSuccessfulPreflightReceipt"] is True
    assert generated["exclusiveCreate"] == [
        "applicationCopy",
        "authorizationOverlay",
        "preflightScript",
        "buildScript",
        "runFilesReceipt",
    ]
    assert generated["generatedScriptsValidateReceiptAndOwnSha256"] is True
    assert generated["generatedScriptsHistoricalLiteralDenied"] == "560f574"


def test_green_authorization_and_hardware_remain_fail_closed() -> None:
    application = _application()
    authorization = application["authorization"]
    product = application["productContract"]
    assert authorization["currentMessageAuthorizesBuild"] is False
    assert authorization["planAllowed"] is True
    assert authorization["generateAllowedBeforeNewYellowSignal"] is False
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
