from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = (
    ROOT / "distribution" / "editions" / "field" / "build" / "run-artifact-bound-postbuild-audit.py"
)

SPEC = importlib.util.spec_from_file_location("field_artifact_audit_tests", TOOL)
assert SPEC and SPEC.loader
audit: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


def canonical_sha(document: dict[str, object]) -> str:
    payload = {key: value for key, value in document.items() if key != "integrity"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def fixture_application(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    dummy = root / "dummy.bin"
    dummy.write_bytes(b"bound")
    record = {
        "id": "dummy",
        "path": str(dummy),
        "bytes": dummy.stat().st_size,
        "sha256": hashlib.sha256(dummy.read_bytes()).hexdigest(),
    }
    application: dict[str, object] = {
        "schemaVersion": 1,
        "kind": audit.APPLICATION_KIND,
        "editionId": "field",
        "status": "prepared-awaiting-exact-start-signal",
        "source": {
            "productCommit": "1" * 40,
            "productTree": "2" * 40,
            "evidenceHeadAtPreparation": "3" * 40,
            "productRoot": str(root / "product"),
            "evidenceRepoRoot": str(root / "evidence"),
        },
        "tool": {
            "path": audit.TOOL_PATH,
            "gitBlob": "4" * 40,
            "canonicalBlobSha256": "5" * 64,
        },
        "execution": {
            "auditCountMaximum": 1,
            "retryCountMaximum": 0,
            "createsAuditRootOnlyAfterPrechecks": True,
            "buildAllowed": False,
            "signingAllowed": False,
            "installationAllowed": False,
            "applicationLaunchAllowed": False,
            "runtimeMigrationAllowed": False,
            "deviceOrHardwareAllowed": False,
            "simulationExecutionAllowed": False,
            "deploymentAllowed": False,
        },
        "contracts": {
            "productTests": list(audit.PRODUCT_TESTS),
            "applicationValidatedExternally": True,
        },
        "safety": {
            "validatedHardwarePackCount": 0,
            "hardwareDecision": "deny",
            "frontendIsAuthority": False,
        },
        "ownedPaths": {
            "visualizationRoot": str(root),
            "historicalBuildRunRoot": str(root / "historical"),
            "cargoTarget": str(root / "cargo"),
            "auditRunRoot": str(root / "audit-root"),
            "auditRunRootMustBeAbsent": True,
            "historicalBuildRunRootReadOnly": True,
            "historicalStaticExtractionReusable": False,
        },
        "bindings": {
            "artifactFiles": [{**record, "path": str(root / "historical" / "dummy.bin")}],
            "buildEvidence": [{**record, "path": str(root / "historical" / "dummy.bin")}],
            "buildOutputs": [{**record, "path": str(root / "cargo" / "dummy.bin")}],
        },
        "sourceParity": {"gitBlobs": []},
        "payloadAudit": {
            "runtimeProfile": "field-lightweight",
            "includesLargeSimulator": False,
            "forbiddenTokens": list(audit.FORBIDDEN_PAYLOAD_TOKENS),
            "expectedEntryCount": 1,
            "expectedEntries": ["drone-dream-desktop.exe"],
        },
        "integrity": {
            "canonicalization": "UTF-8 JSON sorted keys compact separators excluding integrity",
            "canonicalSha256": "",
        },
    }
    application["integrity"]["canonicalSha256"] = canonical_sha(application)  # type: ignore[index]
    path = root / "application.json"
    path.write_text(json.dumps(application, indent=2) + "\n", encoding="utf-8")
    return path, application


def run_plan(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--application",
            str(path),
            "--expected-application-sha256",
            hashlib.sha256(path.read_bytes()).hexdigest(),
            "--plan-only",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def rewrite(path: Path, document: dict[str, object]) -> None:
    document["integrity"]["canonicalSha256"] = canonical_sha(document)  # type: ignore[index]
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def json_record(path: Path, identifier: str, document: dict[str, object]) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return {
        "id": identifier,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def test_plan_only_does_not_create_audit_root_or_read_artifact(tmp_path: Path) -> None:
    path, application = fixture_application(tmp_path)
    result = run_plan(path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "pass-plan-only-no-artifact-read"
    assert payload["auditRunRootCreated"] is False
    assert not Path(application["ownedPaths"]["auditRunRoot"]).exists()  # type: ignore[index]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda app: app["execution"].__setitem__("buildAllowed", True), "buildAllowed"),
        (lambda app: app["execution"].__setitem__("signingAllowed", True), "signingAllowed"),
        (
            lambda app: app["execution"].__setitem__("installationAllowed", True),
            "installationAllowed",
        ),
        (lambda app: app["execution"].__setitem__("auditCountMaximum", 2), "exactly one"),
        (lambda app: app["execution"].__setitem__("retryCountMaximum", 1), "remain zero"),
    ],
)
def test_execution_scope_expansion_fails_closed(tmp_path: Path, mutation, message: str) -> None:
    path, application = fixture_application(tmp_path)
    mutation(application)
    rewrite(path, application)

    result = run_plan(path)

    assert result.returncode == 2
    assert message in result.stderr


def test_evidence_only_product_test_is_rejected(tmp_path: Path) -> None:
    path, application = fixture_application(tmp_path)
    application["contracts"]["productTests"].append(audit.FORBIDDEN_PRODUCT_TEST)  # type: ignore[index]
    rewrite(path, application)

    result = run_plan(path)

    assert result.returncode == 2
    assert "product test allowlist drifted" in result.stderr


def test_application_hash_and_canonical_hash_both_fail_closed(tmp_path: Path) -> None:
    path, application = fixture_application(tmp_path)
    wrong_file_hash = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--application",
            str(path),
            "--expected-application-sha256",
            "0" * 64,
            "--plan-only",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert wrong_file_hash.returncode == 2
    assert "application file SHA-256 drifted" in wrong_file_hash.stderr

    drifted = deepcopy(application)
    drifted["safety"]["hardwareDecision"] = "allow"  # type: ignore[index]
    path.write_text(json.dumps(drifted, indent=2) + "\n", encoding="utf-8")
    result = run_plan(path)
    assert result.returncode == 2
    assert "application canonical SHA-256 drifted" in result.stderr


def test_build_receipt_semantics_bind_single_success_and_old_zero_test_failure(
    tmp_path: Path,
) -> None:
    source = "1" * 40
    process = {
        "kind": "dronedream-field-yellow-build-process",
        "sourceCommit": source,
        "exitCode": 0,
        "invocationCounts": {
            "frontend": 1,
            "tauri": 1,
            "cargo": 1,
            "nsis": 1,
            "freshAttempt": 1,
            "buildScript": 1,
        },
        "cargoBuildJobs": 2,
    }
    preflight = {
        "kind": "dronedream-field-yellow-preflight-receipt",
        "decision": "allow-one-build-after-preflight",
        "source": {"productCommit": source},
        "configuration": {"profile": "field-lightweight"},
        "buildInvoked": False,
        "safety": {"hardwareDecision": "deny"},
    }
    failure = {
        "kind": "dronedream-field-yellow-postbuild-failure-receipt",
        "productSource": source,
        "postbuildFailure": {
            "classification": ("evidence-only-test-path-was-not-present-in-exact-product-source"),
            "testsExecuted": 0,
        },
        "build": {"retryCount": 0},
        "readiness": {"staticAuditComplete": False},
    }
    application = {
        "source": {"productCommit": source},
        "bindings": {
            "buildEvidence": [
                json_record(tmp_path / "process.json", "buildProcessReceipt", process),
                json_record(tmp_path / "preflight.json", "preflightReceipt", preflight),
                json_record(tmp_path / "failure.json", "postbuildFailureReceipt", failure),
            ]
        },
    }

    audit._verify_build_receipts(application)

    failure["postbuildFailure"]["testsExecuted"] = 1  # type: ignore[index]
    application["bindings"]["buildEvidence"][2] = json_record(  # type: ignore[index]
        tmp_path / "failure.json", "postbuildFailureReceipt", failure
    )
    with pytest.raises(audit.AuditError, match="unexpectedly executed"):
        audit._verify_build_receipts(application)


def test_payload_profile_and_hardware_authority_fail_closed(tmp_path: Path) -> None:
    path, application = fixture_application(tmp_path)
    application["payloadAudit"]["runtimeProfile"] = "unified-sim-lab"  # type: ignore[index]
    rewrite(path, application)
    result = run_plan(path)
    assert result.returncode == 2
    assert "Field profile drifted" in result.stderr

    path, application = fixture_application(tmp_path / "second")
    application["safety"]["validatedHardwarePackCount"] = 1  # type: ignore[index]
    rewrite(path, application)
    result = run_plan(path)
    assert result.returncode == 2
    assert "validated pack count drifted" in result.stderr


def test_runner_has_no_build_sign_install_or_launch_process_path() -> None:
    source = TOOL.read_text(encoding="utf-8")
    forbidden_invocations = (
        "build-windows-llvm.ps1",
        "verify-edition-identity-nsis.ps1",
        "invoke-tauri-updater-signer.ps1",
        "makensis.exe",
        "tauri.js",
        "cargo.exe",
        "Start-Process",
    )
    for token in forbidden_invocations:
        assert token not in source
    assert audit.FORBIDDEN_PRODUCT_TEST not in audit.PRODUCT_TESTS
    assert '-p", "no:cacheprovider' in source
    assert "PYTHONDONTWRITEBYTECODE" in source
