from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"

AUDIT_KIND = "dronedream-field-common-drift-readiness-audit"
RECEIPT_KIND = "dronedream-field-preview-build-readiness-receipt"
DEFAULT_BASE_REF = "origin/codex/software"
FIELD_BRANCH = "codex/software-field"
FIELD_RELEASE_BRANCH = "codex/release-field"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

EDITION_BUILD_BACKFLOW_PATHS = {
    "distribution/build-plans/software-1.0.0-065382b68bfa.v1.json",
    "distribution/build-plans/software-1.0.0-065382b68bfa.v1.json.sha256",
    "distribution/schemas/edition-build-plan.schema.json",
    "distribution/tests/test_edition_build_planner.py",
    "distribution/tools/edition_build_planner.py",
}
ENGINE_PROFILE_BACKFLOW_PATHS = {
    "desktop/scripts/verify-updater-build-contract.ps1",
    "desktop/src-tauri/build.rs",
    "engine-pack/manifest.schema.json",
    "engine-pack/tests/test_engine_pack.py",
    "engine-pack/tests/test_engine_pack_manager.py",
    "engine-pack/tools/engine_pack.py",
    "runtime/scripts/edition-safety-gate.py",
}
FIELD_CONTRACT_PREFIXES = (
    "desktop/scripts/verify-field-",
    "desktop/src-tauri/tauri.field.",
    "distribution/editions/field/",
    "distribution/schemas/field-",
    "distribution/tests/test_field_",
    "distribution/tools/field_",
    "frontend/field.html",
    "frontend/src/__tests__/Field",
    "frontend/src/__tests__/field",
    "frontend/src/field/",
    "frontend/vite.field.",
)
FIELD_EDITION_PATHS = {
    "desktop/package.json",
    "distribution/editions/field.v1.json",
    "distribution/runtime-contract-registry.v1.json",
    "frontend/package.json",
}
PROTECTED_EVIDENCE_PREFIXES = ("artifacts/test-runs/",)
FIELD_BRANDING_MANIFEST = Path("distribution/editions/field/branding/source-manifest.v1.json")
FIELD_TAURI_CONFIG = Path("desktop/src-tauri/tauri.field.conf.json")
FIELD_FRONTEND_APP = Path("frontend/src/field/FieldApp.tsx")
FIELD_VITE_CONFIG = Path("frontend/vite.field.config.ts")
BASE_TAURI_CONFIG = Path("desktop/src-tauri/tauri.conf.json")
FIELD_SHORTCUT_PROPOSAL = Path(
    "distribution/editions/field/installer-shortcut-icon-common-core-proposal.v1.json"
)


class FieldDriftReadinessAuditError(ValueError):
    pass


