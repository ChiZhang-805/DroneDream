from __future__ import annotations

import argparse
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

PLAN_KIND = "dronedream-field-isolated-install-acceptance-plan"
READINESS_KIND = "dronedream-field-isolated-install-green-readiness-receipt"
EXECUTION_KIND = "dronedream-field-isolated-install-execution-receipt"
FIELD_ARTIFACT = "DroneDream-Field-1.0.0.exe"
FIELD_PRODUCT_NAME = "DroneDream · FIELD"
FIELD_BUNDLE_ID = "io.dronedream.desktop.field"
WEBSITE_SOURCE = "afdcdee5b60883290c9d1cc0c036141920066659"
WEBSITE_EVIDENCE = "1a82e36b362c95983473c4a0d0d967d8c7415f92"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

PHASE_IDS = (
    "guest-baseline",
    "fresh-install-en",
    "fresh-launch-en",
    "same-version-overwrite-zh-CN",
    "shortcut-launch-zh-CN",
    "uninstall-delete-app-data",
    "residue-audit",
    "guest-discard-rollback",
)

INVOCATION_BUDGET = {
    "installerExe": 2,
    "uninstaller": 1,
    "applicationLaunch": 2,
    "rebuild": 0,
    "networkRequest": 0,
    "deviceEnumeration": 0,
    "hardwareAction": 0,
}

PROVIDER_IDS = (
    "windows-sandbox",
    "hyper-v",
    "vmware",
    "virtualbox",
    "qemu",
)


class FieldInstallAcceptanceError(ValueError):
    pass


def canonical_bytes(document: object) -> bytes:
    return json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_canonical(document: object) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise FieldInstallAcceptanceError(f"expected JSON object: {path}")
    return document


def write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _require_commit(value: object, name: str) -> str:
    if not isinstance(value, str) or COMMIT_RE.fullmatch(value) is None:
        raise FieldInstallAcceptanceError(f"{name} must be a full lowercase Git SHA")
    return value


def _require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise FieldInstallAcceptanceError(f"{name} must be a lowercase SHA-256")
    return value


def _exact_keys(document: dict[str, Any], expected: set[str], label: str) -> None:
    if set(document) != expected:
        raise FieldInstallAcceptanceError(f"{label} fields drifted")


def _phase(phase_id: str, *, locale: str | None, assertions: list[str]) -> dict[str, Any]:
    return {
        "phaseId": phase_id,
        "state": "planned-not-executed",
        "locale": locale,
        "assertions": assertions,
        "evidenceRequired": True,
    }


