#!/usr/bin/env python3
"""Audit one frozen Field installer without rebuilding, signing, or installing it."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

APPLICATION_KIND = "dronedream-field-artifact-bound-postbuild-audit-application"
TOOL_PATH = "distribution/editions/field/build/run-artifact-bound-postbuild-audit.py"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PRODUCT_TESTS = (
    "distribution/tests/test_field_prerelease_audit.py",
    "distribution/tests/test_field_desktop_profile.py",
    "distribution/tests/test_field_lifecycle_contract.py",
    "distribution/tests/test_field_brand_assets.py",
    "distribution/tests/test_field_auth_common_core_proposal.py",
    "distribution/tests/test_field_source_bound_preflight.py",
)
FORBIDDEN_PRODUCT_TEST = "distribution/tests/test_field_yellow_560f574_application.py"
FORBIDDEN_PAYLOAD_TOKENS = ("gazebo", "hitl", "sitl", "simulator")


class AuditError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "integrity"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return _sha256_bytes(encoded)


def _read_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(document, dict), f"expected a JSON object: {path}")
    return document


def _exact_file(path_value: str, *, label: str) -> Path:
    path = Path(path_value)
    _require(path.is_absolute(), f"{label} path must be absolute")
    _require(path.is_file() and not path.is_symlink(), f"{label} must be a regular file")
    return path.resolve()


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _assert_record(path: Path, record: dict[str, Any], *, label: str) -> None:
    actual = _file_record(path)
    _require(actual["bytes"] == record["bytes"], f"{label} byte length drifted")
    _require(actual["sha256"] == record["sha256"], f"{label} SHA-256 drifted")


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    log_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if log_path is not None:
        log_path.write_text(
            completed.stdout + "\n--- stderr ---\n" + completed.stderr,
            encoding="utf-8",
        )
    if completed.returncode != 0:
        raise AuditError(f"read-only audit command failed ({completed.returncode}): {command[0]}")
    return completed


def _git(repo: Path, *arguments: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        check=False,
        text=not binary,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace") if binary else completed.stderr
        raise AuditError(f"Git command failed: {stderr.strip()}")
    output = completed.stdout
    return output if binary else output.strip()


def _validate_plan(application: dict[str, Any]) -> None:
    _require(application.get("schemaVersion") == 1, "application schema version drifted")
    _require(application.get("kind") == APPLICATION_KIND, "application kind drifted")
    _require(application.get("editionId") == "field", "application edition drifted")
    _require(
        application.get("status") == "prepared-awaiting-exact-start-signal",
        "application is not awaiting an exact start signal",
    )
    integrity = application.get("integrity", {})
    _require(
        integrity.get("canonicalization")
        == "UTF-8 JSON sorted keys compact separators excluding integrity",
        "application canonicalization drifted",
    )
    _require(
        _canonical_sha(application) == integrity.get("canonicalSha256"),
        "application canonical SHA-256 drifted",
    )

    source = application["source"]
    _require(COMMIT_RE.fullmatch(source["productCommit"]) is not None, "invalid product commit")
    _require(COMMIT_RE.fullmatch(source["productTree"]) is not None, "invalid product tree")
    _require(
        source["productCommit"] != source["evidenceHeadAtPreparation"],
        "evidence is not product source",
    )

    execution = application["execution"]
    _require(execution["auditCountMaximum"] == 1, "audit count must be exactly one")
    _require(execution["retryCountMaximum"] == 0, "audit retry must remain zero")
    _require(
        execution["createsAuditRootOnlyAfterPrechecks"] is True,
        "audit root precheck boundary drifted",
    )
    for key in (
        "buildAllowed",
        "signingAllowed",
        "installationAllowed",
        "applicationLaunchAllowed",
        "runtimeMigrationAllowed",
        "deviceOrHardwareAllowed",
        "simulationExecutionAllowed",
        "deploymentAllowed",
    ):
        _require(execution[key] is False, f"forbidden execution capability enabled: {key}")

    tests = tuple(application["contracts"]["productTests"])
    _require(tests == PRODUCT_TESTS, "product test allowlist drifted")
    _require(FORBIDDEN_PRODUCT_TEST not in tests, "evidence-only test leaked into product tests")
    _require(
        application["contracts"]["applicationValidatedExternally"] is True,
        "external evidence boundary drifted",
    )
    _require(
        application["safety"]["validatedHardwarePackCount"] == 0, "validated pack count drifted"
    )
    _require(application["safety"]["hardwareDecision"] == "deny", "hardware decision drifted")
    _require(application["safety"]["frontendIsAuthority"] is False, "frontend became authority")

    paths = application["ownedPaths"]
    run_root = Path(paths["auditRunRoot"])
    visualization_root = Path(paths["visualizationRoot"])
    historical_root = Path(paths["historicalBuildRunRoot"])
    cargo_target = Path(paths["cargoTarget"])
    _require(run_root.is_absolute(), "audit run root must be absolute")
    _require(visualization_root.is_absolute(), "visualization root must be absolute")
    _require(historical_root.is_absolute(), "historical build root must be absolute")
    _require(cargo_target.is_absolute(), "Cargo target must be absolute")
    _require(
        run_root.parent == visualization_root,
        "audit run root escaped its exact visualization root",
    )
    _require(
        historical_root.parent == visualization_root,
        "historical build root escaped its exact visualization root",
    )
    _require(run_root != historical_root, "audit run root reuses historical build root")
    _require(paths["auditRunRootMustBeAbsent"] is True, "audit root freshness requirement drifted")
    _require(
        paths["historicalBuildRunRootReadOnly"] is True, "historical build root is not read-only"
    )
    _require(
        paths["historicalStaticExtractionReusable"] is False,
        "historical extraction cannot satisfy the audit",
    )

    for group in ("artifactFiles", "buildEvidence", "buildOutputs"):
        for record in application["bindings"][group]:
            _require(Path(record["path"]).is_absolute(), f"{group} path must be absolute")
            _require(
                isinstance(record["bytes"], int) and record["bytes"] >= 0, f"{group} bytes invalid"
            )
            _require(SHA256_RE.fullmatch(record["sha256"]) is not None, f"{group} SHA invalid")
            bound_path = Path(record["path"])
            expected_root = cargo_target if group == "buildOutputs" else historical_root
            _require(
                bound_path.is_relative_to(expected_root),
                f"{group} path escaped its exact owned root",
            )

    payload = application["payloadAudit"]
    _require(payload["runtimeProfile"] == "field-lightweight", "Field profile drifted")
    _require(payload["includesLargeSimulator"] is False, "large simulator payload enabled")
    _require(
        payload["forbiddenTokens"] == list(FORBIDDEN_PAYLOAD_TOKENS),
        "forbidden payload tokens drifted",
    )
    _require(
        payload["expectedEntryCount"] == len(payload["expectedEntries"]),
        "payload entry count drifted",
    )


def _verify_blob_binding(repo: Path, commit: str, binding: dict[str, str]) -> None:
    relative = PurePosixPath(binding["path"])
    _require(
        not relative.is_absolute() and ".." not in relative.parts,
        "source binding escaped repository",
    )
    blob = _git(repo, "rev-parse", f"{commit}:{relative.as_posix()}")
    _require(blob == binding["gitBlob"], f"Git blob drifted: {relative}")
    blob_bytes = _git(repo, "cat-file", "blob", blob, binary=True)
    assert isinstance(blob_bytes, bytes)
    _require(
        _sha256_bytes(blob_bytes) == binding["canonicalBlobSha256"],
        f"canonical blob SHA-256 drifted: {relative}",
    )


def _verify_evidence(application: dict[str, Any], expected_head: str) -> Path:
    source = application["source"]
    evidence_root = Path(source["evidenceRepoRoot"]).resolve()
    _require(evidence_root.is_dir(), "evidence repository is unavailable")
    _require(COMMIT_RE.fullmatch(expected_head) is not None, "expected evidence HEAD is invalid")
    _require(_git(evidence_root, "rev-parse", "HEAD") == expected_head, "evidence HEAD drifted")
    _require(
        _git(evidence_root, "rev-parse", "@{upstream}") == expected_head,
        "evidence upstream drifted",
    )
    _require(
        _git(evidence_root, "status", "--porcelain=v1", "--untracked-files=all") == "",
        "evidence worktree is dirty",
    )
    tool = application["tool"]
    _verify_blob_binding(evidence_root, expected_head, tool)
    return evidence_root


def _verify_product(application: dict[str, Any]) -> Path:
    source = application["source"]
    product_root = Path(source["productRoot"]).resolve()
    _require(product_root.is_dir(), "product checkout is unavailable")
    product_commit = source["productCommit"]
    _require(_git(product_root, "rev-parse", "HEAD") == product_commit, "product HEAD drifted")
    _require(
        _git(product_root, "rev-parse", f"{product_commit}^{{tree}}") == source["productTree"],
        "product tree drifted",
    )
    status = str(_git(product_root, "status", "--porcelain=v1", "--untracked-files=all"))
    lines = [line for line in status.splitlines() if line]
    unexpected = [
        line
        for line in lines
        if not (line.startswith("?? frontend/field-dist/") and len(line) > 25)
    ]
    _require(not unexpected, f"product checkout has unexpected changes: {unexpected}")
    _require(lines, "expected exact generated frontend/field-dist output is absent")
    for binding in application["sourceParity"]["gitBlobs"]:
        _verify_blob_binding(product_root, product_commit, binding)
    for test_path in PRODUCT_TESTS:
        _git(product_root, "cat-file", "-e", f"{product_commit}:{test_path}")
    try:
        _git(product_root, "cat-file", "-e", f"{product_commit}:{FORBIDDEN_PRODUCT_TEST}")
    except AuditError:
        pass
    else:
        raise AuditError("evidence-only application test unexpectedly entered product source")
    return product_root


def _verify_bound_files(application: dict[str, Any]) -> dict[str, dict[str, Any]]:
    observed: dict[str, dict[str, Any]] = {}
    for group in ("artifactFiles", "buildEvidence", "buildOutputs"):
        for record in application["bindings"][group]:
            path = _exact_file(record["path"], label=record["id"])
            _assert_record(path, record, label=record["id"])
            observed[record["id"]] = _file_record(path)
    return observed


def _verify_artifact_metadata(application: dict[str, Any]) -> None:
    records = {record["id"]: record for record in application["bindings"]["artifactFiles"]}
    installer = Path(records["installer"]["path"])
    checksum = Path(records["checksum"]["path"]).read_text(encoding="ascii").strip()
    _require(
        checksum == f"{records['installer']['sha256']}  DroneDream-Field-1.0.0.exe",
        "checksum sidecar does not bind the frozen installer",
    )
    signature = Path(records["updaterSignature"]["path"]).read_text(encoding="utf-8").strip()
    metadata = _read_json(Path(records["metadata"]["path"]))
    _require(metadata.get("version") == "1.0.0", "updater metadata version drifted")
    platform = metadata.get("platforms", {}).get("windows-x86_64", {})
    _require(
        platform.get("signature", "").strip() == signature,
        "metadata signature differs from sidecar",
    )
    _require(
        platform.get("url") == application["artifactIdentity"]["metadataUrl"],
        "metadata URL family drifted",
    )
    _require(installer.name == "DroneDream-Field-1.0.0.exe", "installer filename drifted")


def _verify_build_receipts(application: dict[str, Any]) -> None:
    required_ids = {
        "buildProcessReceipt",
        "preflightReceipt",
        "postbuildFailureReceipt",
    }
    evidence = {
        record["id"]: _read_json(Path(record["path"]))
        for record in application["bindings"]["buildEvidence"]
        if record["id"] in required_ids
    }
    _require(set(evidence) == required_ids, "required build receipts are not exactly bound")

    source = application["source"]["productCommit"]
    process = evidence["buildProcessReceipt"]
    _require(
        process.get("kind") == "dronedream-field-yellow-build-process",
        "build receipt kind drifted",
    )
    _require(process.get("sourceCommit") == source, "build receipt source drifted")
    _require(process.get("exitCode") == 0, "frozen build was not successful")
    _require(
        process.get("invocationCounts")
        == {
            "frontend": 1,
            "tauri": 1,
            "cargo": 1,
            "nsis": 1,
            "freshAttempt": 1,
            "buildScript": 1,
        },
        "frozen build invocation counts drifted",
    )
    _require(process.get("cargoBuildJobs") == 2, "Cargo build job count drifted")

    preflight = evidence["preflightReceipt"]
    _require(
        preflight.get("kind") == "dronedream-field-yellow-preflight-receipt",
        "preflight receipt kind drifted",
    )
    _require(
        preflight.get("decision") == "allow-one-build-after-preflight",
        "preflight decision drifted",
    )
    _require(
        preflight.get("source", {}).get("productCommit") == source,
        "preflight source drifted",
    )
    _require(
        preflight.get("configuration", {}).get("profile") == "field-lightweight",
        "preflight profile drifted",
    )
    _require(preflight.get("buildInvoked") is False, "preflight receipt claims build execution")
    _require(
        preflight.get("safety", {}).get("hardwareDecision") == "deny",
        "preflight hardware decision drifted",
    )

    failure = evidence["postbuildFailureReceipt"]
    _require(
        failure.get("kind") == "dronedream-field-yellow-postbuild-failure-receipt",
        "postbuild failure receipt kind drifted",
    )
    _require(failure.get("productSource") == source, "postbuild failure source drifted")
    _require(
        failure.get("postbuildFailure", {}).get("classification")
        == "evidence-only-test-path-was-not-present-in-exact-product-source",
        "postbuild failure classification drifted",
    )
    _require(
        failure.get("postbuildFailure", {}).get("testsExecuted") == 0,
        "old postbuild tests unexpectedly executed",
    )
    _require(failure.get("build", {}).get("retryCount") == 0, "frozen build retry count drifted")
    _require(
        failure.get("readiness", {}).get("staticAuditComplete") is False,
        "old failure claims completed audit",
    )


def _verify_pe(path: Path, application: dict[str, Any]) -> dict[str, Any]:
    data = path.read_bytes()
    _require(data[:2] == b"MZ", "installer is not a PE file")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    _require(data[pe_offset : pe_offset + 4] == b"PE\0\0", "PE signature is invalid")
    optional_offset = pe_offset + 24
    magic = struct.unpack_from("<H", data, optional_offset)[0]
    data_directory_offset = optional_offset + (112 if magic == 0x20B else 96)
    certificate_offset, certificate_bytes = struct.unpack_from(
        "<II", data, data_directory_offset + 8 * 4
    )
    _require(certificate_offset == 0 and certificate_bytes == 0, "unexpected PE certificate table")
    return {
        "magic": f"0x{magic:04x}",
        "certificateTableOffset": certificate_offset,
        "certificateTableBytes": certificate_bytes,
        "authenticodeState": application["artifactIdentity"]["authenticodeState"],
    }


def _extract_payload(
    application: dict[str, Any], run_root: Path
) -> tuple[Path, list[dict[str, Any]]]:
    extractor = _exact_file(application["payloadAudit"]["extractor"]["path"], label="extractor")
    _assert_record(extractor, application["payloadAudit"]["extractor"], label="extractor")
    installer_record = next(
        record for record in application["bindings"]["artifactFiles"] if record["id"] == "installer"
    )
    payload_root = run_root / "payload-static"
    payload_root.mkdir()
    _run(
        [str(extractor), "x", "-y", f"-o{payload_root}", installer_record["path"]],
        cwd=run_root,
        log_path=run_root / "payload-extraction.log",
    )
    inventory: list[dict[str, Any]] = []
    for path in sorted(payload_root.rglob("*")):
        _require(not path.is_symlink(), "static payload contains a symlink")
        if path.is_file():
            relative = path.relative_to(payload_root).as_posix()
            inventory.append(
                {"path": relative, "bytes": path.stat().st_size, "sha256": _sha256_file(path)}
            )
    expected_entries = application["payloadAudit"]["expectedEntries"]
    _require(
        [entry["path"] for entry in inventory] == expected_entries,
        "installer payload entry list drifted",
    )
    for entry in inventory:
        lowered = entry["path"].lower()
        _require(
            not any(token in lowered for token in FORBIDDEN_PAYLOAD_TOKENS),
            f"forbidden simulator payload found: {entry['path']}",
        )
    (run_root / "payload-inventory.json").write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return payload_root, inventory


def _verify_payload_bindings(
    application: dict[str, Any], product_root: Path, payload_root: Path
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for binding in application["payloadAudit"]["sourceParity"]:
        payload_path = payload_root / PurePosixPath(binding["payloadPath"])
        source_path = product_root / PurePosixPath(binding["sourcePath"])
        _require(
            payload_path.is_file() and source_path.is_file(), "payload/source parity file missing"
        )
        payload_sha = _sha256_file(payload_path)
        source_sha = _sha256_file(source_path)
        _require(payload_sha == binding["sha256"], f"payload SHA drifted: {binding['payloadPath']}")
        _require(source_sha == binding["sha256"], f"source SHA drifted: {binding['sourcePath']}")
        results.append({**binding, "decision": "pass"})
    return results


def _verify_binary_parity(application: dict[str, Any], payload_root: Path) -> dict[str, Any]:
    staging = next(
        record
        for record in application["bindings"]["buildOutputs"]
        if record["id"] == "stagingApplication"
    )
    source = Path(staging["path"]).read_bytes()
    extracted = (payload_root / "drone-dream-desktop.exe").read_bytes()
    _require(len(source) == len(extracted), "staging and extracted app lengths differ")
    differences = [
        {"offset": index, "staging": left, "payload": right}
        for index, (left, right) in enumerate(zip(source, extracted, strict=True))
        if left != right
    ]
    _require(
        differences == application["payloadAudit"]["expectedApplicationByteDifferences"],
        "application parity drifted",
    )
    return {"bytes": len(source), "differences": differences, "decision": "pass"}


def _load_product_module(product_root: Path, relative_path: str, name: str) -> ModuleType:
    path = product_root / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    _require(
        spec is not None and spec.loader is not None, f"cannot load product module: {relative_path}"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _verify_engine_pack(application: dict[str, Any], product_root: Path) -> dict[str, Any]:
    outputs = {record["id"]: record for record in application["bindings"]["buildOutputs"]}
    tool = _load_product_module(
        product_root,
        "distribution/tools/field_prerelease_audit.py",
        "dronedream_field_frozen_artifact_audit",
    )
    result = tool.audit_engine_pack_payload(
        descriptor_path=Path(outputs["enginePackDescriptor"]["path"]),
        archive_path=Path(outputs["enginePackArchive"]["path"]),
        common_core_commit=application["commonCore"]["latestProductDonor"],
        common_core_hash=application["commonCore"]["bindingSha256"],
    )
    _require(result["profileId"] == "field-lightweight", "Engine Pack profile drifted")
    _require(result["includesLargeSimulator"] is False, "Engine Pack includes large simulator")
    _require(result["forbiddenPayloads"] == [], "Engine Pack has forbidden simulator payload")
    _require(
        result["registrySummary"]["validatedHardwarePackCount"] == 0,
        "validated pack count is not zero",
    )
    _require(
        result["retainedSafetyResources"]["zeroValidatedPackDecision"] == "deny",
        "zero-pack decision drifted",
    )
    return result


def _run_product_contracts(
    application: dict[str, Any], product_root: Path, run_root: Path
) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    completed = _run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *PRODUCT_TESTS],
        cwd=product_root,
        env=env,
        log_path=run_root / "product-contract-tests.log",
    )
    powershell = application["tools"]["powershell"]
    for script, log_name in (
        ("desktop/scripts/verify-nsis-template.ps1", "nsis-template.log"),
        ("desktop/scripts/verify-updater-build-contract.ps1", "updater-build-contract.log"),
    ):
        _run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(product_root / script),
            ],
            cwd=product_root,
            env=env,
            log_path=run_root / log_name,
        )
    return {
        "tests": list(PRODUCT_TESTS),
        "pytestSummary": completed.stdout.strip(),
        "decision": "pass",
    }


def _write_new_json(path: Path, document: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as target:
        json.dump(document, target, indent=2, ensure_ascii=False)
        target.write("\n")


def _actual_audit(application: dict[str, Any], expected_evidence_head: str) -> int:
    evidence_root = _verify_evidence(application, expected_evidence_head)
    product_root = _verify_product(application)
    bound_before = _verify_bound_files(application)
    _verify_artifact_metadata(application)
    _verify_build_receipts(application)
    run_root = Path(application["ownedPaths"]["auditRunRoot"])
    _require(not run_root.exists(), "audit run root is not fresh")
    _require(run_root.parent.is_dir(), "audit run root parent is unavailable")

    run_root.mkdir()
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_new_json(
        run_root / "audit-start-receipt.json",
        {
            "schemaVersion": 1,
            "kind": "dronedream-field-artifact-bound-postbuild-audit-start",
            "auditCount": 1,
            "retryCount": 0,
            "productSource": application["source"]["productCommit"],
            "evidenceHead": expected_evidence_head,
            "startedAt": started_at,
        },
    )
    try:
        payload_root, inventory = _extract_payload(application, run_root)
        parity = _verify_payload_bindings(application, product_root, payload_root)
        binary_parity = _verify_binary_parity(application, payload_root)
        engine_pack = _verify_engine_pack(application, product_root)
        contracts = _run_product_contracts(application, product_root, run_root)
        pe = _verify_pe(Path(application["artifactIdentity"]["path"]), application)
        bound_after = _verify_bound_files(application)
        _require(
            bound_before == bound_after, "frozen artifact or build evidence mutated during audit"
        )
        _require(
            _git(evidence_root, "status", "--porcelain=v1", "--untracked-files=all") == "",
            "evidence worktree mutated during audit",
        )
        receipt = {
            "schemaVersion": 1,
            "kind": "dronedream-field-artifact-bound-postbuild-audit-receipt",
            "decision": "pass-static-audit-lifecycle-still-required",
            "auditCount": 1,
            "retryCount": 0,
            "productSource": application["source"]["productCommit"],
            "evidenceHead": expected_evidence_head,
            "artifact": bound_after["installer"],
            "pe": pe,
            "payload": {
                "entryCount": len(inventory),
                "fieldLightweight": True,
                "largeSimulatorPresent": False,
                "sourceParity": parity,
                "applicationParity": binary_parity,
            },
            "enginePack": engine_pack,
            "contracts": contracts,
            "safety": {
                "validatedHardwarePackCount": 0,
                "hardwareDecision": "deny",
                "frontendIsAuthority": False,
            },
            "readiness": {
                "staticAuditComplete": True,
                "releaseReady": False,
                "websiteReady": False,
                "lifecycleRequired": True,
            },
            "completedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        _write_new_json(run_root / "audit-receipt.json", receipt)
    except Exception as error:
        _write_new_json(
            run_root / "audit-failure-receipt.json",
            {
                "schemaVersion": 1,
                "kind": "dronedream-field-artifact-bound-postbuild-audit-failure",
                "decision": "freeze-failed-no-retry",
                "auditCount": 1,
                "retryCount": 0,
                "error": str(error),
                "failedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
        raise
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", required=True)
    parser.add_argument("--expected-application-sha256", required=True)
    parser.add_argument("--expected-evidence-head")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    try:
        application_path = _exact_file(args.application, label="audit application")
        _require(
            SHA256_RE.fullmatch(args.expected_application_sha256) is not None,
            "expected application SHA-256 is invalid",
        )
        _require(
            _sha256_file(application_path) == args.expected_application_sha256,
            "application file SHA-256 drifted",
        )
        application = _read_json(application_path)
        _validate_plan(application)
        if args.plan_only:
            print(
                json.dumps(
                    {
                        "kind": "dronedream-field-artifact-bound-postbuild-audit-plan-check",
                        "decision": "pass-plan-only-no-artifact-read",
                        "auditRunRootCreated": False,
                    },
                    sort_keys=True,
                )
            )
            return 0
        _require(args.expected_evidence_head is not None, "exact evidence HEAD is required")
        return _actual_audit(application, args.expected_evidence_head)
    except (AuditError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Field artifact audit error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