def _run_git(repo_root: Path, *args: str, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode and not allow_failure:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git failed"
        raise FieldDriftReadinessAuditError(detail)
    return completed


def canonical_bytes(document: object) -> bytes:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_canonical(document: object) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise FieldDriftReadinessAuditError(f"expected JSON object: {path}")
    return document


def current_head(repo_root: Path) -> str:
    head = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
    if COMMIT_RE.fullmatch(head) is None:
        raise FieldDriftReadinessAuditError("HEAD is not a full Git commit")
    return head


def current_branch(repo_root: Path) -> str:
    return _run_git(repo_root, "branch", "--show-current").stdout.strip()


def source_tree_clean(repo_root: Path) -> bool:
    status = _run_git(repo_root, "status", "--porcelain", "--untracked-files=all").stdout
    return not status.strip()


def commit_list(repo_root: Path, base_ref: str, head_ref: str = "HEAD") -> list[dict[str, str]]:
    output = _run_git(repo_root, "log", "--reverse", "--format=%H%x09%s", f"{base_ref}..{head_ref}").stdout
    commits = []
    for line in output.splitlines():
        commit, subject = line.split("\t", 1)
        commits.append({"commit": commit, "subject": subject})
    return commits


def commit_changed_paths(repo_root: Path, commit: str) -> list[dict[str, str]]:
    output = _run_git(repo_root, "diff-tree", "--no-commit-id", "--name-status", "-r", commit).stdout
    paths = []
    for line in output.splitlines():
        status, path = line.split("\t", 1)
        paths.append({"status": status, "path": path})
    return paths


def changed_paths(repo_root: Path, base_ref: str, head_ref: str = "HEAD") -> list[dict[str, str]]:
    output = _run_git(repo_root, "diff", "--name-status", f"{base_ref}..{head_ref}").stdout
    paths = []
    for line in output.splitlines():
        status, path = line.split("\t", 1)
        paths.append({"status": status, "path": path})
    return paths


def classify_path(path: str) -> dict[str, str]:
    if path in EDITION_BUILD_BACKFLOW_PATHS:
        return {
            "classification": "universal-common-core-backflow",
            "topic": "edition-build-common-core-binding",
            "action": "forward-port-to-codex/software",
        }
    if path in ENGINE_PROFILE_BACKFLOW_PATHS:
        return {
            "classification": "universal-common-core-backflow",
            "topic": "engine-pack-edition-profile-and-runtime-whitelist",
            "action": "extract-minimal-shared-core-patch",
        }
    if path in FIELD_EDITION_PATHS or path.startswith(FIELD_CONTRACT_PREFIXES):
        return {
            "classification": "field-specific-contract",
            "topic": "field-edition-contract-and-product-surface",
            "action": "keep-on-field-through-universal-contract-registry-hook",
        }
    if path.startswith(PROTECTED_EVIDENCE_PREFIXES):
        return {
            "classification": "protected-evidence-drift",
            "topic": "historical-sim-preview-artifact-records",
            "action": "do-not-backflow-delete-coordinate-evidence-owner",
        }
    return {
        "classification": "unclassified-review-required",
        "topic": "manual-review",
        "action": "do-not-backflow-without-owner-review",
    }


def release_branch_state(repo_root: Path) -> dict[str, bool]:
    local = (
        _run_git(
            repo_root,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{FIELD_RELEASE_BRANCH}",
            allow_failure=True,
        ).returncode
        == 0
    )
    remote = (
        _run_git(
            repo_root,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/remotes/origin/{FIELD_RELEASE_BRANCH}",
            allow_failure=True,
        ).returncode
        == 0
    )
    return {"localPresent": local, "originPresent": remote}


def registry_summary(repo_root: Path) -> dict[str, Any]:
    registry = load_json(repo_root / "distribution" / "vehicle-packs" / "registry.v1.json")
    validated = [
        pack
        for pack in registry["packs"]
        if pack["currentValidationStatus"] == "validated"
        and pack["currentValidationTier"] == "hardware-validated"
    ]
    return {
        "path": "distribution/vehicle-packs/registry.v1.json",
        "sha256": sha256_file(repo_root / "distribution" / "vehicle-packs" / "registry.v1.json"),
        "packCount": len(registry["packs"]),
        "validatedHardwarePackCount": len(validated),
        "validatedHardwarePackIds": [pack["packId"] for pack in validated],
    }


def field_desktop_preview_structure(repo_root: Path) -> dict[str, Any]:
    manifest_path = repo_root / FIELD_BRANDING_MANIFEST
    manifest = load_json(manifest_path)
    tauri = load_json(repo_root / FIELD_TAURI_CONFIG)
    base_tauri = load_json(repo_root / BASE_TAURI_CONFIG)
    edition = load_json(repo_root / "distribution" / "editions" / "field.v1.json")
    app_source = (repo_root / FIELD_FRONTEND_APP).read_text(encoding="utf-8")
    vite_source = (repo_root / FIELD_VITE_CONFIG).read_text(encoding="utf-8")
    proposal_path = repo_root / FIELD_SHORTCUT_PROPOSAL
    proposal = load_json(proposal_path)
    hook_relative = base_tauri["bundle"]["windows"]["nsis"]["installerHooks"]
    hook_path = repo_root / "desktop" / "src-tauri" / hook_relative
    hook_source = hook_path.read_text(encoding="utf-8")

    verification_errors: list[str] = []
    assets = []
    for asset in manifest.get("assets", []):
        target_path = Path(asset["targetPath"])
        target = repo_root / target_path
        actual_sha256 = sha256_file(target) if target.is_file() else ""
        hash_matches_source = (
            actual_sha256 == asset.get("sourceSha256") == asset.get("targetSha256")
        )
        size_matches = target.is_file() and target.stat().st_size == asset.get("sizeBytes")
        transformations_empty = asset.get("transformations") == []
        if not hash_matches_source:
            verification_errors.append(f"field.branding.hash-drift:{target_path.as_posix()}")
        if not size_matches:
            verification_errors.append(f"field.branding.size-drift:{target_path.as_posix()}")
        if not transformations_empty:
            verification_errors.append(
                f"field.branding.transformation-declared:{target_path.as_posix()}"
            )
        assets.append(
            {
                "assetId": asset["assetId"],
                "path": target_path.as_posix(),
                "sha256": actual_sha256,
                "sizeBytes": target.stat().st_size if target.is_file() else 0,
                "hashMatchesSource": hash_matches_source,
                "transformationsEmpty": transformations_empty,
            }
        )

    expected_mark = "../../distribution/editions/field/branding/dronedream-field-mark.png"
    expected_lockup = (
        "../../distribution/editions/field/branding/dronedream-field-dot-lockup.png"
    )
    expected_manifest = (
        "../../distribution/editions/field/branding/source-manifest.v1.json"
    )
    bundle = tauri.get("bundle", {})
    resources = bundle.get("resources", {})
    endpoint = tauri.get("plugins", {}).get("updater", {}).get("endpoints", [""])[0]
    consumer_checks = {
        "displayName": tauri.get("productName") == manifest.get("displayName"),
        "windowTitle": tauri.get("app", {}).get("windows", [{}])[0].get("title")
        == manifest.get("displayName"),
        "frontendDotLockup": 'src="/dronedream-field-dot-lockup.png"' in app_source,
        "frontendBrandingRoot": "../distribution/editions/field/branding" in vite_source,
        "tauriIcon": bundle.get("icon") == [expected_mark],
        "tauriResources": resources
        == {
            expected_mark: "branding/dronedream-field-mark.png",
            expected_lockup: "branding/dronedream-field-dot-lockup.png",
            expected_manifest: "branding/source-manifest.v1.json",
        },
        "fieldFrontendDist": tauri.get("build", {}).get("frontendDist")
        == "../../frontend/field-dist",
        "fieldUpdaterManifest": endpoint.endswith("/field-latest.json"),
        "fieldArtifactBaseName": edition.get("artifactBaseName")
        == "DroneDream-Field-1.0.0.exe",
        "authorityRemainsFalse": 'data-authority="false"' in app_source,
        "installerShortcutFieldIcon": "$INSTDIR\\icons\\DroneDream.ico"
        not in hook_source,
    }
    for check, passed in consumer_checks.items():
        if not passed:
            verification_errors.append(f"field.desktop-consumer.invalid:{check}")

    scanned_structure = json.dumps(
        {
            "build": tauri.get("build", {}),
            "bundleIcon": bundle.get("icon", []),
            "bundleResources": resources,
            "updaterEndpoints": tauri.get("plugins", {}).get("updater", {}).get(
                "endpoints", []
            ),
        },
        sort_keys=True,
    ).lower()
    simulator_references = sorted(
        token for token in ("gazebo", "hitl", "sitl", "simulator") if token in scanned_structure
    )
    if simulator_references:
        verification_errors.append("field.desktop-structure.simulator-reference")

    return {
        "artifactBaseName": edition["artifactBaseName"],
        "frontendDist": tauri["build"]["frontendDist"],
        "updaterManifestFilename": "field-latest.json",
        "brandManifestPath": FIELD_BRANDING_MANIFEST.as_posix(),
        "brandManifestSha256": sha256_file(manifest_path),
        "brandCommonCoreCommit": manifest["commonCoreCommit"],
        "brandCopyPolicy": manifest["copyPolicy"],
        "installerShortcutHook": {
            "path": hook_path.relative_to(repo_root).as_posix(),
            "sha256": sha256_file(hook_path),
            "fieldIconBound": consumer_checks["installerShortcutFieldIcon"],
            "commonCoreProposalPath": FIELD_SHORTCUT_PROPOSAL.as_posix(),
            "commonCoreProposalSha256": sha256_file(proposal_path),
            "proposalStatus": proposal["status"],
        },
        "assets": assets,
        "consumerChecks": consumer_checks,
        "simulatorReferences": simulator_references,
        "verificationErrors": verification_errors,
        "verified": not verification_errors,
    }


def common_core_drift_audit(
    *,
    repo_root: Path = ROOT,
    base_ref: str = DEFAULT_BASE_REF,
    head_ref: str = "HEAD",
) -> dict[str, Any]:
    commits = commit_list(repo_root, base_ref, head_ref)
    commit_details = []
    for commit in commits:
        paths = commit_changed_paths(repo_root, commit["commit"])
        commit_details.append(
            {
                **commit,
                "changedPaths": [
                    {
                        **path_record,
                        **classify_path(path_record["path"]),
                    }
                    for path_record in paths
                ],
            }
        )
    all_paths = [
        {**path_record, **classify_path(path_record["path"])}
        for path_record in changed_paths(repo_root, base_ref, head_ref)
    ]
    common_paths = [
        item for item in all_paths if item["classification"] == "universal-common-core-backflow"
    ]
    field_paths = [item for item in all_paths if item["classification"] == "field-specific-contract"]
    protected_paths = [item for item in all_paths if item["classification"] == "protected-evidence-drift"]
    audit = {
        "schemaVersion": 1,
        "kind": AUDIT_KIND,
        "source": {
            "baseRef": base_ref,
            "headRef": head_ref,
            "headCommit": current_head(repo_root) if head_ref == "HEAD" else head_ref,
            "branch": current_branch(repo_root),
            "treeClean": source_tree_clean(repo_root),
        },
        "commits": commit_details,
        "changedPaths": all_paths,
        "summary": {
            "commitCount": len(commits),
            "changedPathCount": len(all_paths),
            "universalCommonCorePathCount": len(common_paths),
            "fieldSpecificPathCount": len(field_paths),
            "protectedEvidenceDriftCount": len(protected_paths),
        },
        "dependencies": [
            {
                "dependencyId": "common-core-source-binding",
                "dependsOnPaths": sorted(EDITION_BUILD_BACKFLOW_PATHS),
                "mustBackflowBefore": ["field-preview-build-receipt", "release-promotion"],
            },
            {
                "dependencyId": "engine-pack-edition-profile",
                "dependsOnPaths": sorted(ENGINE_PROFILE_BACKFLOW_PATHS),
                "mustBackflowBefore": ["field-engine-pack-production-build"],
            },
            {
                "dependencyId": "field-contracts",
                "dependsOnPaths": sorted(
                    item["path"] for item in field_paths if item["status"] != "D"
                ),
                "mustStayFieldSpecificUntil": "Universal defines a generic edition contract registry hook",
            },
        ],
        "minimumForwardBackflowPlan": [
            {
                "planId": "universal-core-common-core-commit-binding",
                "sourceCommits": [
                    commit["commit"]
                    for commit in commits
                    if commit["subject"] == "test(field): bind build plans to common core commit"
                ],
                "paths": sorted(EDITION_BUILD_BACKFLOW_PATHS),
                "method": "replay-or-reimplement-as-minimal-patch-on-codex/software",
                "excludePaths": [],
            },
            {
                "planId": "universal-core-engine-pack-edition-profile",
                "sourceCommits": [
                    commit["commit"]
                    for commit in commits
                    if commit["subject"] == "feat(field): add lightweight engine pack profile"
                ],
                "paths": sorted(ENGINE_PROFILE_BACKFLOW_PATHS),
                "method": "extract generic edition-profile build plumbing and Field profile filter",
                "excludePaths": sorted(path["path"] for path in field_paths),
            },
            {
                "planId": "universal-core-field-contract-retention-hook",
                "sourceCommits": [
                    commit["commit"]
                    for commit in commits
                    if commit["subject"]
                    in {
                        "test(field): add prerelease audit contract",
                        "test(field): add lifecycle refusal contract",
                    }
                ],
                "paths": [
                    "engine-pack/tools/engine_pack.py",
                    "runtime/scripts/edition-safety-gate.py",
                ],
                "method": "port only whitelist/contract-retention hook; keep Field contract implementations on Field",
                "excludePaths": sorted(path["path"] for path in field_paths),
            },
        ],
        "protectedEvidencePlan": {
            "paths": protected_paths,
            "backflowAction": "none",
            "reason": "historical artifact evidence deletions must not be normalized through Universal without evidence-owner coordination",
        },
    }
    audit["auditSha256"] = sha256_canonical({k: v for k, v in audit.items() if k != "auditSha256"})
    return audit


def field_preview_readiness_receipt(
    *,
    repo_root: Path = ROOT,
    base_ref: str = DEFAULT_BASE_REF,
) -> dict[str, Any]:
    drift = common_core_drift_audit(repo_root=repo_root, base_ref=base_ref)
    registry = registry_summary(repo_root)
    release_branch = release_branch_state(repo_root)
    desktop_structure = field_desktop_preview_structure(repo_root)
    blockers = [
        "field.preview-build.disabled-by-request",
        "field.exe-build.prohibited-in-this-audit",
        "field.install.prohibited-in-this-audit",
        "field.hardware-device-action.prohibited-in-this-audit",
        "field.simulation.prohibited-in-this-audit",
        "field.registry.zero-validated-packs",
        "field.quorum.missing-three-layer",
    ]
    if drift["summary"]["universalCommonCorePathCount"]:
        blockers.append("field.common-core-backflow.pending")
    if not drift["source"]["treeClean"]:
        blockers.append("field.source-tree.not-clean")
    if release_branch["localPresent"] or release_branch["originPresent"]:
        blockers.append("field.release-branch.present")
    if not desktop_structure["verified"]:
        blockers.append("field.desktop-preview-structure.invalid")
    if not desktop_structure["consumerChecks"]["installerShortcutFieldIcon"]:
        blockers.append("field.installer-shortcut-icon.common-core-hook-pending")
    receipt = {
        "schemaVersion": 1,
        "kind": RECEIPT_KIND,
        "editionId": "field",
        "source": {
            "branch": drift["source"]["branch"],
            "headCommit": drift["source"]["headCommit"],
            "baseRef": base_ref,
            "driftAuditSha256": drift["auditSha256"],
        },
        "decision": "deny",
        "buildAllowed": False,
        "installAllowed": False,
        "releaseBranchAllowed": False,
        "hardwareActionsAllowed": False,
        "deviceEnumerationAllowed": False,
        "simulationAllowed": False,
        "registry": registry,
        "desktopPreviewStructure": desktop_structure,
        "releaseBranch": release_branch,
        "prohibitedOperations": [
            "build DroneDream-Field-1.0.0.exe",
            "install DroneDream-Field-1.0.0.exe",
            "create codex/release-field",
            "open USB or serial devices",
            "write parameters",
            "unlock, arm, or fly hardware",
            "start PX4, Gazebo, SITL, or HITL",
            "read OPENAI_API_KEY or provider credentials",
        ],
        "blockers": sorted(set(blockers)),
    }
    receipt["receiptSha256"] = sha256_canonical(
        {k: v for k, v in receipt.items() if k != "receiptSha256"}
    )
    return receipt


def validate_common_core_drift_audit(document: dict[str, Any]) -> dict[str, Any]:
    if document.get("schemaVersion") != 1 or document.get("kind") != AUDIT_KIND:
        raise FieldDriftReadinessAuditError("common-core drift audit identity is invalid")
    if not document["source"]["branch"]:
        raise FieldDriftReadinessAuditError("common-core drift audit branch is missing")
    if COMMIT_RE.fullmatch(document["source"]["headCommit"]) is None:
        raise FieldDriftReadinessAuditError("common-core drift audit head commit is invalid")
    if not document["minimumForwardBackflowPlan"]:
        raise FieldDriftReadinessAuditError("common-core drift audit lacks a backflow plan")
    field_paths = [
        item["path"]
        for item in document["changedPaths"]
        if item["classification"] == "field-specific-contract"
    ]
    for plan in document["minimumForwardBackflowPlan"]:
        if any(path in plan["paths"] for path in field_paths):
            raise FieldDriftReadinessAuditError("Field-specific contracts entered Universal backflow")
    if SHA256_RE.fullmatch(document["auditSha256"]) is None:
        raise FieldDriftReadinessAuditError("common-core drift audit hash is invalid")
    return document


def validate_field_preview_readiness_receipt(document: dict[str, Any]) -> dict[str, Any]:
    if document.get("schemaVersion") != 1 or document.get("kind") != RECEIPT_KIND:
        raise FieldDriftReadinessAuditError("Field preview readiness receipt identity is invalid")
    if document["decision"] != "deny" or document["buildAllowed"]:
        raise FieldDriftReadinessAuditError("Field preview readiness must deny builds")
    for key in (
        "installAllowed",
        "releaseBranchAllowed",
        "hardwareActionsAllowed",
        "deviceEnumerationAllowed",
        "simulationAllowed",
    ):
        if document[key]:
            raise FieldDriftReadinessAuditError(f"Field preview readiness allowed {key}")
    if document["registry"]["validatedHardwarePackCount"] != 0:
        raise FieldDriftReadinessAuditError("Field preview readiness overstated validated packs")
    expected_receipt_hash = sha256_canonical(
        {key: value for key, value in document.items() if key != "receiptSha256"}
    )
    if document["receiptSha256"] != expected_receipt_hash:
        raise FieldDriftReadinessAuditError("Field preview readiness receipt hash drifted")
    structure = document["desktopPreviewStructure"]
    expected_verified = (
        not structure["verificationErrors"]
        and not structure["simulatorReferences"]
        and all(structure["consumerChecks"].values())
    )
    if structure["verified"] != expected_verified:
        raise FieldDriftReadinessAuditError("Field desktop preview verification state drifted")
    if not structure["verified"] and "field.desktop-preview-structure.invalid" not in document["blockers"]:
        raise FieldDriftReadinessAuditError("Field desktop preview blocker is missing")
    if not structure["consumerChecks"]["installerShortcutFieldIcon"] and (
        "field.installer-shortcut-icon.common-core-hook-pending" not in document["blockers"]
    ):
        raise FieldDriftReadinessAuditError("Field shortcut icon blocker is missing")
    if len(structure["assets"]) != 2 or not all(
        asset["hashMatchesSource"] and asset["transformationsEmpty"]
        for asset in structure["assets"]
    ):
        raise FieldDriftReadinessAuditError("Field brand assets are not exact donor bytes")
    if "field.registry.zero-validated-packs" not in document["blockers"]:
        raise FieldDriftReadinessAuditError("Field preview readiness lost zero-pack blocker")
    if SHA256_RE.fullmatch(document["receiptSha256"]) is None:
        raise FieldDriftReadinessAuditError("Field preview readiness receipt hash is invalid")
    return document