def _website_precheck(
    *,
    signature_status: str,
    unsigned_internal_authorized: bool,
    environment_available: bool,
    execution: dict[str, Any] | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    signature_acceptable = signature_status == "Valid" or (
        signature_status == "NotSigned" and unsigned_internal_authorized
    )
    if not signature_acceptable:
        blockers.append("field.website.signature-state-not-authorized")
    if not environment_available:
        blockers.append("field.website.isolated-environment-unavailable")
    if execution is None:
        blockers.extend(
            [
                "field.website.fresh-install-not-passed",
                "field.website.overwrite-not-passed",
                "field.website.uninstall-not-passed",
                "field.website.shortcut-not-passed",
                "field.website.webview2-not-passed",
                "field.website.en-zh-not-passed",
                "field.website.residue-not-passed",
                "field.website.rollback-not-passed",
                "field.website.url-family-not-frozen",
                "field.website.redownload-not-verified",
            ]
        )
    else:
        phase_results = {
            item["phaseId"]: item["result"] for item in execution["phases"]
        }
        for phase_id in PHASE_IDS:
            if phase_results.get(phase_id) != "pass":
                blockers.append(f"field.website.phase-not-passed:{phase_id}")
        checks = (
            (execution["shortcutEvidence"]["result"] == "pass", "shortcut-not-passed"),
            (execution["webView2Evidence"]["result"] == "pass", "webview2-not-passed"),
            (execution["localizationEvidence"]["result"] == "pass", "en-zh-not-passed"),
            (execution["residueEvidence"]["result"] == "pass", "residue-not-passed"),
            (execution["rollbackEvidence"]["result"] == "pass", "rollback-not-passed"),
            (execution["websiteMetadata"]["urlFamilyFrozen"], "url-family-not-frozen"),
            (execution["websiteMetadata"]["redownloadSha256Matched"], "redownload-not-verified"),
        )
        blockers.extend(f"field.website.{code}" for passed, code in checks if not passed)
    return {
        "websiteSourceCommit": WEBSITE_SOURCE,
        "websiteEvidenceCommit": WEBSITE_EVIDENCE,
        "state": "ready-for-exact-handoff" if not blockers else "blocked",
        "previewSubstitutionAllowed": False,
        "crossEditionAttachmentAllowed": False,
        "signatureState": signature_status,
        "unsignedInternalDistributionAuthorized": unsigned_internal_authorized,
        "websiteReady": not blockers,
        "blockers": blockers,
    }


def create_plan(
    *,
    artifact_manifest: dict[str, Any],
    build_receipt: dict[str, Any],
    artifact_manifest_sha256: str,
    build_receipt_sha256: str,
    evidence_head: str,
    host_probe: dict[str, Any],
) -> dict[str, Any]:
    _require_commit(evidence_head, "evidenceHead")
    _require_sha256(artifact_manifest_sha256, "artifactManifestSha256")
    _require_sha256(build_receipt_sha256, "buildReceiptSha256")

    artifact = artifact_manifest.get("artifact", {})
    receipt_artifact = build_receipt.get("artifact", {})
    source = artifact_manifest.get("productSource", {})
    if (
        artifact_manifest.get("editionId") != "field"
        or artifact_manifest.get("version") != "1.0.0"
        or build_receipt.get("editionId") != "field"
    ):
        raise FieldInstallAcceptanceError("artifact evidence is not Field 1.0.0")
    if artifact.get("filename") != FIELD_ARTIFACT:
        raise FieldInstallAcceptanceError("Field artifact filename drifted")
    for key in ("filename", "bytes", "sha256", "fileVersion", "productVersion"):
        if artifact.get(key) != receipt_artifact.get(key):
            raise FieldInstallAcceptanceError(f"artifact manifest/receipt mismatch: {key}")
    if source.get("commit") != build_receipt.get("productSourceHead"):
        raise FieldInstallAcceptanceError("product source binding drifted")
    if (
        build_receipt.get("previewReady") is not True
        or build_receipt.get("releaseReady") is not False
    ):
        raise FieldInstallAcceptanceError("expected preview-ready, release-blocked build receipt")
    if artifact.get("cargoBuildCount") != 1 or artifact.get("nsisInvocationCount") != 1:
        raise FieldInstallAcceptanceError("Field preview must remain the unique built artifact")
    _require_commit(source.get("commit"), "productSourceCommit")
    _require_commit(source.get("commonCoreCommit"), "commonCoreCommit")
    _require_sha256(source.get("commonCoreHash"), "commonCoreHash")
    _require_sha256(artifact.get("sha256"), "artifactSha256")

    _exact_keys(host_probe, {"host", "providers"}, "host probe")
    _exact_keys(
        host_probe["host"],
        {
            "osCaption",
            "osVersion",
            "osBuild",
            "osArchitecture",
            "totalPhysicalMemoryBytes",
        },
        "host probe host",
    )
    providers = host_probe.get("providers")
    if not isinstance(providers, list) or [item.get("providerId") for item in providers] != list(
        PROVIDER_IDS
    ):
        raise FieldInstallAcceptanceError("isolated provider probe drifted")
    for provider in providers:
        _exact_keys(
            provider,
            {"providerId", "available", "path", "version", "sha256"},
            "isolated provider",
        )
        if provider["available"]:
            if not provider["path"] or not provider["version"]:
                raise FieldInstallAcceptanceError("available provider identity is incomplete")
            _require_sha256(provider["sha256"], "providerSha256")
        elif any(provider[key] is not None for key in ("path", "version", "sha256")):
            raise FieldInstallAcceptanceError("unavailable provider cannot claim identity")
    available = [item for item in providers if item.get("available") is True]
    environment_available = bool(available)
    selected_provider = available[0]["providerId"] if available else None

    artifact_path = artifact.get("absolutePath")
    if not isinstance(artifact_path, str) or not artifact_path.lower().endswith(
        "\\" + FIELD_ARTIFACT.lower()
    ):
        raise FieldInstallAcceptanceError("artifact absolute path is invalid")

    host_root = (
        "C:\\Users\\zju20\\AppData\\Local\\DroneDream\\codex-test\\"
        f"field-install-acceptance-{source['commit'][:7]}"
    )
    phases = [
        _phase("guest-baseline", locale=None, assertions=["filesystem-registry-process-baseline"]),
        _phase(
            "fresh-install-en",
            locale="en",
            assertions=["current-user-install", "app-only", "desktop-shortcut-selected"],
        ),
        _phase(
            "fresh-launch-en",
            locale="en",
            assertions=["app-starts", "field-brand-visible", "hardware-actions-denied"],
        ),
        _phase(
            "same-version-overwrite-zh-CN",
            locale="zh-CN",
            assertions=["maintenance-reinstall", "source-sha-unchanged", "shortcut-icon-refreshed"],
        ),
        _phase(
            "shortcut-launch-zh-CN",
            locale="zh-CN",
            assertions=["start-menu-target", "desktop-target", "field-icon", "app-starts"],
        ),
        _phase(
            "uninstall-delete-app-data",
            locale="zh-CN",
            assertions=["uninstaller-success", "delete-app-data-selected"],
        ),
        _phase("residue-audit", locale=None, assertions=["no-unexpected-field-residue"]),
        _phase(
            "guest-discard-rollback",
            locale=None,
            assertions=["guest-discarded", "evidence-preserved"],
        ),
    ]

    plan: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": PLAN_KIND,
        "editionId": "field",
        "state": (
            "yellow-approval-required"
            if environment_available
            else "blocked-no-isolated-provider"
        ),
        "source": {
            "productSourceCommit": source["commit"],
            "evidenceHead": evidence_head,
            "commonCoreCommit": source["commonCoreCommit"],
            "commonCoreHash": source["commonCoreHash"],
            "artifactManifestSha256": artifact_manifest_sha256,
            "buildReceiptSha256": build_receipt_sha256,
            "toolSha256": sha256_file(Path(__file__)),
            "schemaSha256": sha256_file(
                ROOT
                / "distribution"
                / "schemas"
                / "field-install-acceptance-evidence.schema.json"
            ),
        },
        "artifact": {
            "absolutePath": artifact_path,
            "filename": FIELD_ARTIFACT,
            "version": "1.0.0",
            "bytes": artifact["bytes"],
            "sha256": artifact["sha256"],
            "authenticodeStatus": artifact_manifest["signature"]["authenticodeStatus"],
            "peCertificateTableBytes": artifact_manifest["signature"]["peCertificateTableBytes"],
            "buildCount": 1,
            "nsisInvocationCount": 1,
        },
        "authorization": {
            "currentClass": "GREEN",
            "requestedExecutionClass": "YELLOW",
            "authorizationSourceThreadId": "019fa6ec-e8e6-7222-8c4c-1a064d17a0a9",
            "unsignedInternalDistributionAuthorized": True,
            "planOnly": True,
            "installationAuthorized": False,
            "rebuildAuthorized": False,
            "uploadAuthorized": False,
            "deviceAccessAuthorized": False,
            "releaseBranchAuthorized": False,
        },
        "environment": {
            "requiredClass": "disposable-windows-guest",
            "host": deepcopy(host_probe["host"]),
            "providers": deepcopy(providers),
            "probeSha256": sha256_canonical(host_probe),
            "selectedProvider": selected_provider,
            "available": environment_available,
            "guestIdentityMustBeCaptured": True,
            "networkMode": "disabled",
            "clipboardRedirection": "disabled",
            "deviceRedirection": "disabled",
            "rollbackMode": "discard-entire-guest",
        },
        "ownedPaths": {
            "hostArtifact": {"path": artifact_path, "mode": "read-only"},
            "hostOwnedRoot": host_root,
            "hostEvidenceRoot": host_root + r"\evidence",
            "guestOwnedRoot": r"C:\FieldAcceptance",
            "guestInstallDirectory": rf"%LOCALAPPDATA%\{FIELD_PRODUCT_NAME}",
            "guestBundleData": [
                rf"%APPDATA%\{FIELD_BUNDLE_ID}",
                rf"%LOCALAPPDATA%\{FIELD_BUNDLE_ID}",
            ],
            "guestShortcuts": [
                rf"%APPDATA%\Microsoft\Windows\Start Menu\Programs\{FIELD_PRODUCT_NAME}.lnk",
                rf"%USERPROFILE%\Desktop\{FIELD_PRODUCT_NAME}.lnk",
            ],
            "guestRegistryKeys": [
                rf"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{FIELD_PRODUCT_NAME}",
                rf"HKCU\Software\DroneDream\{FIELD_PRODUCT_NAME}",
            ],
            "writesOutsideDisposableGuestAllowed": False,
        },
        "invocationBudget": deepcopy(INVOCATION_BUDGET),
        "upgradeSemantics": {
            "coveredScenario": "same-version-overwrite-reinstall",
            "semanticVersionUpgradeCovered": False,
            "semanticVersionUpgradeClaimAllowed": False,
            "priorFieldInstallerRequiredForSemanticUpgrade": True,
        },
        "phases": phases,
        "shortcutGate": {
            "target": rf"%LOCALAPPDATA%\{FIELD_PRODUCT_NAME}\drone-dream-desktop.exe",
            "icon": rf"%LOCALAPPDATA%\{FIELD_PRODUCT_NAME}\icons\DroneDream.ico",
            "startMenuRequired": True,
            "desktopRequiredWhenSelected": True,
            "appUserModelIdRequired": True,
        },
        "webView2Gate": {
            "networkAllowed": False,
            "embeddedBootstrapperSha256": artifact_manifest["installerStructure"][
                "webView2BootstrapperSha256"
            ],
            "runtimeExecutableHealthRequired": True,
            "sharedRuntimeMayRemainAfterUninstall": True,
        },
        "localizationGate": {
            "locales": ["en", "zh-CN"],
            "installerUiRequired": True,
            "applicationUiRequired": True,
            "keyboardTraversalRequired": True,
            "screenReaderNamesRequired": True,
        },
        "residueGate": {
            "mustBeAbsent": [
                "guestInstallDirectory",
                "guestBundleData",
                "guestShortcuts",
                "guestRegistryKeys",
                "drone-dream-desktop-process",
                "uninstall-process",
            ],
            "allowedResidue": [
                "shared-microsoft-webview2-runtime",
                "hostEvidenceRoot",
            ],
            "unexpectedProductResidueDecision": "fail",
        },
        "rollbackGate": {
            "method": "discard-entire-guest",
            "rollbackRequiredOnPass": True,
            "rollbackRequiredOnFailure": True,
            "evidenceMustBeCopiedBeforeDiscard": True,
            "evidenceDeletionAllowed": False,
            "hostProductStateMutationAllowed": False,
        },
        "safetyBoundary": {
            "validatedHardwarePackCount": 0,
            "deviceEnumerationAllowed": False,
            "usbSerialOpenAllowed": False,
            "parameterWriteAllowed": False,
            "unlockArmFlightAllowed": False,
            "simulationAllowed": False,
            "frontendIsAuthority": False,
        },
        "websiteHandoffPrecheck": _website_precheck(
            signature_status=artifact_manifest["signature"]["authenticodeStatus"],
            unsigned_internal_authorized=True,
            environment_available=environment_available,
            execution=None,
        ),
    }
    plan["planSha256"] = sha256_canonical(plan)
    return validate_plan(plan)


