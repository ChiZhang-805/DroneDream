from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"

KIND = "dronedream-field-lifecycle-refusal-contract"
RECEIPT_KIND = "dronedream-field-lifecycle-refusal-receipt"
FIELD_ARTIFACT_BASENAME = "DroneDream-Field-1.0.0.exe"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

LIFECYCLE_SCENARIOS = (
    "fresh-install",
    "upgrade",
    "uninstall",
    "rollback",
)
DANGEROUS_ACTIONS = (
    "hardware.parameter.write",
    "hardware.unlock",
    "hardware.arm",
    "hardware.flight",
)
OFFLINE_SCENARIOS = (
    "offline-no-network",
    "device-missing",
)
REQUIRED_LOCALIZED_KEYS = (
    "title",
    "body",
    "primaryActionLabel",
    "screenReaderSummary",
)


class FieldLifecycleContractError(ValueError):
    pass


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
        raise FieldLifecycleContractError(f"expected JSON object: {path}")
    return document


def _require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise FieldLifecycleContractError(f"{name} must be a lowercase SHA-256")
    return value


def _require_commit(value: object, name: str) -> str:
    if not isinstance(value, str) or COMMIT_RE.fullmatch(value) is None:
        raise FieldLifecycleContractError(f"{name} must be a full lowercase Git SHA")
    return value


def _localized_message(scenario_id: str) -> dict[str, dict[str, str]]:
    text = {
        "en": {
            "title": "Action unavailable",
            "body": f"{scenario_id} is blocked in Field until signed hardware validation is present.",
            "primaryActionLabel": "Review receipt",
            "screenReaderSummary": f"{scenario_id} denied; no hardware action was executed.",
        },
        "zh-CN": {
            "title": "操作不可用",
            "body": f"Field 在具备签名硬件验证前会阻止 {scenario_id}。",
            "primaryActionLabel": "查看回执",
            "screenReaderSummary": f"{scenario_id} 已拒绝；未执行任何硬件动作。",
        },
    }
    return text


def create_lifecycle_contract(
    *,
    common_core_commit: str,
    common_core_hash: str,
    field_manifest_sha256: str,
    capability_policy_sha256: str,
    execution_gate_policy_sha256: str,
) -> dict[str, Any]:
    source = {
        "commonCoreCommit": _require_commit(common_core_commit, "commonCoreCommit"),
        "commonCoreHash": _require_sha256(common_core_hash, "commonCoreHash"),
        "fieldManifestSha256": _require_sha256(
            field_manifest_sha256, "fieldManifestSha256"
        ),
        "capabilityPolicySha256": _require_sha256(
            capability_policy_sha256, "capabilityPolicySha256"
        ),
        "executionGatePolicySha256": _require_sha256(
            execution_gate_policy_sha256, "executionGatePolicySha256"
        ),
    }
    lifecycle = [
        {
            "scenarioId": scenario,
            "state": "planned-not-executed",
            "expectedArtifactBaseName": FIELD_ARTIFACT_BASENAME,
            "installerBuilt": False,
            "installerInstalled": False,
            "writesFilesystemOutsidePlan": False,
            "requiresRollbackReceipt": scenario in {"upgrade", "uninstall", "rollback"},
            "decision": "deny",
            "reasonCodes": [
                "field.lifecycle.plan-only",
                "field.installer.not-built",
            ],
            "localizedMessage": _localized_message(scenario),
        }
        for scenario in LIFECYCLE_SCENARIOS
    ]
    refusals = [
        {
            "scenarioId": f"dangerous-{action}",
            "action": action,
            "decision": "deny",
            "frontendIsAuthority": False,
            "requiresValidatedSignedPack": True,
            "requiresThreeLayerQuorum": True,
            "reasonCodes": [
                "field.registry.zero-validated-packs",
                "field.quorum.missing-three-layer",
                "field.hardware-action.fail-closed",
            ],
            "localizedMessage": _localized_message(f"dangerous-{action}"),
        }
        for action in DANGEROUS_ACTIONS
    ]
    refusals.extend(
        {
            "scenarioId": scenario,
            "action": "hardware.discover",
            "decision": "deny",
            "frontendIsAuthority": False,
            "requiresValidatedSignedPack": True,
            "requiresThreeLayerQuorum": True,
            "reasonCodes": [
                "field.offline-or-device-missing",
                "field.discovery.not-authorization",
            ],
            "localizedMessage": _localized_message(scenario),
        }
        for scenario in OFFLINE_SCENARIOS
    )
    document = {
        "schemaVersion": 1,
        "kind": KIND,
        "editionId": "field",
        "source": source,
        "artifactPolicy": {
            "expectedBaseName": FIELD_ARTIFACT_BASENAME,
            "exeBuilt": False,
            "exeInstalled": False,
            "unsignedPreviewAllowedOnlyWhenExplicit": True,
            "signatureMayBeClaimed": False,
        },
        "lifecycleScenarios": lifecycle,
        "refusalScenarios": refusals,
        "accessibilityPolicy": {
            "localizedLanguages": ["en", "zh-CN"],
            "screenReaderSummaryRequired": True,
            "keyboardAccessibleReviewActionRequired": True,
        },
    }
    document["contractSha256"] = sha256_canonical(document)
    return document


