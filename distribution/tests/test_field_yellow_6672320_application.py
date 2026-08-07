from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "distribution/editions/field/build/yellow-6672320-application.v1.json"
PRODUCT = "6672320392f3274a952a7f02a2006aa2bd6e2671"


def _git(*args: str, binary: bool = False) -> str | bytes:
    output = subprocess.check_output(["git", *args], cwd=ROOT, text=not binary)
    return output if binary else output.strip()


def _canonical_sha(document: dict[str, object]) -> str:
    payload = {key: value for key, value in document.items() if key != "integrity"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _application() -> dict[str, object]:
    return json.loads(APPLICATION.read_text(encoding="utf-8"))


def test_application_binds_exact_new_product_and_product_fix_blobs() -> None:
    application = _application()
    source = application["source"]
    assert source["productCommit"] == PRODUCT
    assert _git("rev-parse", f"{PRODUCT}^{{tree}}") == source["productTree"]
    for path_key, blob_key, sha_key in (
        ("runtimeModePolicyPath", "runtimeModePolicyGitBlob", "runtimeModePolicySha256"),
        (
            "runtimeModeImplementationPath",
            "runtimeModeImplementationGitBlob",
            "runtimeModeImplementationSha256",
        ),
        ("installerLanguagePath", "installerLanguageGitBlob", "installerLanguageSha256"),
        ("observerPath", "observerGitBlob", "observerSha256"),
    ):
        binding = application["productFix"]
        blob = _git("rev-parse", f"{PRODUCT}:{binding[path_key]}")
        assert blob == binding[blob_key]
        content = _git("cat-file", "blob", blob, binary=True)
        assert isinstance(content, bytes)
        assert hashlib.sha256(content).hexdigest() == binding[sha_key]


def test_field_installer_and_hardware_contracts_remain_fail_closed() -> None:
    application = _application()
    fix = application["productFix"]
    safety = application["safety"]
    assert fix["fieldRuntimeModePageEnabled"] is False
    assert fix["fieldRuntimeChoiceStringsCompiled"] is False
    assert fix["fieldSimulatorPayloadAllowed"] is False
    assert fix["observerNextInvocationsBeforeDirectoryAssertion"] == 1
    assert fix["unknownInstallerPageDecision"] == "deny"
    assert safety["validatedHardwarePackCount"] == 0
    assert safety["hardwareDecision"] == "deny"
    assert safety["frontendIsAuthority"] is False
    assert safety["installationAllowed"] is False


def test_old_artifact_and_attempts_are_permanent_read_only_no_go() -> None:
    historical = _application()["historicalNoGo"]
    assert historical["productCommit"] == "560f574a95c8b51bbf34711bfd092d77fd3e166e"
    assert historical["artifactSha256"] == (
        "8e2e2260704901c52b1c0b149eb4929b0e353b7ccf3d76a0fbba7031aa17ca1f"
    )
    assert historical["decision"] == "permanent-no-go-no-relabel-no-website-handoff"
    assert historical["reuseAllowed"] is False
    assert [item["attempt"] for item in historical["lifecycleReceipts"]] == list(range(1, 8))
    assert historical["lifecycleReceipts"][-1]["sha256"] == (
        "482876e03bfb667a23924968d118d7458d6fc42cc0f3335edc2d3d912ef6d5a0"
    )
    assert historical["attempt7ObserverSha256"] == (
        "ebdca5077c65c64f8c35415db916243880890b18523df99dc690cdb055cc9b77"
    )


def test_owned_paths_are_new_and_build_is_single_attempt_not_authorized() -> None:
    application = _application()
    paths = application["ownedPaths"]
    ordinal = application["attemptOrdinal"]
    assert paths["sourceRoot"].endswith("ddf6672320")
    assert paths["cargoTarget"].endswith("field-cargo-target\\6672320")
    assert paths["runRoot"].endswith("field-yellow-build-6672320-lightweight-installer")
    assert paths["reuseHistoricalSourceTargetOrOutputAllowed"] is False
    assert ordinal["application"] == 1
    assert ordinal["freshBuild"] == 1
    assert ordinal["retryMaximum"] == 0
    assert application["authorization"]["currentMessageAuthorizesBuild"] is False
    assert application["authorization"]["newExactYellowStartSignalRequired"] is True
    assert application["greenVerification"]["tauriCargoNsisInvoked"] is False


def test_application_integrity_is_canonical_and_source_bound() -> None:
    application = _application()
    verifier = application["sourceBoundPreflight"]
    assert verifier["targetGitBlob"] == "5195887fae97016693466d7f75e466ca4a5e77e2"
    assert verifier["targetCanonicalSha256"] == (
        "9c8dfc3c1a9ea584ea27cab53c23c4ca0b05911e6409b87b01d05297a309fc14"
    )
    assert verifier["workingTreeFileShaIsAuthorization"] is False
    assert _canonical_sha(application) == application["integrity"]["canonicalSha256"]
