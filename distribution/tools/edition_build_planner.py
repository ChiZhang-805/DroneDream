#!/usr/bin/env python3
"""Create and validate plan-only SIM/LAB/FIELD/AGENT build inventories.

This tool never invokes Tauri, NSIS, an installer, Runtime migration, a release
API, or a release-branch mutation.  It derives a deterministic, source-bound
plan from reviewed edition and Vehicle Pack contracts and fails closed when
the source tree, common core, NOTICE closure, controller selection, or remote
long-lived product-branch observations drift.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import distribution_contract as contract

EDITION_IDS = ("autonomy", "field", "lab", "sim")
EDITION_BRANCHES = {edition_id: contract.EDITION_BRANCHES[edition_id] for edition_id in EDITION_IDS}
EDITION_LABELS = {
    "autonomy": "Agent",
    "field": "Field",
    "lab": "Lab",
    "sim": "Sim",
}
CORE_PATHS = ("backend", "desktop", "engine-pack", "frontend", "runtime", "worker")
COMPONENT_IDS = {
    "desktop-core",
    "engine-pack",
    "runtime-base-field-lightweight",
    "runtime-base-full-simulation",
}
RECEIPT_ONLY_PREFIX = "distribution/build-plans/"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*$")
ID_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")

REQUEST_KEYS = {
    "schemaVersion",
    "kind",
    "requestVersion",
    "productDisplayVersion",
    "targetArchitecture",
    "commonCorePaths",
    "policyPaths",
    "components",
    "editions",
    "precombinedBundles",
}
POLICY_PATH_KEYS = {
    "capabilityPolicy",
    "upstreamInventory",
    "vehiclePackRegistry",
    "licenseNotice",
}
COMPONENT_KEYS = {
    "componentId",
    "version",
    "sourcePolicy",
    "sourceCommit",
    "contractPath",
    "artifactState",
    "artifactManifestSha256",
    "artifactSha256",
    "artifactBytes",
    "signatureState",
    "planningDownloadBytes",
    "planningInstalledBytes",
}
EDITION_REQUEST_KEYS = {
    "editionId",
    "editionManifestPath",
    "componentIds",
    "vehiclePackManifestPath",
    "controllerModel",
    "region",
    "vehiclePackDownloadEstimateBytes",
    "vehiclePackInstalledEstimateBytes",
    "artifactFileName",
}
BUNDLE_REQUEST_KEYS = {
    "bundleId",
    "editionId",
    "vehiclePackId",
    "controllerModel",
    "region",
    "artifactFileName",
}
PLAN_KEYS = {
    "schemaVersion",
    "kind",
    "planVersion",
    "planId",
    "state",
    "blockers",
    "productDisplayVersion",
    "internalBuildId",
    "targetArchitecture",
    "source",
    "execution",
    "policyBindings",
    "components",
    "editions",
    "precombinedBundles",
    "licenseClosure",
}


class BuildPlanError(ValueError):
    """Raised when an E4 plan would overstate or drift from reviewed input."""


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BuildPlanError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise BuildPlanError(f"{label} keys drifted (missing={missing}, extra={extra})")
    return value


def _safe_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SAFE_PATH_RE.fullmatch(value):
        raise BuildPlanError(f"{label} is not a safe repository-relative path")
    return value


def _positive_or_zero(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BuildPlanError(f"{label} must be a non-negative integer")
    return value


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildPlanError(f"{label} could not be read: {path}") from exc
    if not isinstance(value, dict):
        raise BuildPlanError(f"{label} must be a JSON object")
    return value


def _resolve(root: Path, relative: Any, label: str) -> Path:
    safe = _safe_path(relative, label)
    candidate = (root / safe).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise BuildPlanError(f"{label} escapes the repository root") from exc
    if not candidate.is_file():
        raise BuildPlanError(f"{label} does not exist: {safe}")
    return candidate


def _file_ref(root: Path, relative: str) -> dict[str, Any]:
    path = _resolve(root, relative, "bound file")
    return {"path": relative, "sha256": contract.sha256_file(path)}


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
        raise BuildPlanError(detail)
    return completed.stdout


def current_source_state(repo_root: Path) -> tuple[str, bool]:
    head = _run_git(repo_root, "rev-parse", "HEAD").strip()
    if not COMMIT_RE.fullmatch(head):
        raise BuildPlanError("current Git HEAD is not a full commit")
    clean = not _run_git(repo_root, "status", "--porcelain", "--untracked-files=all").strip()
    return head, clean


def common_core_hash(repo_root: Path, source_commit: str, paths: list[str]) -> str:
    if not COMMIT_RE.fullmatch(source_commit):
        raise BuildPlanError("source commit is invalid")
    if tuple(paths) != CORE_PATHS:
        raise BuildPlanError("common-core path set drifted")
    _run_git(repo_root, "cat-file", "-e", f"{source_commit}^{{commit}}")
    listing = _run_git(
        repo_root,
        "ls-tree",
        "-r",
        "--full-tree",
        source_commit,
        "--",
        *paths,
    )
    if not listing.strip():
        raise BuildPlanError("common-core inventory is empty")
    return hashlib.sha256(listing.encode("utf-8")).hexdigest()


def observe_release_heads(repo_root: Path, remote: str = "origin") -> dict[str, str | None]:
    refs = [f"refs/heads/{EDITION_BRANCHES[edition_id]}" for edition_id in EDITION_IDS]
    output = _run_git(repo_root, "ls-remote", "--heads", remote, *refs)
    observed: dict[str, str | None] = {edition_id: None for edition_id in EDITION_IDS}
    for raw_line in output.splitlines():
        fields = raw_line.split()
        if len(fields) != 2 or not COMMIT_RE.fullmatch(fields[0]):
            raise BuildPlanError("remote release-head observation is malformed")
        branch = fields[1].removeprefix("refs/heads/")
        branch_to_edition = {
            edition_branch: edition_id for edition_id, edition_branch in EDITION_BRANCHES.items()
        }
        if branch not in branch_to_edition:
            raise BuildPlanError("remote release-head observation returned an unexpected ref")
        edition_id = branch_to_edition[branch]
        if edition_id not in observed or observed[edition_id] is not None:
            raise BuildPlanError("remote release-head observation is duplicated or unknown")
        observed[edition_id] = fields[0]
    return observed


def validate_post_source_paths(
    repo_root: Path, *, source_commit: str, current_head: str
) -> list[str]:
    if current_head == source_commit:
        return []
    paths = [
        line.strip()
        for line in _run_git(
            repo_root, "diff", "--name-only", source_commit, current_head
        ).splitlines()
        if line.strip()
    ]
    if not paths or any(not path.startswith(RECEIPT_ONLY_PREFIX) for path in paths):
        raise BuildPlanError(
            "post-source HEAD contains changes outside the build-plan receipt allowlist"
        )
    return paths


def validate_request(request: Any) -> dict[str, Any]:
    document = _exact_keys(request, REQUEST_KEYS, "build request")
    if (
        document["schemaVersion"] != 1
        or document["kind"] != "dronedream-edition-build-request"
        or document["requestVersion"] != "1.0.0"
        or document["productDisplayVersion"] != "1.0.0"
        or document["targetArchitecture"] != "windows-x86_64"
    ):
        raise BuildPlanError("build request identity is unsupported")
    paths = document["commonCorePaths"]
    if not isinstance(paths, list) or tuple(paths) != CORE_PATHS:
        raise BuildPlanError("build request common-core paths drifted")
    policy_paths = _exact_keys(document["policyPaths"], POLICY_PATH_KEYS, "policy paths")
    for field, path in policy_paths.items():
        _safe_path(path, f"policyPaths.{field}")

    components = document["components"]
    if not isinstance(components, list) or len(components) != len(COMPONENT_IDS):
        raise BuildPlanError("build request must define the four reviewed components")
    component_ids: set[str] = set()
    for index, raw in enumerate(components):
        item = _exact_keys(raw, COMPONENT_KEYS, f"components[{index}]")
        component_id = item["componentId"]
        if component_id not in COMPONENT_IDS or component_id in component_ids:
            raise BuildPlanError("component id is unknown or duplicated")
        component_ids.add(component_id)
        if not isinstance(item["version"], str) or not item["version"]:
            raise BuildPlanError("component version is empty")
        _safe_path(item["contractPath"], "component contractPath")
        source_policy = item["sourcePolicy"]
        if source_policy == "common-source":
            if item["sourceCommit"] is not None:
                raise BuildPlanError("common-source component must derive sourceCommit")
        elif source_policy == "pinned-source":
            if not isinstance(item["sourceCommit"], str) or not COMMIT_RE.fullmatch(
                item["sourceCommit"]
            ):
                raise BuildPlanError("pinned component sourceCommit is invalid")
        else:
            raise BuildPlanError("component sourcePolicy is unsupported")
        state = item["artifactState"]
        artifact_fields = (
            item["artifactManifestSha256"],
            item["artifactSha256"],
            item["artifactBytes"],
        )
        if state == "planned-not-built":
            if artifact_fields != (None, None, None) or item["signatureState"] != "not-issued":
                raise BuildPlanError("unbuilt component cannot claim artifact bytes or signature")
        elif state == "verified-existing-reference":
            if (
                not all(
                    isinstance(value, str) and SHA256_RE.fullmatch(value)
                    for value in artifact_fields[:2]
                )
                or not isinstance(artifact_fields[2], int)
                or artifact_fields[2] <= 0
                or item["signatureState"] != "verified"
            ):
                raise BuildPlanError(
                    "existing component reference must bind verified artifact bytes"
                )
        else:
            raise BuildPlanError("component artifactState is unsupported")
        download = _positive_or_zero(item["planningDownloadBytes"], "component download")
        installed = _positive_or_zero(item["planningInstalledBytes"], "component installed")
        if installed < download:
            raise BuildPlanError("component installed estimate cannot be below download estimate")
        if isinstance(item["artifactBytes"], int) and download < item["artifactBytes"]:
            raise BuildPlanError("component download estimate cannot omit existing artifact bytes")
    if component_ids != COMPONENT_IDS:
        raise BuildPlanError("component set is incomplete")

    editions = document["editions"]
    if not isinstance(editions, list) or len(editions) != 4:
        raise BuildPlanError("build request must define exactly four product editions")
    edition_ids: set[str] = set()
    artifact_names: set[str] = set()
    for index, raw in enumerate(editions):
        item = _exact_keys(raw, EDITION_REQUEST_KEYS, f"editions[{index}]")
        edition_id = item["editionId"]
        if edition_id not in EDITION_IDS or edition_id in edition_ids:
            raise BuildPlanError("edition id is unknown or duplicated")
        edition_ids.add(edition_id)
        _safe_path(item["editionManifestPath"], "edition manifest path")
        _safe_path(item["vehiclePackManifestPath"], "Vehicle Pack manifest path")
        component_refs = item["componentIds"]
        if (
            not isinstance(component_refs, list)
            or len(component_refs) != 3
            or len(set(component_refs)) != 3
            or not set(component_refs) <= COMPONENT_IDS
            or "desktop-core" not in component_refs
            or "engine-pack" not in component_refs
        ):
            raise BuildPlanError("edition component set is unsupported")
        expected_runtime = (
            "runtime-base-field-lightweight"
            if edition_id == "field"
            else "runtime-base-full-simulation"
        )
        if expected_runtime not in component_refs:
            raise BuildPlanError("edition Runtime Base selection drifted")
        if item["region"] not in {"cn", "global"}:
            raise BuildPlanError("edition region is unsupported")
        _positive_or_zero(item["vehiclePackDownloadEstimateBytes"], "Vehicle Pack download")
        _positive_or_zero(item["vehiclePackInstalledEstimateBytes"], "Vehicle Pack installed")
        if item["vehiclePackInstalledEstimateBytes"] < item["vehiclePackDownloadEstimateBytes"]:
            raise BuildPlanError("Vehicle Pack installed estimate is too small")
        expected_name = f"DroneDream-{EDITION_LABELS[edition_id]}-1.0.0.exe"
        if item["artifactFileName"] != expected_name or expected_name in artifact_names:
            raise BuildPlanError("edition artifact filename drifted or duplicated")
        artifact_names.add(expected_name)
    if edition_ids != set(EDITION_IDS):
        raise BuildPlanError("edition set is incomplete")

    bundles = document["precombinedBundles"]
    if not isinstance(bundles, list) or not bundles:
        raise BuildPlanError("at least one precombined bundle is required")
    bundle_ids: set[str] = set()
    for index, raw in enumerate(bundles):
        item = _exact_keys(raw, BUNDLE_REQUEST_KEYS, f"precombinedBundles[{index}]")
        if not isinstance(item["bundleId"], str) or not ID_RE.fullmatch(item["bundleId"]):
            raise BuildPlanError("bundle id is invalid")
        if item["bundleId"] in bundle_ids:
            raise BuildPlanError("bundle id is duplicated")
        bundle_ids.add(item["bundleId"])
        if item["editionId"] not in EDITION_IDS or item["region"] not in {"cn", "global"}:
            raise BuildPlanError("bundle target is unsupported")
        name = item["artifactFileName"]
        if (
            not isinstance(name, str)
            or not name.startswith("DroneDream-")
            or not name.endswith("-1.0.0.exe")
        ):
            raise BuildPlanError("bundle artifact filename is invalid")
        if name in artifact_names:
            raise BuildPlanError("bundle artifact filename is duplicated")
        artifact_names.add(name)
    return document


def _load_contract_inputs(
    request: dict[str, Any], repo_root: Path
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, str],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    policy_path = _resolve(
        repo_root, request["policyPaths"]["capabilityPolicy"], "capability policy"
    )
    inventory_path = _resolve(
        repo_root, request["policyPaths"]["upstreamInventory"], "upstream inventory"
    )
    registry_path = _resolve(
        repo_root, request["policyPaths"]["vehiclePackRegistry"], "Vehicle Pack registry"
    )
    policy = contract.load_capability_policy(policy_path)
    policy_sha = contract.sha256_file(policy_path)
    editions: dict[str, dict[str, Any]] = {}
    edition_shas: dict[str, str] = {}
    for item in request["editions"]:
        path = _resolve(repo_root, item["editionManifestPath"], "edition manifest")
        edition = contract.validate_edition_manifest(
            _read_json(path, "edition manifest"), policy=policy, policy_sha256=policy_sha
        )
        if edition["editionId"] != item["editionId"]:
            raise BuildPlanError("edition request drifted from manifest identity")
        editions[edition["editionId"]] = edition
        edition_shas[edition["editionId"]] = contract.sha256_file(path)

    pack_dir = repo_root / "distribution" / "vehicle-packs"
    all_pack_paths = sorted(
        path for path in pack_dir.glob("*.v1.json") if not path.name.startswith("registry.")
    )
    registry = contract.load_vehicle_pack_registry(
        registry_path,
        vehicle_pack_paths=all_pack_paths,
        upstream_inventory_path=inventory_path,
        capability_policy_path=policy_path,
        repository_root=repo_root,
    )
    packs = contract.load_vehicle_pack_manifests(
        all_pack_paths,
        upstream_inventory_path=inventory_path,
        capability_policy_path=policy_path,
    )
    pack_shas: dict[str, str] = {}
    for path in all_pack_paths:
        pack_id = _read_json(path, "Vehicle Pack manifest")["packId"]
        pack_shas[pack_id] = contract.sha256_file(path)
    registry_ids = {item["packId"] for item in registry["packs"]}
    if registry_ids != set(packs):
        raise BuildPlanError("Vehicle Pack registry and manifests drifted")
    return editions, edition_shas, packs, pack_shas


def _component_plan(item: dict[str, Any], source_commit: str, repo_root: Path) -> dict[str, Any]:
    resolved_source = (
        source_commit if item["sourcePolicy"] == "common-source" else item["sourceCommit"]
    )
    suffix = "plan1" if item["sourcePolicy"] == "common-source" else "reference"
    return {
        "componentId": item["componentId"],
        "version": item["version"],
        "buildId": f"{item['componentId']}-{item['version']}-{resolved_source[:12]}-{suffix}",
        "sourceCommit": resolved_source,
        "contract": _file_ref(repo_root, item["contractPath"]),
        "artifactState": item["artifactState"],
        "artifactManifestSha256": item["artifactManifestSha256"],
        "artifactSha256": item["artifactSha256"],
        "artifactBytes": item["artifactBytes"],
        "signatureState": item["signatureState"],
        "planningDownloadBytes": item["planningDownloadBytes"],
        "planningInstalledBytes": item["planningInstalledBytes"],
    }


def _artifact_plan(file_name: str, build_id: str) -> dict[str, Any]:
    return {
        "fileName": file_name,
        "buildId": build_id,
        "state": "planned-not-built",
        "sha256": None,
        "bytes": None,
        "packaging": "tauri-nsis-planned",
    }


def create_build_plan(
    request: Any,
    *,
    repo_root: Path,
    source_commit: str,
    source_tree_clean: bool,
    observed_common_core_hash: str,
    observed_release_heads: dict[str, str | None],
) -> dict[str, Any]:
    request = validate_request(request)
    if not COMMIT_RE.fullmatch(source_commit):
        raise BuildPlanError("observed source commit is invalid")
    if not source_tree_clean:
        raise BuildPlanError("build planning requires a clean source tree")
    if not SHA256_RE.fullmatch(observed_common_core_hash):
        raise BuildPlanError("observed common-core hash is invalid")
    if set(observed_release_heads) != set(EDITION_IDS):
        raise BuildPlanError("release-head observations are incomplete")
    missing = {key for key, value in observed_release_heads.items() if value is None}
    malformed = {
        key
        for key, value in observed_release_heads.items()
        if value is not None and not COMMIT_RE.fullmatch(value)
    }
    if missing or malformed:
        raise BuildPlanError(
            "long-lived product branches are incomplete or malformed: "
            f"missing={sorted(missing)} malformed={sorted(malformed)}"
        )

    editions, edition_shas, packs, pack_shas = _load_contract_inputs(request, repo_root)
    short_source = source_commit[:12]
    components = [_component_plan(item, source_commit, repo_root) for item in request["components"]]
    components_by_id = {item["componentId"]: item for item in components}
    edition_plans: list[dict[str, Any]] = []
    all_license_ids: set[str] = set()

    for selection in sorted(request["editions"], key=lambda item: item["editionId"]):
        edition_id = selection["editionId"]
        edition = editions[edition_id]
        pack_path = _resolve(
            repo_root, selection["vehiclePackManifestPath"], "selected Vehicle Pack"
        )
        pack_id = _read_json(pack_path, "selected Vehicle Pack")["packId"]
        pack = packs[pack_id]
        if (
            edition_id not in pack["supportedEditions"]
            or selection["region"] not in pack["availabilityRegions"]
        ):
            raise BuildPlanError("Vehicle Pack is incompatible with edition or region")
        controller = selection["controllerModel"]
        controller_models = {item["model"] for item in pack["controllers"]}
        if controller is None:
            if controller_models:
                raise BuildPlanError("hardware Vehicle Pack requires an explicit controller")
        elif controller not in controller_models:
            raise BuildPlanError("selected controller is absent from the Vehicle Pack")
        if pack_id == "px4-gazebo-x500-reference" and controller is not None:
            raise BuildPlanError("simulation reference cannot bind a hardware controller")

        component_ids = selection["componentIds"]
        download_bytes = selection["vehiclePackDownloadEstimateBytes"] + sum(
            components_by_id[component_id]["planningDownloadBytes"]
            for component_id in component_ids
        )
        installed_bytes = selection["vehiclePackInstalledEstimateBytes"] + sum(
            components_by_id[component_id]["planningInstalledBytes"]
            for component_id in component_ids
        )
        license_ids = sorted(item["id"] for item in pack["licenses"])
        all_license_ids.update(license_ids)
        edition_build_id = f"{edition_id}-1.0.0-{short_source}-plan1"
        branch = edition["releaseChannel"]["branch"]
        blockers = [
            "The edition installer has not been built or validated.",
            "The selected Vehicle Pack is not validated and signed for this edition.",
            "The artifact-specific binary license and NOTICE closure has not been generated.",
        ]
        if edition_id in {"lab", "field"}:
            blockers.append("Physical-flight capability remains contract-only and unauthorized.")
        edition_plans.append(
            {
                "editionId": edition_id,
                "editionManifest": {
                    "path": selection["editionManifestPath"],
                    "sha256": edition_shas[edition_id],
                },
                "commonCoreCommit": source_commit,
                "commonCoreHash": observed_common_core_hash,
                "componentIds": component_ids,
                "vehiclePack": {
                    "packId": pack_id,
                    "packVersion": pack["packVersion"],
                    "manifest": {
                        "path": selection["vehiclePackManifestPath"],
                        "sha256": pack_shas[pack_id],
                    },
                    "payloadSha256": pack["integrity"]["payloadSha256"],
                    "validationStatus": pack["validationStatus"],
                    "validationTier": pack["validationTier"],
                    "controllerModel": controller,
                    "region": selection["region"],
                },
                "selectedModules": edition["modules"]["required"],
                "capabilities": edition["capabilities"]["enabledOrConditioned"],
                "artifact": _artifact_plan(selection["artifactFileName"], edition_build_id),
                "resourceEstimate": {
                    "basis": "planning-upper-bound-v1",
                    "downloadBytes": download_bytes,
                    "installedBytes": installed_bytes,
                    "requiresWsl": edition_id != "field",
                    "requiresGazebo": edition["runtimeProfile"]["includesLargeSimulator"],
                },
                "licenseIds": license_ids,
                "promotion": {
                    "targetBranch": branch,
                    "creationState": "long-lived-product-branch",
                    "observedBranchHead": observed_release_heads[edition_id],
                    "sourceCommit": source_commit,
                    "commonCoreCommit": source_commit,
                    "commonCoreHash": observed_common_core_hash,
                    "promotionManifestState": "planned-not-generated",
                    "prOnly": True,
                    "forcePushAllowed": False,
                    "supersedes": [],
                    "rollback": {
                        "policy": "previous-verified-promotion",
                        "targetPromotionId": None,
                        "targetArtifactSha256": None,
                    },
                },
                "blockers": blockers,
            }
        )

    editions_by_id = {item["editionId"]: item for item in edition_plans}
    bundles: list[dict[str, Any]] = []
    for item in request["precombinedBundles"]:
        edition = editions_by_id[item["editionId"]]
        vehicle = edition["vehiclePack"]
        if (
            vehicle["packId"] != item["vehiclePackId"]
            or vehicle["controllerModel"] != item["controllerModel"]
            or vehicle["region"] != item["region"]
        ):
            raise BuildPlanError("precombined bundle drifted from its edition plan")
        build_id = f"{item['bundleId']}-1.0.0-{short_source}-plan1"
        bundles.append(
            {
                "bundleId": item["bundleId"],
                "editionId": item["editionId"],
                "editionBuildId": edition["artifact"]["buildId"],
                "vehiclePackId": item["vehiclePackId"],
                "controllerModel": item["controllerModel"],
                "region": item["region"],
                "artifact": _artifact_plan(item["artifactFileName"], build_id),
                "resourceEstimate": edition["resourceEstimate"],
                "state": "plan-only",
            }
        )

    policy_paths = request["policyPaths"]
    notice_path = _resolve(repo_root, policy_paths["licenseNotice"], "license notice")
    notice_ref = _file_ref(repo_root, policy_paths["licenseNotice"])
    notice_ref["bytes"] = notice_path.stat().st_size
    upstream_ref = _file_ref(repo_root, policy_paths["upstreamInventory"])
    return {
        "schemaVersion": 1,
        "kind": "dronedream-unified-edition-build-plan",
        "planVersion": "1.0.0",
        "planId": f"software-1.0.0-{short_source}",
        "state": "plan-only",
        "blockers": [
            "No edition installer or precombined bundle has been built by this plan.",
            "All eight Vehicle Packs remain contract-only or planned; zero are validated.",
            "Each edition update must be forward-integrated through its long-lived "
            "product branch and reviewed pull request.",
            "Artifact-specific license, NOTICE, signature, and rollback evidence is pending.",
        ],
        "productDisplayVersion": "1.0.0",
        "internalBuildId": f"software-1.0.0-{short_source}-plan1",
        "targetArchitecture": request["targetArchitecture"],
        "source": {
            "commit": source_commit,
            "treeState": "clean",
            "commonCorePaths": request["commonCorePaths"],
            "commonCoreCommit": source_commit,
            "commonCoreHash": observed_common_core_hash,
        },
        "execution": {
            "canBuildInstaller": False,
            "canBundleModules": False,
            "canCreateReleaseBranch": False,
            "canPromote": False,
            "canInstall": False,
            "canMigrateRuntime": False,
        },
        "policyBindings": {
            "capabilityPolicy": _file_ref(repo_root, policy_paths["capabilityPolicy"]),
            "upstreamInventory": upstream_ref,
            "vehiclePackRegistry": _file_ref(repo_root, policy_paths["vehiclePackRegistry"]),
        },
        "components": components,
        "editions": edition_plans,
        "precombinedBundles": bundles,
        "licenseClosure": {
            "state": "plan-only-incomplete-artifact-closure",
            "notice": notice_ref,
            "upstreamInventory": upstream_ref,
            "licenseIds": sorted(all_license_ids),
            "blockers": [
                "The existing Runtime NOTICE is bound for planning only.",
                "Each future installer must regenerate and verify its exact "
                "binary-package closure.",
                "No third-party payload is newly copied or distributed by this plan.",
            ],
        },
    }


def validate_build_plan(
    document: Any,
    request: Any,
    *,
    repo_root: Path,
    observed_source_commit: str,
    source_tree_clean: bool,
    observed_common_core_hash: str,
    observed_release_heads: dict[str, str | None],
) -> dict[str, Any]:
    plan = _exact_keys(document, PLAN_KEYS, "build plan")
    source = plan.get("source")
    if not isinstance(source, dict) or not COMMIT_RE.fullmatch(str(source.get("commit", ""))):
        raise BuildPlanError("build plan source commit is invalid")
    if source["commit"] != observed_source_commit:
        raise BuildPlanError("build plan source drifted from independently observed source")
    expected = create_build_plan(
        request,
        repo_root=repo_root,
        source_commit=source["commit"],
        source_tree_clean=source_tree_clean,
        observed_common_core_hash=observed_common_core_hash,
        observed_release_heads=observed_release_heads,
    )
    for key in sorted(PLAN_KEYS):
        if plan[key] != expected[key]:
            raise BuildPlanError(f"build plan {key} drifted from the deterministic planner")
    return plan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--validate", type=Path)
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    repo_root = args.repository.resolve()
    try:
        request = _read_json(args.request.resolve(), "build request")
        current_head, clean = current_source_state(repo_root)
        release_heads = observe_release_heads(repo_root, args.remote)
        if args.validate is None:
            source_commit = current_head
        else:
            candidate = _read_json(args.validate.resolve(), "build plan")
            source = candidate.get("source")
            if not isinstance(source, dict):
                raise BuildPlanError("build plan source is missing")
            source_commit = str(source.get("commit", ""))
            validate_post_source_paths(
                repo_root, source_commit=source_commit, current_head=current_head
            )
        core_hash = common_core_hash(
            repo_root, source_commit, list(validate_request(request)["commonCorePaths"])
        )
        if args.validate is None:
            plan = create_build_plan(
                request,
                repo_root=repo_root,
                source_commit=source_commit,
                source_tree_clean=clean,
                observed_common_core_hash=core_hash,
                observed_release_heads=release_heads,
            )
            print(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", end="")
        else:
            validate_build_plan(
                candidate,
                request,
                repo_root=repo_root,
                observed_source_commit=source_commit,
                source_tree_clean=clean,
                observed_common_core_hash=core_hash,
                observed_release_heads=release_heads,
            )
    except (BuildPlanError, contract.DistributionContractError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
