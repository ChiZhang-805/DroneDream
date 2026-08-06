from __future__ import annotations

import argparse
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    ROOT
    / "distribution"
    / "editions"
    / "field"
    / "host-contained-install-validation.v1.json"
)
SCHEMA_PATH = (
    ROOT
    / "distribution"
    / "schemas"
    / "field-host-contained-install-evidence.schema.json"
)
FIELD_CONFIG_PATH = ROOT / "desktop" / "src-tauri" / "tauri.field.conf.json"
BASE_CONFIG_PATH = ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
NSIS_PATH = ROOT / "desktop" / "src-tauri" / "nsis" / "installer.nsi"
HANDOFF_PATH = ROOT / "desktop" / "src-tauri" / "src" / "installer_handoff.rs"
FIELD_APP_PATH = ROOT / "frontend" / "src" / "field" / "FieldApp.tsx"
FIELD_SAFETY_PATH = ROOT / "frontend" / "src" / "field" / "safety.ts"
EXECUTOR_PATH = (
    ROOT / "distribution" / "tools" / "execute_field_host_contained_acceptance.ps1"
)
ARTIFACT_MANIFEST_PATH = (
    ROOT
    / "artifacts"
    / "test-runs"
    / "field-preview-1.0.0-c7e25b3"
    / "artifact-manifest.json"
)

PLAN_KIND = "dronedream-field-host-contained-install-plan"
READINESS_KIND = "dronedream-field-host-contained-green-readiness-receipt"
EXECUTION_KIND = "dronedream-field-host-contained-execution-receipt"
FIELD_ARTIFACT = "DroneDream-Field-1.0.0.exe"
FIELD_PRODUCT = "DroneDream · FIELD"
FIELD_BUNDLE_ID = "io.dronedream.desktop.field"
PRODUCT_SOURCE = "c7e25b3862fdd491de99f4a0b02cf0f348b94ea3"
ARTIFACT_SHA256 = "ce3937440e85655d9532097904286eae783f6ed6b25eb0eb94ee113049139317"
PREVIOUS_VM_PLAN_SHA256 = "8fca6e3a5d66749ce9aeabca45edae4424e2548c28d2ca02edf4eb8e82244bb4"
PREVIOUS_VM_RECEIPT_SHA256 = "5690269c86128300b42bd9537d73261f73172b6218e6002a4fb7d36170134643"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class FieldHostContainedError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise FieldHostContainedError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise FieldHostContainedError(f"{label} must be a lowercase SHA-256")
    return value


def _require_commit(value: object, label: str) -> str:
    if not isinstance(value, str) or COMMIT_RE.fullmatch(value) is None:
        raise FieldHostContainedError(f"{label} must be a full lowercase commit")
    return value


def _exact_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise FieldHostContainedError(f"{label} fields drifted")


def validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        contract,
        {
            "schemaVersion",
            "kind",
            "editionId",
            "version",
            "isolationClass",
            "disposableWindowsGuestRequired",
            "claimsVmLevelIsolation",
            "artifact",
            "productIdentities",
            "fieldNamespaces",
            "ownedPaths",
            "writeSurfaces",
            "absentWriteSurfaces",
            "protectedState",
            "processEnvironment",
            "invocationBudget",
            "phases",
            "preconditions",
            "rollback",
            "knownExecutionBlockers",
            "websiteGate",
        },
        "contract",
    )
    if (
        contract["schemaVersion"] != 1
        or contract["editionId"] != "field"
        or contract["version"] != "1.0.0"
        or contract["isolationClass"] != "host-contained-owned-paths"
        or contract["disposableWindowsGuestRequired"] is not False
        or contract["claimsVmLevelIsolation"] is not False
    ):
        raise FieldHostContainedError("host-contained contract identity drifted")
    artifact = contract["artifact"]
    if artifact != {
        "filename": FIELD_ARTIFACT,
        "bytes": 11267482,
        "sha256": ARTIFACT_SHA256,
        "authenticodeStatus": "NotSigned",
        "productSourceCommit": PRODUCT_SOURCE,
    }:
        raise FieldHostContainedError("frozen Field artifact binding drifted")
    identities = contract["productIdentities"]
    if [item["editionId"] for item in identities] != ["universal", "sim", "lab", "field"]:
        raise FieldHostContainedError("edition identity order drifted")
    for key in (
        "productName",
        "bundleId",
        "defaultInstallRoot",
        "uninstallRegistryKey",
        "manufacturerRegistryKey",
        "startMenuShortcut",
        "desktopShortcut",
    ):
        values = [item[key].casefold() for item in identities]
        if len(values) != len(set(values)):
            raise FieldHostContainedError(f"edition identity collision: {key}")
    if identities[-1]["productName"] != FIELD_PRODUCT or identities[-1]["bundleId"] != FIELD_BUNDLE_ID:
        raise FieldHostContainedError("Field product identity drifted")
    if contract["fieldNamespaces"] != {
        "windowAndDisplayName": FIELD_PRODUCT,
        "appUserModelId": FIELD_BUNDLE_ID,
        "updaterEndpoint": "https://github.com/ChiZhang-805/DroneDream/releases/latest/download/field-latest.json",
        "enginePackProfileId": "field-lightweight",
        "dataNamespace": FIELD_BUNDLE_ID,
        "installedIconRelativePath": "icons\\DroneDream.ico",
        "canonicalIconSha256": "b90e188679d209009e5eda859665a3582efe1e9129e5f8ecce3c08783b794559",
    }:
        raise FieldHostContainedError("Field updater/profile/data/icon namespace drifted")
    absent = contract["absentWriteSurfaces"]
    if not all(absent.values()):
        raise FieldHostContainedError("forbidden write surface was enabled")
    budget = contract["invocationBudget"]
    if budget != {
        "installerExe": 2,
        "uninstaller": 1,
        "applicationLaunch": 2,
        "rebuild": 0,
        "networkRequest": 0,
        "deviceEnumeration": 0,
        "hardwareAction": 0,
        "simulation": 0,
    }:
        raise FieldHostContainedError("invocation budget drifted")
    environment = contract["processEnvironment"]
    for key in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        if not environment[key].startswith("ownedPaths."):
            raise FieldHostContainedError(f"{key} must redirect to an owned path")
    if environment["HTTP_PROXY"] != "http://127.0.0.1:9" or environment["HTTPS_PROXY"] != "http://127.0.0.1:9":
        raise FieldHostContainedError("external network proxy deny drifted")
    browser_arguments = environment["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]
    for marker in (
        "--disable-background-networking",
        "--disable-component-update",
        "--proxy-server=127.0.0.1:9",
        "--proxy-bypass-list=<-loopback>",
    ):
        if marker not in browser_arguments:
            raise FieldHostContainedError("WebView2 network deny arguments drifted")
    if contract["preconditions"]["webView2RepairAllowed"] is not False:
        raise FieldHostContainedError("shared WebView2 repair cannot be allowed")
    if contract["rollback"]["evidenceDeletionAllowed"] is not False:
        raise FieldHostContainedError("evidence deletion cannot be allowed")
    for blocker in contract["knownExecutionBlockers"]:
        _exact_keys(
            blocker,
            {
                "blockerId",
                "status",
                "attemptSourceCommit",
                "failureEvidencePath",
                "clearanceRequirement",
            },
            "known execution blocker",
        )
        if blocker["status"] != "open" or not blocker["blockerId"].startswith("field.host."):
            raise FieldHostContainedError("known execution blocker identity drifted")
        _require_commit(blocker["attemptSourceCommit"], "attemptSourceCommit")
        if not blocker["failureEvidencePath"].startswith("artifacts/test-runs/field-host-contained-"):
            raise FieldHostContainedError("known execution blocker evidence path drifted")
    if contract["websiteGate"]["websiteReadyBeforeExecution"] is not False:
        raise FieldHostContainedError("GREEN contract cannot authorize Website handoff")
    return contract


def audit_source(contract: dict[str, Any]) -> dict[str, Any]:
    validate_contract(contract)
    field = load_json(FIELD_CONFIG_PATH)
    base = load_json(BASE_CONFIG_PATH)
    nsis = NSIS_PATH.read_text(encoding="utf-8")
    handoff = HANDOFF_PATH.read_text(encoding="utf-8")
    field_app = FIELD_APP_PATH.read_text(encoding="utf-8")
    field_safety = FIELD_SAFETY_PATH.read_text(encoding="utf-8")
    executor = EXECUTOR_PATH.read_text(encoding="utf-8")
    artifact_manifest = load_json(ARTIFACT_MANIFEST_PATH)

    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, evidence: str) -> None:
        checks.append({"checkId": check_id, "passed": passed, "evidence": evidence})

    check("field-product-name", field.get("productName") == FIELD_PRODUCT, "tauri.field.conf.json:productName")
    check("field-bundle-id", field.get("identifier") == FIELD_BUNDLE_ID, "tauri.field.conf.json:identifier")
    check(
        "field-updater-endpoint",
        field.get("plugins", {}).get("updater", {}).get("endpoints")
        == [contract["fieldNamespaces"]["updaterEndpoint"]],
        "tauri.field.conf.json:plugins.updater.endpoints",
    )
    check(
        "current-user-install",
        base.get("bundle", {}).get("windows", {}).get("nsis", {}).get("installMode") == "currentUser",
        "tauri.conf.json:bundle.windows.nsis.installMode",
    )
    check("no-deep-link-plugin", "deep-link" not in field.get("plugins", {}) and "deep-link" not in base.get("plugins", {}), "merged Tauri plugins")
    check("no-file-associations", not field.get("bundle", {}).get("fileAssociations") and not base.get("bundle", {}).get("fileAssociations"), "merged Tauri bundle")
    required_nsis = (
        '!define UNINSTKEY "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${PRODUCTNAME}"',
        '!define MANUPRODUCTKEY "${MANUKEY}\\${PRODUCTNAME}"',
        'StrCpy $INSTDIR "$LOCALAPPDATA\\${PRODUCTNAME}"',
        'CreateShortcut "$SMPROGRAMS\\${PRODUCTNAME}.lnk"',
        'CreateShortcut "$DESKTOP\\${PRODUCTNAME}.lnk"',
        'DeleteRegValue HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Run" "${PRODUCTNAME}"',
    )
    check("nsis-product-scoped-writes", all(marker in nsis for marker in required_nsis), "installer.nsi product-scoped markers")
    forbidden_create = ("CreateService", "New-Service", "schtasks /Create", "WriteRegStr HKLM \"Software\\Microsoft\\Windows\\CurrentVersion\\Run")
    check("no-service-task-autorun-create", not any(marker in nsis for marker in forbidden_create), "installer.nsi forbidden create markers")
    check("shared-handoff-identified", 'const RECEIPT_DIRECTORY: &str = "io.dronedream.desktop";' in handoff, "installer_handoff.rs:RECEIPT_DIRECTORY")
    check("field-ui-no-native-invoke", "invoke(" not in field_app and "@tauri-apps/api" not in field_app, "FieldApp.tsx")
    check("field-ui-no-device-api", all(marker not in (field_app + field_safety).lower() for marker in ("navigator.serial", "navigator.usb", "serialport", "webusb")), "Field frontend sources")
    check("field-controls-disabled", "disabled" in field_app and "FIELD_HARDWARE_ACTIONS" in field_app, "FieldApp.tsx controls")
    check(
        "field-profile-and-icon",
        artifact_manifest.get("payload", {}).get("enginePack", {}).get("profileId")
        == contract["fieldNamespaces"]["enginePackProfileId"]
        and artifact_manifest.get("branding", {}).get("fieldIconSha256")
        == contract["fieldNamespaces"]["canonicalIconSha256"],
        "frozen artifact manifest profile and branding",
    )
    check(
        "executor-owned-environment",
        all(
            marker in executor
            for marker in (
                "$env:LOCALAPPDATA = $RedirectedLocal",
                "$env:APPDATA = $RedirectedRoaming",
                "$env:TEMP = $RedirectedTemp",
                "$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
            )
        ),
        "execute_field_host_contained_acceptance.ps1 environment",
    )
    check(
        "executor-budget-and-rollback",
        "installer invocation budget exhausted" in executor
        and "application launch budget exhausted" in executor
        and "Remove-ProvenNewPath" in executor
        and "Assert-ProtectedState" in executor,
        "execute_field_host_contained_acceptance.ps1 execution gates",
    )
    return {
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "sourceFiles": {
            str(path.relative_to(ROOT)).replace("\\", "/"): file_sha256(path)
            for path in (
                FIELD_CONFIG_PATH,
                BASE_CONFIG_PATH,
                NSIS_PATH,
                HANDOFF_PATH,
                FIELD_APP_PATH,
                FIELD_SAFETY_PATH,
                EXECUTOR_PATH,
                ARTIFACT_MANIFEST_PATH,
            )
        },
    }