def validate_plan(document: dict[str, Any]) -> dict[str, Any]:
    expected_top = {
        "schemaVersion",
        "kind",
        "editionId",
        "state",
        "source",
        "artifact",
        "authorization",
        "environment",
        "ownedPaths",
        "invocationBudget",
        "upgradeSemantics",
        "phases",
        "shortcutGate",
        "webView2Gate",
        "localizationGate",
        "residueGate",
        "rollbackGate",
        "safetyBoundary",
        "websiteHandoffPrecheck",
        "planSha256",
    }
    _exact_keys(document, expected_top, "plan")
    expected_hash = document["planSha256"]
    unsigned = deepcopy(document)
    unsigned.pop("planSha256")
    if _require_sha256(expected_hash, "planSha256") != sha256_canonical(unsigned):
        raise FieldInstallAcceptanceError("plan hash mismatch")
    if (
        document["schemaVersion"] != 1
        or document["kind"] != PLAN_KIND
        or document["editionId"] != "field"
    ):
        raise FieldInstallAcceptanceError("plan identity drifted")
    if (
        document["artifact"]["filename"] != FIELD_ARTIFACT
        or document["artifact"]["buildCount"] != 1
    ):
        raise FieldInstallAcceptanceError("artifact binding drifted")
    if document["authorization"] != {
        "currentClass": "GREEN",
        "requestedExecutionClass": "YELLOW",
        "authorizationSourceThreadId": "019fa6ec-e8e6-7222-8c4c-1a064d17a0a9",
        "unsignedInternalDistributionAuthorized": True,
        "planOnly": True,
        "installationAuthorized": False,
        "rebuildAuthorized": False,
        "uploadAuthorized": False,
        "deviceAccessAuthorized": False,
        "releaseBranchAuthorized": False,
    }:
        raise FieldInstallAcceptanceError("GREEN/YELLOW authorization boundary drifted")
    environment = document["environment"]
    if (
        environment["requiredClass"] != "disposable-windows-guest"
        or environment["networkMode"] != "disabled"
        or environment["deviceRedirection"] != "disabled"
        or environment["rollbackMode"] != "discard-entire-guest"
    ):
        raise FieldInstallAcceptanceError("isolated environment boundary drifted")
    provider_ids = [item["providerId"] for item in environment["providers"]]
    if provider_ids != list(PROVIDER_IDS):
        raise FieldInstallAcceptanceError("provider inventory drifted")
    probe = {"host": environment["host"], "providers": environment["providers"]}
    if environment["probeSha256"] != sha256_canonical(probe):
        raise FieldInstallAcceptanceError("host provider probe hash drifted")
    actual_available = [
        item["providerId"] for item in environment["providers"] if item["available"]
    ]
    if environment["available"] != bool(actual_available):
        raise FieldInstallAcceptanceError("provider availability drifted")
    expected_selected = actual_available[0] if actual_available else None
    if environment["selectedProvider"] != expected_selected:
        raise FieldInstallAcceptanceError("selected provider drifted")
    expected_state = (
        "yellow-approval-required" if actual_available else "blocked-no-isolated-provider"
    )
    if document["state"] != expected_state:
        raise FieldInstallAcceptanceError("plan state drifted")
    if document["invocationBudget"] != INVOCATION_BUDGET:
        raise FieldInstallAcceptanceError("invocation budget drifted")
    if [item["phaseId"] for item in document["phases"]] != list(PHASE_IDS):
        raise FieldInstallAcceptanceError("execution phase order drifted")
    if any(item["state"] != "planned-not-executed" for item in document["phases"]):
        raise FieldInstallAcceptanceError("plan cannot claim executed phases")
    if document["ownedPaths"]["writesOutsideDisposableGuestAllowed"]:
        raise FieldInstallAcceptanceError("host write boundary drifted")
    if document["rollbackGate"]["evidenceDeletionAllowed"]:
        raise FieldInstallAcceptanceError("evidence deletion cannot be allowed")
    if document["residueGate"]["unexpectedProductResidueDecision"] != "fail":
        raise FieldInstallAcceptanceError("residue gate must fail closed")
    if document["safetyBoundary"] != {
        "validatedHardwarePackCount": 0,
        "deviceEnumerationAllowed": False,
        "usbSerialOpenAllowed": False,
        "parameterWriteAllowed": False,
        "unlockArmFlightAllowed": False,
        "simulationAllowed": False,
        "frontendIsAuthority": False,
    }:
        raise FieldInstallAcceptanceError("hardware safety boundary drifted")
    if document["websiteHandoffPrecheck"]["websiteReady"]:
        raise FieldInstallAcceptanceError("unexecuted preview cannot be Website-ready")
    return document


