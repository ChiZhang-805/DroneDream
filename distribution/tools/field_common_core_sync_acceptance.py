from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

REQUEST_KIND = "dronedream-field-common-core-sync-acceptance-request"
RECEIPT_KIND = "dronedream-field-common-core-sync-acceptance-receipt"
FIELD_BRANCH = "codex/software-field"
UNIVERSAL_BRANCH = "codex/software"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

BACKFLOW_GROUPS: dict[str, tuple[str, ...]] = {
    "universal-core-common-core-commit-binding": (
        "distribution/build-plans/software-1.0.0-065382b68bfa.v1.json",
        "distribution/build-plans/software-1.0.0-065382b68bfa.v1.json.sha256",
        "distribution/schemas/edition-build-plan.schema.json",
        "distribution/tests/test_edition_build_planner.py",
        "distribution/tools/edition_build_planner.py",
    ),
    "universal-core-engine-pack-edition-profile": (
        "desktop/scripts/verify-updater-build-contract.ps1",
        "desktop/src-tauri/build.rs",
        "engine-pack/manifest.schema.json",
        "engine-pack/tests/test_engine_pack.py",
        "engine-pack/tests/test_engine_pack_manager.py",
        "engine-pack/tools/engine_pack.py",
        "runtime/scripts/edition-safety-gate.py",
    ),
    "universal-core-field-contract-retention-hook": (
        "engine-pack/tools/engine_pack.py",
        "runtime/scripts/edition-safety-gate.py",
    ),
}

FIELD_SPECIFIC_PATHS = (
    "distribution/schemas/field-common-drift-readiness-audit.schema.json",
    "distribution/schemas/field-lifecycle-contract.schema.json",
    "distribution/schemas/field-prerelease-audit.schema.json",
    "distribution/tests/test_field_common_drift_readiness_audit.py",
    "distribution/tests/test_field_lifecycle_contract.py",
    "distribution/tests/test_field_prerelease_audit.py",
    "distribution/tools/field_common_drift_readiness_audit.py",
    "distribution/tools/field_lifecycle_contract.py",
    "distribution/tools/field_prerelease_audit.py",
)

PROTECTED_EVIDENCE_PATHS = (
    "artifacts/test-runs/sim-preview-1.0.0-2aec69e/DroneDream-Sim-1.0.0.exe.sha256",
    "artifacts/test-runs/sim-preview-1.0.0-2aec69e/handoff-manifest.json",
    "artifacts/test-runs/sim-preview-1.0.0-2aec69e/handoff-manifest.json.sha256",
    "artifacts/test-runs/sim-preview-1.0.0-2aec69e/release-receipt.json",
    "artifacts/test-runs/sim-preview-1.0.0-2aec69e/release-receipt.json.sha256",
)

REQUIRED_TOP_LEVEL_KEYS = {
    "schemaVersion",
    "kind",
    "universalSource",
    "fieldSource",
    "backflowGroups",
    "fieldSpecificIsolation",
    "protectedEvidence",
    "safetyGates",
}


class FieldCommonCoreSyncAcceptanceError(ValueError):
    pass


def canonical_bytes(document: object) -> bytes:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_canonical(document: object) -> str:
    return sha256_bytes(canonical_bytes(document))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git failed"
        raise FieldCommonCoreSyncAcceptanceError(detail)
    return completed.stdout


def git_blob_sha256(repo_root: Path, ref: str, path: str) -> str:
    payload = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{ref}:{path}"],
        check=False,
        capture_output=True,
    )
    if payload.returncode != 0:
        raise FieldCommonCoreSyncAcceptanceError(f"unable to read {path} at {ref}")
    return sha256_bytes(payload.stdout)


def current_head(repo_root: Path = ROOT) -> str:
    head = _run_git(repo_root, "rev-parse", "HEAD").strip()
    if COMMIT_RE.fullmatch(head) is None:
        raise FieldCommonCoreSyncAcceptanceError("HEAD is not a full Git commit")
    return head


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise FieldCommonCoreSyncAcceptanceError(f"{label} must be a lowercase SHA-256")
    return value