def host_blockers(snapshot: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if snapshot.get("kind") != "dronedream-field-host-contained-host-snapshot":
        raise FieldHostContainedError("host snapshot identity drifted")
    paths = snapshot["paths"]
    registry = snapshot["registry"]
    shortcuts = snapshot["shortcuts"]
    if not paths["universalInstall"]["digest"]["exists"]:
        blockers.append("field.host.universal-install-baseline-missing")
    for key in ("fieldDefaultInstall", "ownedRoot", "fieldBundleRoaming", "fieldBundleLocal"):
        if paths[key]["digest"]["exists"]:
            blockers.append(f"field.host.preexisting-path:{key}")
    for key in ("fieldUninstall", "fieldProduct"):
        if registry[key]["exists"]:
            blockers.append(f"field.host.preexisting-registry:{key}")
    for key in ("fieldStartMenu", "fieldDesktop"):
        if shortcuts[key]["exists"]:
            blockers.append(f"field.host.preexisting-shortcut:{key}")
    field_run_name = FIELD_PRODUCT
    if field_run_name in registry["fieldAutorun"]["values"]:
        blockers.append("field.host.preexisting-autorun")
    if snapshot["processes"]:
        blockers.append("field.host.dronedream-process-running")
    runtime_status = snapshot["universalRuntimeStatus"]
    if runtime_status["operation"] != {"available": True, "exitCode": 0}:
        blockers.append("field.host.shared-runtime-operation-not-idle")
    if runtime_status["handoff"] != {"available": True, "exitCode": 0}:
        blockers.append("field.host.shared-installer-handoff-not-idle")
    if snapshot["webView2"]["healthy"] is not True:
        blockers.append("field.host.webview2-not-healthy-repair-forbidden")
    return blockers


def create_plan(
    *,
    contract: dict[str, Any],
    snapshot: dict[str, Any],
    evidence_head: str,
    artifact_absolute_path: str,
    snapshot_sha256: str,
) -> dict[str, Any]:
    validate_contract(contract)
    _require_commit(evidence_head, "evidenceHead")
    _require_sha(snapshot_sha256, "snapshotSha256")
    source_audit = audit_source(contract)
    blockers = host_blockers(snapshot)
    blockers.extend(
        item["blockerId"]
        for item in contract["knownExecutionBlockers"]
        if item["status"] == "open"
    )
    if not source_audit["passed"]:
        blockers.extend(
            f"field.host.source-audit:{item['checkId']}"
            for item in source_audit["checks"]
            if not item["passed"]
        )
    plan: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": PLAN_KIND,
        "editionId": "field",
        "state": "yellow-host-contained-requestable" if not blockers else "blocked",
        "source": {
            "productSourceCommit": PRODUCT_SOURCE,
            "evidenceHead": evidence_head,
            "contractSha256": file_sha256(CONTRACT_PATH),
            "toolSha256": file_sha256(Path(__file__)),
            "schemaSha256": file_sha256(SCHEMA_PATH),
            "hostSnapshotSha256": snapshot_sha256,
        },
        "previousVmEvidence": {
            "preserved": True,
            "planFileSha256": PREVIOUS_VM_PLAN_SHA256,
            "readinessReceiptFileSha256": PREVIOUS_VM_RECEIPT_SHA256,
            "decision": "deny-before-yellow",
        },
        "artifact": {
            **deepcopy(contract["artifact"]),
            "absolutePath": artifact_absolute_path,
        },
        "environment": {
            "isolationClass": "host-contained-owned-paths",
            "claimsVmLevelIsolation": False,
            "processEnvironment": deepcopy(contract["processEnvironment"]),
            "ownedPaths": deepcopy(contract["ownedPaths"]),
            "protectedState": deepcopy(contract["protectedState"]),
        },
        "fieldNamespaces": deepcopy(contract["fieldNamespaces"]),
        "sourceAudit": source_audit,
        "writeSurfaces": deepcopy(contract["writeSurfaces"]),
        "absentWriteSurfaces": deepcopy(contract["absentWriteSurfaces"]),
        "invocationBudget": deepcopy(contract["invocationBudget"]),
        "phases": [
            {"phaseId": phase_id, "state": "planned-not-executed"}
            for phase_id in contract["phases"]
        ],
        "preconditions": deepcopy(contract["preconditions"]),
        "rollback": deepcopy(contract["rollback"]),
        "safetyBoundary": {
            "validatedHardwarePackCount": 0,
            "frontendIsAuthority": False,
            "deviceEnumerationAllowed": False,
            "hardwareActionAllowed": False,
            "simulationAllowed": False,
            "externalNetworkAllowed": False,
        },
        "authorization": {
            "currentClass": "GREEN",
            "requestedExecutionClass": "YELLOW",
            "fullDeliveryAuthorizationSourceThreadId": "019fa6ec-e8e6-7222-8c4c-1a064d17a0a9",
            "planOnly": True,
            "executionPerformed": False,
            "rebuildAllowed": False,
            "releaseBranchAllowed": False,
            "uploadAllowed": False,
        },
        "websiteGate": {
            **deepcopy(contract["websiteGate"]),
            "websiteReady": False,
            "blockers": ["field.website.dynamic-host-acceptance-not-executed"],
        },
        "blockers": blockers,
    }
    plan["planSha256"] = canonical_sha256(plan)
    return validate_plan(plan)


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    expected_hash = plan.get("planSha256")
    unsigned = deepcopy(plan)
    unsigned.pop("planSha256", None)
    if _require_sha(expected_hash, "planSha256") != canonical_sha256(unsigned):
        raise FieldHostContainedError("plan hash mismatch")
    if plan.get("kind") != PLAN_KIND or plan.get("editionId") != "field":
        raise FieldHostContainedError("plan identity drifted")
    if plan["previousVmEvidence"] != {
        "preserved": True,
        "planFileSha256": PREVIOUS_VM_PLAN_SHA256,
        "readinessReceiptFileSha256": PREVIOUS_VM_RECEIPT_SHA256,
        "decision": "deny-before-yellow",
    }:
        raise FieldHostContainedError("previous VM evidence binding drifted")
    if plan["artifact"]["sha256"] != ARTIFACT_SHA256:
        raise FieldHostContainedError("artifact binding drifted")
    if plan["fieldNamespaces"] != validate_contract(load_json(CONTRACT_PATH))["fieldNamespaces"]:
        raise FieldHostContainedError("Field namespace binding drifted")
    if plan["environment"]["claimsVmLevelIsolation"] is not False:
        raise FieldHostContainedError("host-contained plan cannot claim VM isolation")
    if plan["authorization"]["executionPerformed"] is not False:
        raise FieldHostContainedError("GREEN plan cannot claim execution")
    if plan["websiteGate"]["websiteReady"] is not False:
        raise FieldHostContainedError("unexecuted plan cannot be Website-ready")
    if plan["safetyBoundary"] != {
        "validatedHardwarePackCount": 0,
        "frontendIsAuthority": False,
        "deviceEnumerationAllowed": False,
        "hardwareActionAllowed": False,
        "simulationAllowed": False,
        "externalNetworkAllowed": False,
    }:
        raise FieldHostContainedError("safety boundary drifted")
    expected_state = "yellow-host-contained-requestable" if not plan["blockers"] else "blocked"
    if plan["state"] != expected_state:
        raise FieldHostContainedError("plan state does not match blockers")
    return plan