def _validate_localized_message(message: object, label: str) -> None:
    if not isinstance(message, dict) or set(message) != {"en", "zh-CN"}:
        raise FieldLifecycleContractError(f"{label} localized message languages drifted")
    for locale in ("en", "zh-CN"):
        value = message[locale]
        if not isinstance(value, dict) or set(value) != set(REQUIRED_LOCALIZED_KEYS):
            raise FieldLifecycleContractError(f"{label} localized message fields drifted")
        for key in REQUIRED_LOCALIZED_KEYS:
            if not isinstance(value[key], str) or not value[key].strip():
                raise FieldLifecycleContractError(f"{label} localized message is empty")


def validate_lifecycle_contract(document: dict[str, Any]) -> dict[str, Any]:
    expected_top = {
        "schemaVersion",
        "kind",
        "editionId",
        "source",
        "artifactPolicy",
        "lifecycleScenarios",
        "refusalScenarios",
        "accessibilityPolicy",
        "contractSha256",
    }
    if set(document) != expected_top:
        raise FieldLifecycleContractError("Field lifecycle contract fields drifted")
    if document["schemaVersion"] != 1 or document["kind"] != KIND or document["editionId"] != "field":
        raise FieldLifecycleContractError("Field lifecycle contract identity is invalid")
    expected_hash = document["contractSha256"]
    unhashed = dict(document)
    unhashed.pop("contractSha256")
    if sha256_canonical(unhashed) != expected_hash:
        raise FieldLifecycleContractError("Field lifecycle contract hash drifted")

    source = document["source"]
    if set(source) != {
        "commonCoreCommit",
        "commonCoreHash",
        "fieldManifestSha256",
        "capabilityPolicySha256",
        "executionGatePolicySha256",
    }:
        raise FieldLifecycleContractError("Field lifecycle source binding drifted")
    _require_commit(source["commonCoreCommit"], "commonCoreCommit")
    for key in (
        "commonCoreHash",
        "fieldManifestSha256",
        "capabilityPolicySha256",
        "executionGatePolicySha256",
    ):
        _require_sha256(source[key], key)

    artifact = document["artifactPolicy"]
    if artifact != {
        "expectedBaseName": FIELD_ARTIFACT_BASENAME,
        "exeBuilt": False,
        "exeInstalled": False,
        "unsignedPreviewAllowedOnlyWhenExplicit": True,
        "signatureMayBeClaimed": False,
    }:
        raise FieldLifecycleContractError("Field artifact policy must remain non-executed")

    lifecycle = document["lifecycleScenarios"]
    if not isinstance(lifecycle, list) or [item["scenarioId"] for item in lifecycle] != list(
        LIFECYCLE_SCENARIOS
    ):
        raise FieldLifecycleContractError("Field lifecycle scenario set drifted")
    for item in lifecycle:
        if item["decision"] != "deny" or item["installerBuilt"] or item["installerInstalled"]:
            raise FieldLifecycleContractError("Field lifecycle scenario must be plan-only deny")
        if item["writesFilesystemOutsidePlan"]:
            raise FieldLifecycleContractError("Field lifecycle scenario must not write")
        _validate_localized_message(item["localizedMessage"], item["scenarioId"])

    refusals = document["refusalScenarios"]
    expected_refusal_ids = [f"dangerous-{action}" for action in DANGEROUS_ACTIONS] + list(
        OFFLINE_SCENARIOS
    )
    if not isinstance(refusals, list) or [item["scenarioId"] for item in refusals] != expected_refusal_ids:
        raise FieldLifecycleContractError("Field refusal scenario set drifted")
    for item in refusals:
        if item["decision"] != "deny":
            raise FieldLifecycleContractError("Field refusal scenario must deny")
        if item["frontendIsAuthority"]:
            raise FieldLifecycleContractError("frontend cannot authorize Field hardware")
        if not item["requiresValidatedSignedPack"] or not item["requiresThreeLayerQuorum"]:
            raise FieldLifecycleContractError("Field refusal scenario lost hardware gates")
        _validate_localized_message(item["localizedMessage"], item["scenarioId"])

    accessibility = document["accessibilityPolicy"]
    if accessibility != {
        "localizedLanguages": ["en", "zh-CN"],
        "screenReaderSummaryRequired": True,
        "keyboardAccessibleReviewActionRequired": True,
    }:
        raise FieldLifecycleContractError("Field accessibility policy drifted")
    return document


def create_lifecycle_receipt(document: dict[str, Any]) -> dict[str, Any]:
    contract = validate_lifecycle_contract(document)
    receipt = {
        "schemaVersion": 1,
        "kind": RECEIPT_KIND,
        "editionId": "field",
        "decision": "deny",
        "contractSha256": contract["contractSha256"],
        "source": contract["source"],
        "artifactPolicy": contract["artifactPolicy"],
        "scenarioCounts": {
            "lifecycle": len(contract["lifecycleScenarios"]),
            "refusal": len(contract["refusalScenarios"]),
        },
        "reasonCodes": [
            "field.lifecycle.plan-only",
            "field.hardware-action.fail-closed",
            "field.offline-or-device-missing",
        ],
    }
    receipt["receiptSha256"] = sha256_canonical(receipt)
    return receipt