def create_readiness_receipt(plan: dict[str, Any]) -> dict[str, Any]:
    plan = validate_plan(plan)
    environment_available = plan["environment"]["available"]
    blockers = [
        "field.install.yellow-approval-required",
        "field.install.dynamic-acceptance-not-executed",
        "field.install.website-handoff-blocked",
    ]
    if not environment_available:
        blockers.insert(0, "field.install.environment.unavailable")
    receipt: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": READINESS_KIND,
        "editionId": "field",
        "decision": (
            "deny-before-yellow"
            if not environment_available
            else "request-yellow-approval"
        ),
        "planSha256": plan["planSha256"],
        "source": deepcopy(plan["source"]),
        "artifact": deepcopy(plan["artifact"]),
        "environment": deepcopy(plan["environment"]),
        "invocationBudget": deepcopy(plan["invocationBudget"]),
        "impact": {
            "hostInstallerExecution": False,
            "guestInstallerExecutionPlanned": True,
            "guestRegistryAndFilesystemMutationPlanned": True,
            "sharedWebView2RepairMayExecuteInsideGuest": True,
            "network": "disabled",
            "deviceAccess": "denied",
            "hostProductState": "must-remain-unchanged",
        },
        "rollback": deepcopy(plan["rollbackGate"]),
        "executionCounts": {key: 0 for key in INVOCATION_BUDGET},
        "executionPerformed": False,
        "websiteHandoffPrecheck": deepcopy(plan["websiteHandoffPrecheck"]),
        "blockers": blockers,
    }
    receipt["receiptSha256"] = sha256_canonical(receipt)
    return validate_readiness_receipt(receipt, plan=plan)


