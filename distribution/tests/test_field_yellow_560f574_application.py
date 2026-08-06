from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = (
    ROOT
    / "distribution/editions/field/build/yellow-560f574-application.v1.json"
)


def _git(*args: str, binary: bool = False) -> str | bytes:
    output = subprocess.check_output(
        ["git", *args], cwd=ROOT, text=not binary
    )
    return output if binary else output.strip()


def _canonical_sha(document: dict[str, object]) -> str:
    payload = {key: value for key, value in document.items() if key != "integrity"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_application_binds_exact_product_source_and_verifier_blob() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    source = application["source"]
    verifier = application["sourceBoundPreflight"]
    assert source["productCommit"] == "560f574a95c8b51bbf34711bfd092d77fd3e166e"
    assert _git("rev-parse", f"{source['productCommit']}^{{tree}}") == source["productTree"]
    assert _git(
        "rev-parse",
        f"{source['productCommit']}:{verifier['verifier']}",
    ) == verifier["verifierGitBlob"]
    blob_bytes = _git("cat-file", "blob", verifier["verifierGitBlob"], binary=True)
    assert isinstance(blob_bytes, bytes)
    assert hashlib.sha256(blob_bytes).hexdigest() == verifier["verifierCanonicalBlobSha256"]
    assert verifier["targetGitBlob"] == "5195887fae97016693466d7f75e466ca4a5e77e2"
    assert verifier["workingTreeFileShaIsAuthorization"] is False


def test_application_uses_new_owned_paths_and_preserves_failure_evidence() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    paths = application["ownedPaths"]
    predecessor = application["predecessor"]
    assert paths["sourceRoot"].endswith("ddf560f574")
    assert paths["cargoTarget"].endswith("field-cargo-target\\560f574")
    assert paths["runRoot"].endswith(
        "field-yellow-build-560f574-source-bound-preflight"
    )
    assert paths["reuseHistoricalSourceTargetOrOutputAllowed"] is False
    assert all(
        paths[key] != predecessor["failureReceipt"]
        for key in ("sourceRoot", "cargoTarget", "runRoot", "outputRoot")
    )
    assert predecessor["failureReceiptSha256"] == (
        "9defbcc32c67679b43c1609bd88a725566cfb5eb201b6ebd059bc2941cd14f73"
    )
    assert predecessor["readOnlyPreserved"] is True
    assert predecessor["reuseAllowed"] is False


def test_attempt_ordinals_and_single_build_contract_are_exact() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    ordinal = application["attemptOrdinal"]
    artifact = application["artifact"]
    assert ordinal == {
        "scope": "field-ui-theme-source-bound-preflight-lineage",
        "application": 2,
        "preflight": 2,
        "buildScript": 1,
        "frontend": 1,
        "tauri": 1,
        "cargo": 1,
        "nsis": 1,
        "freshBuild": 1,
        "predecessorBuildWasNotConsumed": True,
    }
    for key in (
        "frontendBuildInvocationMaximum",
        "tauriInvocationMaximum",
        "cargoBuildCountMaximum",
        "nsisInvocationMaximum",
        "freshBuildAttemptMaximum",
    ):
        assert artifact[key] == 1
    assert application["greenVerification"]["tauriCargoNsisInvoked"] is False


def test_safety_and_application_integrity_remain_fail_closed() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    safety = application["safety"]
    assert safety["validatedHardwarePackCount"] == 0
    assert safety["hardwareDecision"] == "deny"
    assert safety["frontendIsAuthority"] is False
    assert safety["installationAllowed"] is False
    assert safety["deviceOrHardwareAllowed"] is False
    assert _canonical_sha(application) == application["integrity"]["canonicalSha256"]