def _require_commit(value: object, label: str) -> str:
    if not isinstance(value, str) or COMMIT_RE.fullmatch(value) is None:
        raise FieldCommonCoreSyncAcceptanceError(f"{label} must be a full lowercase Git SHA")
    return value


def _path_map(records: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list):
        raise FieldCommonCoreSyncAcceptanceError(f"{label} must be an array")
    mapped: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(records):
        if not isinstance(raw, dict) or "path" not in raw:
            raise FieldCommonCoreSyncAcceptanceError(f"{label}[{index}] is invalid")
        path = raw["path"]
        if not isinstance(path, str) or path in mapped:
            raise FieldCommonCoreSyncAcceptanceError(f"{label}[{index}] path is invalid")
        mapped[path] = raw
    return mapped


def field_path_hashes(repo_root: Path = ROOT) -> dict[str, str]:
    paths = sorted(
        set().union(*BACKFLOW_GROUPS.values()).union(FIELD_SPECIFIC_PATHS)
    )
    return {path: sha256_file(repo_root / path) for path in paths}


def protected_evidence_base_hashes(
    *,
    repo_root: Path = ROOT,
    base_ref: str = "origin/codex/software",
) -> dict[str, str]:
    return {path: git_blob_sha256(repo_root, base_ref, path) for path in PROTECTED_EVIDENCE_PATHS}


def validate_acceptance_request(request: dict[str, Any], *, repo_root: Path = ROOT) -> dict[str, Any]:
    if set(request) != REQUIRED_TOP_LEVEL_KEYS:
        raise FieldCommonCoreSyncAcceptanceError("sync acceptance request fields drifted")
    if request["schemaVersion"] != 1 or request["kind"] != REQUEST_KIND:
        raise FieldCommonCoreSyncAcceptanceError("sync acceptance request identity is invalid")

    universal = request["universalSource"]
    if set(universal) != {"branch", "commit", "commonCoreHash"}:
        raise FieldCommonCoreSyncAcceptanceError("universal source binding drifted")
    if universal["branch"] != UNIVERSAL_BRANCH:
        raise FieldCommonCoreSyncAcceptanceError("universal source must be codex/software")
    _require_commit(universal["commit"], "universalSource.commit")
    _require_sha256(universal["commonCoreHash"], "universalSource.commonCoreHash")

    field = request["fieldSource"]
    if set(field) != {"branch", "commit", "driftAuditSha256"}:
        raise FieldCommonCoreSyncAcceptanceError("field source binding drifted")
    if field["branch"] != FIELD_BRANCH:
        raise FieldCommonCoreSyncAcceptanceError("field source must be codex/software-field")
    _require_commit(field["commit"], "fieldSource.commit")
    _require_sha256(field["driftAuditSha256"], "fieldSource.driftAuditSha256")

    field_hashes = field_path_hashes(repo_root)
    groups = _path_map(request["backflowGroups"], "backflowGroups")
    if set(groups) != set(BACKFLOW_GROUPS):
        raise FieldCommonCoreSyncAcceptanceError("backflow group set drifted")
    for group_id, expected_paths in BACKFLOW_GROUPS.items():
        group = groups[group_id]
        if set(group) != {"path", "universalStatus", "pathObservations"}:
            raise FieldCommonCoreSyncAcceptanceError(f"{group_id} fields drifted")
        if group["universalStatus"] != "present":
            raise FieldCommonCoreSyncAcceptanceError(f"{group_id} is not present in Universal")
        observations = _path_map(group["pathObservations"], f"{group_id}.pathObservations")
        if tuple(sorted(observations)) != tuple(sorted(expected_paths)):
            raise FieldCommonCoreSyncAcceptanceError(f"{group_id} path set drifted")
        for path, observation in observations.items():
            if set(observation) != {"path", "fieldSha256", "universalSha256", "universalStatus"}:
                raise FieldCommonCoreSyncAcceptanceError(f"{group_id}.{path} fields drifted")
            if observation["universalStatus"] != "present":
                raise FieldCommonCoreSyncAcceptanceError(f"{path} is missing from Universal")
            if observation["fieldSha256"] != field_hashes[path]:
                raise FieldCommonCoreSyncAcceptanceError(f"{path} Field hash drifted")
            if observation["universalSha256"] != observation["fieldSha256"]:
                raise FieldCommonCoreSyncAcceptanceError(f"{path} Universal hash does not match Field")

    isolation = _path_map(request["fieldSpecificIsolation"], "fieldSpecificIsolation")
    if tuple(sorted(isolation)) != tuple(sorted(FIELD_SPECIFIC_PATHS)):
        raise FieldCommonCoreSyncAcceptanceError("Field-specific isolation path set drifted")
    for path, observation in isolation.items():
        if set(observation) != {"path", "fieldSha256", "universalStatus"}:
            raise FieldCommonCoreSyncAcceptanceError(f"{path} isolation fields drifted")
        if observation["fieldSha256"] != field_hashes[path]:
            raise FieldCommonCoreSyncAcceptanceError(f"{path} Field-specific hash drifted")
        if observation["universalStatus"] != "absent":
            raise FieldCommonCoreSyncAcceptanceError(f"{path} leaked into Universal")

    protected_base = protected_evidence_base_hashes(repo_root=repo_root)
    protected = _path_map(request["protectedEvidence"], "protectedEvidence")
    if tuple(sorted(protected)) != tuple(sorted(PROTECTED_EVIDENCE_PATHS)):
        raise FieldCommonCoreSyncAcceptanceError("protected evidence path set drifted")
    for path, observation in protected.items():
        if set(observation) != {"path", "baseSha256", "universalSha256", "universalStatus"}:
            raise FieldCommonCoreSyncAcceptanceError(f"{path} protected evidence fields drifted")
        if observation["universalStatus"] != "present":
            raise FieldCommonCoreSyncAcceptanceError(f"{path} was deleted from Universal")
        if observation["baseSha256"] != protected_base[path]:
            raise FieldCommonCoreSyncAcceptanceError(f"{path} base evidence hash drifted")
        if observation["universalSha256"] != observation["baseSha256"]:
            raise FieldCommonCoreSyncAcceptanceError(f"{path} was tampered in Universal")

    gates = request["safetyGates"]
    expected_gates = {
        "validatedHardwarePackCount": 0,
        "threeLayerQuorum": "missing",
        "buildAllowed": False,
        "installAllowed": False,
        "deviceEnumerationAllowed": False,
        "hardwareActionsAllowed": False,
    }
    if gates != expected_gates:
        raise FieldCommonCoreSyncAcceptanceError("Field safety gates must remain fail-closed")
    return request


