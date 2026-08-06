from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = (
    ROOT
    / "distribution"
    / "editions"
    / "field"
    / "build"
    / "postbuild-audit-560f574-application.v1.json"
)
RUNNER = (
    ROOT / "distribution" / "editions" / "field" / "build" / "run-artifact-bound-postbuild-audit.py"
)


def git(*arguments: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=not binary,
    )
    return result.stdout if binary else result.stdout.strip()


def canonical_sha(document: dict[str, object]) -> str:
    payload = {key: value for key, value in document.items() if key != "integrity"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def load() -> dict[str, object]:
    return json.loads(APPLICATION.read_text(encoding="utf-8"))


def test_application_binds_exact_product_and_external_runner() -> None:
    application = load()
    source = application["source"]
    tool = application["tool"]
    assert source["productCommit"] == "560f574a95c8b51bbf34711bfd092d77fd3e166e"
    assert source["productTree"] == "0e4535535b7ee339faeaa704069a46bcfe1c350d"
    assert source["evidenceCommitIsProductSource"] is False
    assert source["applicationAndRunnerRemainExternalToProductCheckout"] is True
    assert tool["sourceCommit"] == "2049b878e18a0f40481747c4e31dec031b4aaeb3"
    assert git("rev-parse", f"{tool['sourceCommit']}:{tool['path']}") == tool["gitBlob"]
    blob = git("cat-file", "blob", tool["gitBlob"], binary=True)
    assert isinstance(blob, bytes)
    assert hashlib.sha256(blob).hexdigest() == tool["canonicalBlobSha256"]


def test_product_source_bindings_use_git_blobs_not_worktree_representation() -> None:
    application = load()
    source = application["source"]
    parity = application["sourceParity"]
    assert parity["workingTreeLineEndingsGrantAuthority"] is False
    for binding in parity["gitBlobs"]:
        blob = git("rev-parse", f"{source['productCommit']}:{binding['path']}")
        assert blob == binding["gitBlob"]
        payload = git("cat-file", "blob", blob, binary=True)
        assert isinstance(payload, bytes)
        assert hashlib.sha256(payload).hexdigest() == binding["canonicalBlobSha256"]


def test_frozen_artifact_receipts_and_single_audit_scope_are_exact() -> None:
    application = load()
    artifact = application["artifactIdentity"]
    execution = application["execution"]
    assert artifact["filename"] == "DroneDream-Field-1.0.0.exe"
    assert artifact["bytes"] == 11534069
    assert artifact["sha256"] == (
        "8e2e2260704901c52b1c0b149eb4929b0e353b7ccf3d76a0fbba7031aa17ca1f"
    )
    assert artifact["authenticodeState"] == "NotSigned"
    assert artifact["peCertificatePresent"] is False
    assert execution["auditCountMaximum"] == 1
    assert execution["retryCountMaximum"] == 0
    assert execution["failureDecision"] == "freeze-failed-no-retry"
    assert all(
        execution[key] is False
        for key in (
            "buildAllowed",
            "signingAllowed",
            "installationAllowed",
            "applicationLaunchAllowed",
            "runtimeMigrationAllowed",
            "deviceOrHardwareAllowed",
            "simulationExecutionAllowed",
            "deploymentAllowed",
            "networkAllowed",
        )
    )
    bound = {
        item["id"]: item
        for group in ("artifactFiles", "buildEvidence", "buildOutputs")
        for item in application["bindings"][group]
    }
    assert bound["updaterSignature"]["sha256"] == (
        "11b5ceec3172fbe91c4e342a1a1aa1211a207bef11ef3d3a4697cac621bd5314"
    )
    assert bound["buildProcessReceipt"]["sha256"] == (
        "b8cb490d016f2c8ae2f68ea1fe210cf8bf2f5b118474a8be5dcdebdc3de6b4ca"
    )
    assert bound["preflightReceipt"]["sha256"] == (
        "b67389486bc5dc8758c8d73e767612cc1c81ed108a4ebfe1b750ae88a8f6196b"
    )
    assert bound["postbuildFailureReceipt"]["sha256"] == (
        "5a2c0eff7c7242b456634f679f89f04fdd8ae8dfed8d978632bb3c627ce73db7"
    )


def test_payload_brand_license_profile_and_hardware_contracts_remain_fail_closed() -> None:
    application = load()
    payload = application["payloadAudit"]
    safety = application["safety"]
    assert payload["runtimeProfile"] == "field-lightweight"
    assert payload["includesLargeSimulator"] is False
    assert payload["excludedSourcePaths"] == [
        "backend/app/simulator",
        "scripts/simulators",
    ]
    assert payload["expectedEntryCount"] == 21
    assert not any(
        token in entry.lower()
        for entry in payload["expectedEntries"]
        for token in payload["forbiddenTokens"]
    )
    parity = {item["payloadPath"]: item for item in payload["sourceParity"]}
    assert parity["branding/dronedream-field-mark.png"]["sha256"] == (
        "751372c87bc9630afc2482f5510fa51f8f52d0702a72f58307fc5ed23f9ba7f5"
    )
    assert parity["branding/dronedream-field-dot-lockup.png"]["sha256"] == (
        "588c5aca42b09fa3396efc63a7423bbf1e182379e1a41427f716a1b9f73fbd27"
    )
    assert "licenses/DroneDream-LICENSE.txt" in parity
    assert "licenses/THIRD_PARTY_NOTICES.md" in parity
    assert safety["validatedHardwarePackCount"] == 0
    assert safety["requiredDecisionLayers"] == ["native", "backend", "runtime"]
    assert safety["hardwareDecision"] == "deny"
    assert safety["frontendIsAuthority"] is False
    assert safety["parameterWriteAllowed"] is False
    assert safety["armAllowed"] is False
    assert safety["flightAllowed"] is False


def test_application_never_requires_evidence_test_inside_product_checkout() -> None:
    application = load()
    contracts = application["contracts"]
    forbidden = contracts["forbiddenEvidenceOnlyProductTest"]
    assert contracts["applicationValidatedExternally"] is True
    assert contracts["evidenceOnlyApplicationTestRequiredInProductSource"] is False
    assert forbidden not in contracts["productTests"]
    assert forbidden.endswith("test_field_yellow_560f574_application.py")


def test_application_integrity_and_plan_only_runner_pass_without_audit_root() -> None:
    application = load()
    assert canonical_sha(application) == application["integrity"]["canonicalSha256"]
    audit_root = Path(application["ownedPaths"]["auditRunRoot"])
    assert not audit_root.exists()
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--application",
            str(APPLICATION),
            "--expected-application-sha256",
            hashlib.sha256(APPLICATION.read_bytes()).hexdigest(),
            "--plan-only",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "pass-plan-only-no-artifact-read"
    assert not audit_root.exists()