def validate_readiness_receipt(
    document: dict[str, Any], *, plan: dict[str, Any]
) -> dict[str, Any]:
    validate_plan(plan)
    expected_hash = document.get("receiptSha256")
    unsigned = deepcopy(document)
    unsigned.pop("receiptSha256", None)
    if _require_sha256(expected_hash, "receiptSha256") != sha256_canonical(unsigned):
        raise FieldInstallAcceptanceError("readiness receipt hash mismatch")
    if document.get("kind") != READINESS_KIND or document.get("editionId") != "field":
        raise FieldInstallAcceptanceError("readiness receipt identity drifted")
    if document.get("planSha256") != plan["planSha256"]:
        raise FieldInstallAcceptanceError("readiness receipt plan binding drifted")
    if document.get("executionPerformed") is not False or any(document["executionCounts"].values()):
        raise FieldInstallAcceptanceError("GREEN readiness cannot claim installer execution")
    if document["websiteHandoffPrecheck"]["websiteReady"]:
        raise FieldInstallAcceptanceError("GREEN readiness cannot authorize Website handoff")
    if not plan["environment"]["available"] and document["decision"] != "deny-before-yellow":
        raise FieldInstallAcceptanceError("missing isolated provider must deny before YELLOW")
    return document


def evaluate_execution_for_website(
    execution: dict[str, Any], *, plan: dict[str, Any]
) -> dict[str, Any]:
    validate_plan(plan)
    if not plan["environment"]["available"]:
        raise FieldInstallAcceptanceError("execution requires an available isolated provider")
    if execution.get("planSha256") != plan["planSha256"]:
        raise FieldInstallAcceptanceError("execution plan binding drifted")
    if execution.get("artifactSha256") != plan["artifact"]["sha256"]:
        raise FieldInstallAcceptanceError("execution artifact binding drifted")
    if execution.get("invocationCounts") != INVOCATION_BUDGET:
        raise FieldInstallAcceptanceError("execution invocation counts drifted")
    if execution["environment"]["networkMode"] != "disabled":
        raise FieldInstallAcceptanceError("execution network boundary drifted")
    if execution["environment"]["providerId"] != plan["environment"]["selectedProvider"]:
        raise FieldInstallAcceptanceError("execution provider binding drifted")
    _require_sha256(execution["environment"]["providerSha256"], "executionProviderSha256")
    if execution["environment"]["deviceRedirection"] != "disabled":
        raise FieldInstallAcceptanceError("execution device redirection drifted")
    if [item["phaseId"] for item in execution["phases"]] != list(PHASE_IDS):
        raise FieldInstallAcceptanceError("execution phase order drifted")
    for phase in execution["phases"]:
        _require_sha256(phase["evidenceSha256"], f"{phase['phaseId']}EvidenceSha256")
    if (
        execution["signatureEvidence"]["authenticodeStatus"]
        != plan["artifact"]["authenticodeStatus"]
    ):
        raise FieldInstallAcceptanceError("execution signature evidence drifted")
    shortcut = execution["shortcutEvidence"]
    if (
        shortcut["startMenuTargetMatched"] is not True
        or shortcut["desktopTargetMatched"] is not True
        or shortcut["iconMatched"] is not True
        or shortcut["appUserModelIdPresent"] is not True
    ):
        raise FieldInstallAcceptanceError("shortcut evidence is incomplete")
    webview = execution["webView2Evidence"]
    if webview["networkRequests"] != 0 or webview["runtimeExecutableHealthy"] is not True:
        raise FieldInstallAcceptanceError("WebView2 evidence drifted")
    localization = execution["localizationEvidence"]
    if not all(
        localization[key]
        for key in (
            "englishInstallerPassed",
            "chineseInstallerPassed",
            "englishApplicationPassed",
            "chineseApplicationPassed",
            "keyboardPassed",
            "screenReaderNamesPassed",
        )
    ):
        raise FieldInstallAcceptanceError("localization/accessibility evidence is incomplete")
    if execution["residueEvidence"]["unexpectedResidue"]:
        raise FieldInstallAcceptanceError("unexpected Field residue remains")
    rollback = execution["rollbackEvidence"]
    if not (
        rollback["guestDiscarded"]
        and rollback["evidencePreserved"]
        and rollback["hostProductStateUnchanged"]
    ):
        raise FieldInstallAcceptanceError("rollback evidence is incomplete")
    safety = execution["safetyEvidence"]
    if any(
        safety[key]
        for key in (
            "deviceEnumerationExecuted",
            "usbSerialOpened",
            "hardwareActionExecuted",
            "simulationExecuted",
        )
    ):
        raise FieldInstallAcceptanceError("execution crossed hardware/simulation boundary")
    return _website_precheck(
        signature_status=execution["signatureEvidence"]["authenticodeStatus"],
        unsigned_internal_authorized=plan["authorization"][
            "unsignedInternalDistributionAuthorized"
        ],
        environment_available=True,
        execution=execution,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the Field isolated installer GREEN readiness plan"
    )
    parser.add_argument("--artifact-manifest", type=Path, required=True)
    parser.add_argument("--build-receipt", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--host-probe", type=Path, required=True)
    parser.add_argument("--evidence-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    artifact_manifest = load_json(args.artifact_manifest)
    build_receipt = load_json(args.build_receipt)
    artifact_path = args.artifact.resolve(strict=True)
    expected_path = Path(artifact_manifest["artifact"]["absolutePath"]).resolve(strict=True)
    if artifact_path != expected_path:
        raise FieldInstallAcceptanceError("artifact path does not match frozen manifest")
    if artifact_path.name != FIELD_ARTIFACT:
        raise FieldInstallAcceptanceError("artifact filename drifted")
    if artifact_path.stat().st_size != artifact_manifest["artifact"]["bytes"]:
        raise FieldInstallAcceptanceError("artifact byte count drifted")
    if sha256_file(artifact_path) != artifact_manifest["artifact"]["sha256"]:
        raise FieldInstallAcceptanceError("artifact SHA-256 drifted")

    plan = create_plan(
        artifact_manifest=artifact_manifest,
        build_receipt=build_receipt,
        artifact_manifest_sha256=sha256_file(args.artifact_manifest),
        build_receipt_sha256=sha256_file(args.build_receipt),
        evidence_head=args.evidence_head,
        host_probe=load_json(args.host_probe),
    )
    receipt = create_readiness_receipt(plan)
    output = args.output_dir.resolve()
    write_json(output / "plan.json", plan)
    write_json(output / "green-readiness-receipt.json", receipt)
    print(
        json.dumps(
            {
                "decision": receipt["decision"],
                "planPath": str(output / "plan.json"),
                "planSha256": sha256_file(output / "plan.json"),
                "receiptPath": str(output / "green-readiness-receipt.json"),
                "receiptSha256": sha256_file(output / "green-readiness-receipt.json"),
                "artifactSha256": plan["artifact"]["sha256"],
                "environmentAvailable": plan["environment"]["available"],
                "executionPerformed": False,
                "websiteReady": False,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