def evaluate_sync_acceptance(request: dict[str, Any], *, repo_root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    try:
        validate_acceptance_request(request, repo_root=repo_root)
    except FieldCommonCoreSyncAcceptanceError as error:
        errors.append(str(error))

    accepted = not errors
    blockers = [
        "field.registry.zero-validated-packs",
        "field.quorum.missing-three-layer",
        "field.build.prohibited-until-hardware-validation",
    ]
    if not accepted:
        blockers.append("field.common-core-backflow.pending")
    receipt = {
        "schemaVersion": 1,
        "kind": RECEIPT_KIND,
        "editionId": "field",
        "source": {
            "fieldCommit": request.get("fieldSource", {}).get("commit"),
            "universalCommit": request.get("universalSource", {}).get("commit"),
            "universalCommonCoreHash": request.get("universalSource", {}).get("commonCoreHash"),
        },
        "acceptanceDecision": "accept" if accepted else "deny",
        "commonCoreBackflowPending": not accepted,
        "buildAllowed": False,
        "installAllowed": False,
        "deviceEnumerationAllowed": False,
        "hardwareActionsAllowed": False,
        "simulationAllowed": False,
        "validatedHardwarePackCount": 0,
        "threeLayerQuorum": "missing",
        "acceptedBackflowGroups": sorted(BACKFLOW_GROUPS) if accepted else [],
        "fieldSpecificPathsStillFieldOnly": sorted(FIELD_SPECIFIC_PATHS) if accepted else [],
        "protectedEvidencePathsPreserved": sorted(PROTECTED_EVIDENCE_PATHS) if accepted else [],
        "blockers": sorted(blockers),
        "errors": errors,
    }
    receipt["receiptSha256"] = sha256_canonical(
        {key: value for key, value in receipt.items() if key != "receiptSha256"}
    )
    return receipt