def create_readiness_receipt(plan: dict[str, Any]) -> dict[str, Any]:
    validate_plan(plan)
    receipt: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": READINESS_KIND,
        "editionId": "field",
        "decision": "request-yellow-host-contained" if not plan["blockers"] else "deny",
        "planSha256": plan["planSha256"],
        "source": deepcopy(plan["source"]),
        "artifact": deepcopy(plan["artifact"]),
        "environment": deepcopy(plan["environment"]),
        "executionCounts": {key: 0 for key in plan["invocationBudget"]},
        "executionPerformed": False,
        "websiteReady": False,
        "blockers": deepcopy(plan["blockers"]),
    }
    receipt["receiptSha256"] = canonical_sha256(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Field host-contained GREEN readiness evidence")
    parser.add_argument("--host-snapshot", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--evidence-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    artifact = args.artifact.resolve(strict=True)
    if artifact.name != FIELD_ARTIFACT or artifact.stat().st_size != 11267482 or file_sha256(artifact) != ARTIFACT_SHA256:
        raise FieldHostContainedError("frozen Field artifact identity drifted")
    snapshot = load_json(args.host_snapshot)
    plan = create_plan(
        contract=load_json(CONTRACT_PATH),
        snapshot=snapshot,
        evidence_head=args.evidence_head,
        artifact_absolute_path=str(artifact),
        snapshot_sha256=file_sha256(args.host_snapshot),
    )
    receipt = create_readiness_receipt(plan)
    output = args.output_dir.resolve()
    write_json(output / "plan.json", plan)
    write_json(output / "green-readiness-receipt.json", receipt)
    print(
        json.dumps(
            {
                "decision": receipt["decision"],
                "planFileSha256": file_sha256(output / "plan.json"),
                "receiptFileSha256": file_sha256(output / "green-readiness-receipt.json"),
                "blockers": receipt["blockers"],
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
