#!/usr/bin/env python3
"""Validate DroneDream distribution contracts without third-party packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

INVENTORY_KEYS = {"schemaVersion", "kind", "auditDate", "policy", "sources"}
POLICY_KEYS = {
    "mutableReferencesForbidden",
    "copyRequiresLicenseReview",
    "validationLabelsAreEvidenceBound",
}
SOURCE_REQUIRED_KEYS = {
    "id",
    "project",
    "officialRepository",
    "integrationStatus",
    "integrationMode",
    "distributionMode",
    "copiedIntoRepository",
    "pin",
    "licenseConclusion",
    "licenseEvidence",
    "noticeObligations",
    "validationTier",
    "validationNotes",
}
SOURCE_OPTIONAL_KEYS = {"auditedUpstreamCommit", "declaredLicenses"}
PIN_KEYS = {"kind", "value", "commit", "authority"}
LICENSE_EVIDENCE_KEYS = {"url", "sha256", "scope"}
INTEGRATION_STATUSES = {"current", "transitive", "evaluated", "planned"}
INTEGRATION_MODES = {
    "compiled-at-runtime-build",
    "apt-metapackage",
    "python-package",
    "px4-submodule",
    "external-launch-only",
    "contract-only",
}
DISTRIBUTION_MODES = {"runtime-bundled", "runtime-transitive", "not-distributed"}
PIN_KINDS = {"commit", "tag-and-commit", "apt-version", "oci-digest"}
VALIDATION_TIERS = {
    "integrated-contract",
    "external-integration-reviewed",
    "contract-only",
    "legal-review-required",
}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DOTTED_ID_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
LICENSE_RE = re.compile(r"^(?:[A-Za-z0-9.+-]+(?: (?:AND|OR) [A-Za-z0-9.+-]+)*|NOASSERTION)$")
IMMUTABLE_RAW_LICENSE_RE = re.compile(
    r"^https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/"
)
CAPABILITY_POLICY_KEYS = {
    "schemaVersion",
    "kind",
    "policyId",
    "policyVersion",
    "defaultDecision",
    "frontendIsAuthority",
    "llmControlBoundary",
    "targetContext",
    "conditionDefinitions",
    "capabilities",
}
CONDITION_KEYS = {"id", "description", "enforcedBy"}
CAPABILITY_KEYS = {
    "id",
    "risk",
    "targetKinds",
    "requiredEnforcementLayers",
    "decisions",
}
DECISION_KEYS = {"decision", "conditions", "reason"}
EDITION_KEYS = {
    "schemaVersion",
    "kind",
    "editionId",
    "editionVersion",
    "productDisplayVersion",
    "displayName",
    "description",
    "implementationStatus",
    "validationTier",
    "artifactBaseName",
    "capabilityPolicy",
    "modules",
    "capabilities",
    "runtimeProfile",
    "qualification",
    "sourcePolicy",
    "releaseChannel",
    "knownGaps",
}
EDITION_IDS = {"sim", "lab", "field", "autonomy"}
EDITION_BRANCHES = {
    "sim": "codex/software-sim",
    "lab": "codex/software-lab",
    "field": "codex/software-field",
    # The protocol/storage identity remains `autonomy`; the product channel is AGENT.
    "autonomy": "codex/software-agent",
}
ENFORCEMENT_LAYERS = {"backend", "runtime", "native"}
CONDITION_LAYERS = ENFORCEMENT_LAYERS | {"operator"}
TARGET_KINDS = {"installation", "simulation", "hitl", "real-hardware"}
RISK_LEVELS = {"read-only", "controlled", "safety-critical"}
DECISIONS = {"allow", "conditioned", "deny"}
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SAFE_RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*$")
ED25519_KEY_ID_RE = re.compile(r"^ed25519:[0-9a-f]{64}$")
PARAMETER_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
VEHICLE_PACK_KEYS = {
    "schemaVersion",
    "kind",
    "packId",
    "packVersion",
    "displayName",
    "manufacturer",
    "vehicleClass",
    "availabilityRegions",
    "supportedEditions",
    "validationStatus",
    "validationTier",
    "autopilot",
    "controllers",
    "components",
    "safety",
    "sourceBindings",
    "licenses",
    "integrity",
    "knownGaps",
}
VEHICLE_COMPONENT_KEYS = {"status", "sourceIds", "artifacts"}
VEHICLE_COMPONENT_IDS = {"sim", "hardware", "sensors", "validation"}
VEHICLE_COMPONENT_STATUSES = {"included", "external", "unsupported", "planned"}
VEHICLE_ARTIFACT_KEYS = {"path", "sizeBytes", "sha256", "licenseIds"}
VEHICLE_SOURCE_BINDING_KEYS = {"sourceId", "pinSha256"}
VEHICLE_LICENSE_KEYS = {"id", "spdxExpression", "noticePath", "redistribution"}
VEHICLE_CONTROLLER_KEYS = {"vendor", "model", "status", "regions"}
VEHICLE_AUTOPILOT_KEYS = {
    "family",
    "adapterStatus",
    "supportedFirmwareVersions",
}
VEHICLE_SAFETY_KEYS = {
    "capabilityPolicySha256",
    "frontendIsAuthority",
    "hardwareActionsRequireValidatedTier",
    "parameterBounds",
}
VEHICLE_PARAMETER_BOUND_KEYS = {"name", "minimum", "maximum", "unit"}
VEHICLE_INTEGRITY_KEYS = {"canonicalization", "payloadSha256", "signature"}
VEHICLE_SIGNATURE_KEYS = {
    "state",
    "algorithm",
    "keyId",
    "detachedSignatureSha256",
}
VEHICLE_CLASSES = {
    "multicopter-small",
    "multicopter-medium",
    "multicopter-research",
    "fixed-wing",
    "hybrid-vtol",
}
REGIONS = {"cn", "global"}
VEHICLE_VALIDATION_STATUSES = {"validated", "contract-only", "planned"}
VEHICLE_VALIDATION_TIERS = {
    "sim-validated",
    "hardware-validated",
    "contract-only",
    "planned",
}
AUTOPILOT_FAMILIES = {"px4", "ardupilot", "crazyflie"}
ADAPTER_STATUSES = {"integrated-contract", "contract-only", "planned"}
VEHICLE_PACK_REGISTRY_KEYS = {
    "schemaVersion",
    "kind",
    "registryId",
    "registryVersion",
    "auditDate",
    "policy",
    "packs",
}
VEHICLE_PACK_PROFILE_REGISTRY_KEYS = {
    "schemaVersion",
    "kind",
    "registryId",
    "registryVersion",
    "profileId",
    "sourceRegistry",
    "policy",
    "packs",
}
VEHICLE_PACK_PROFILE_SOURCE_KEYS = {
    "path",
    "sha256",
    "registryId",
    "registryVersion",
    "auditDate",
}
VEHICLE_PACK_PROFILE_POLICY_KEYS = {
    "exactPackCount",
    "allowedPackIds",
    "hardwareMetadataAllowed",
    "validatedRequiresSignedReceipt",
    "stockDoesNotImplyCompatibility",
    "parameterBoundsAreProvisionalUntilValidated",
}
VEHICLE_PACK_REGISTRY_POLICY_KEYS = {
    "minimumPackCount",
    "maximumPackCount",
    "goldenCandidateCount",
    "validatedRequiresSignedReceipt",
    "stockDoesNotImplyCompatibility",
    "hardwareActionsRequireValidatedTier",
    "parameterBoundsAreProvisionalUntilValidated",
    "mutableAvailabilityEvidenceRequiresObservedDate",
}
VEHICLE_PACK_REGISTRY_ENTRY_KEYS = {
    "packId",
    "manifestPath",
    "manifestSha256",
    "currentValidationStatus",
    "currentValidationTier",
    "segments",
    "goldenCandidate",
    "productAvailability",
    "supportRegions",
    "availabilityEvidence",
}
VEHICLE_PACK_AVAILABILITY_EVIDENCE_KEYS = {"url", "scope", "observedDate"}
VEHICLE_PACK_SEGMENTS = {
    "simulation-reference",
    "student",
    "teaching",
    "research",
    "racing",
}
VEHICLE_PRODUCT_AVAILABILITY = {
    "simulation-only",
    "listed-available",
    "variant-limited",
    "listed-sold-out",
    "documentation-only",
}
COMPOSITE_INSTALLATION_KEYS = {
    "schemaVersion",
    "kind",
    "inventoryVersion",
    "sourceCommit",
    "commonCoreHash",
    "productDisplayVersion",
    "edition",
    "region",
    "targetArchitecture",
    "components",
    "vehiclePacks",
    "selectedModules",
    "capabilities",
    "resourceEstimate",
    "installability",
    "licenseNotice",
}
COMPOSITE_EDITION_KEYS = {"editionId", "editionVersion", "manifestSha256"}
COMPOSITE_COMPONENT_KEYS = {"desktop", "runtimeBase", "enginePack"}
COMPOSITE_COMPONENT_REF_KEYS = {
    "componentId",
    "version",
    "buildId",
    "sourceCommit",
    "manifestSha256",
    "artifactSha256",
    "artifactBytes",
    "signatureState",
    "validationTier",
}
COMPOSITE_VEHICLE_REF_KEYS = {
    "packId",
    "packVersion",
    "manifestSha256",
    "payloadSha256",
    "artifactSha256",
    "artifactBytes",
    "signatureState",
    "validationTier",
}
COMPOSITE_RESOURCE_KEYS = {
    "downloadBytes",
    "installedBytes",
    "requiresWsl",
    "requiresGazebo",
}
COMPOSITE_INSTALLABILITY_KEYS = {"state", "blockers", "physicalCapabilityStatus"}
COMPOSITE_LICENSE_NOTICE_KEYS = {"path", "sha256", "sizeBytes"}
SIGNATURE_STATES = {"verified", "not-issued"}
RELEASE_PROMOTION_KEYS = {
    "schemaVersion",
    "kind",
    "promotionId",
    "promotionVersion",
    "state",
    "blockers",
    "sourceCommit",
    "commonCoreHash",
    "productDisplayVersion",
    "edition",
    "branchPolicy",
    "artifact",
    "runtimeBase",
    "enginePack",
    "vehiclePacks",
    "capabilities",
    "validationTier",
    "licenseNotice",
    "supersedes",
    "rollback",
}
PROMOTION_EDITION_KEYS = {
    "editionId",
    "editionManifestSha256",
    "compositeManifestSha256",
}
PROMOTION_BRANCH_POLICY_KEYS = {
    "targetBranch",
    "creationState",
    "proposedHeadCommit",
    "headClassification",
    "metadataOnlyChangedPaths",
    "prOnly",
    "forcePushAllowed",
}
PROMOTION_ARTIFACT_KEYS = {
    "fileName",
    "sha256",
    "bytes",
    "authenticodeState",
    "updaterSignatureState",
}
PROMOTION_COMPONENT_KEYS = {"manifestSha256", "artifactSha256", "buildId"}
PROMOTION_VEHICLE_PACK_KEYS = {"packId", "manifestSha256", "artifactSha256"}
PROMOTION_SUPERSEDES_KEYS = {"promotionId", "artifactSha256"}
PROMOTION_ROLLBACK_KEYS = {
    "policy",
    "targetPromotionId",
    "targetArtifactSha256",
}
PROMOTION_BRANCH_CREATION_STATES = {
    "long-lived-product-branch",
    "existing-protected",
}
PROMOTION_METADATA_PREFIXES = (
    "distribution/catalog/",
    "distribution/editions/",
    "distribution/promotions/",
    "distribution/vehicle-packs/",
)


class DistributionContractError(ValueError):
    """Raised when a distribution manifest is incomplete or unsafe."""


def _require_exact_keys(
    value: dict[str, Any],
    required: set[str],
    label: str,
    *,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    actual = set(value)
    missing = sorted(required - actual)
    unsupported = sorted(actual - required - optional)
    if not missing and not unsupported:
        return
    details: list[str] = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if unsupported:
        details.append("unsupported " + ", ".join(unsupported))
    raise DistributionContractError(f"{label} fields are invalid ({'; '.join(details)})")


def _require_nonempty_string(value: Any, label: str, *, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)
    ):
        raise DistributionContractError(f"{label} must be safe non-empty text")
    return value


def _validate_https_url(value: Any, label: str) -> str:
    value = _require_nonempty_string(value, label, maximum=1024)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise DistributionContractError(f"{label} must be a credential-free HTTPS URL") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(character.isspace() for character in value)
        or (port is not None and port <= 0)
    ):
        raise DistributionContractError(f"{label} must be a credential-free HTTPS URL")
    return value


def _validate_text_list(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise DistributionContractError(f"{label} must be a non-empty list")
    for index, item in enumerate(value):
        _require_nonempty_string(item, f"{label}[{index}]")


def _validate_unique_text_list(value: Any, label: str, *, allow_empty: bool = False) -> set[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise DistributionContractError(f"{label} must be {qualifier}")
    for index, item in enumerate(value):
        _require_nonempty_string(item, f"{label}[{index}]")
    if len(value) != len(set(value)):
        raise DistributionContractError(f"{label} must not contain duplicates")
    return set(value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_canonical_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_pin(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise DistributionContractError(f"{label} must be an object")
    _require_exact_keys(value, {"kind", "value", "authority"}, label, optional={"commit"})
    kind = value["kind"]
    if kind not in PIN_KINDS:
        raise DistributionContractError(f"{label}.kind is unsupported")
    _require_nonempty_string(value["value"], f"{label}.value", maximum=256)
    _require_nonempty_string(value["authority"], f"{label}.authority", maximum=256)
    commit = value.get("commit")
    if kind in {"commit", "tag-and-commit"}:
        if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
            raise DistributionContractError(f"{label}.commit must be a full lowercase Git SHA")
    elif commit is not None:
        raise DistributionContractError(f"{label}.commit is not valid for {kind}")


def _validate_license_evidence(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise DistributionContractError(f"{label} must be a non-empty list")
    for index, evidence in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(evidence, dict):
            raise DistributionContractError(f"{item_label} must be an object")
        _require_exact_keys(
            evidence,
            {"url", "scope"},
            item_label,
            optional={"sha256"},
        )
        url = _validate_https_url(evidence["url"], f"{item_label}.url")
        _require_nonempty_string(evidence["scope"], f"{item_label}.scope", maximum=256)
        if urlsplit(url).hostname == "raw.githubusercontent.com":
            sha256 = evidence.get("sha256")
            if not IMMUTABLE_RAW_LICENSE_RE.match(url):
                raise DistributionContractError(
                    f"{item_label}.url must bind raw GitHub evidence to a full commit"
                )
            if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
                raise DistributionContractError(
                    f"{item_label}.sha256 is required for immutable raw evidence"
                )


def validate_upstream_source_inventory(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise DistributionContractError("inventory must be an object")
    _require_exact_keys(document, INVENTORY_KEYS, "inventory")
    if document["schemaVersion"] != 1:
        raise DistributionContractError("inventory.schemaVersion must be 1")
    if document["kind"] != "dronedream-upstream-source-inventory":
        raise DistributionContractError("inventory.kind is unsupported")
    if not isinstance(document["auditDate"], str) or not DATE_RE.fullmatch(document["auditDate"]):
        raise DistributionContractError("inventory.auditDate must be YYYY-MM-DD")
    policy = document["policy"]
    if not isinstance(policy, dict):
        raise DistributionContractError("inventory.policy must be an object")
    _require_exact_keys(policy, POLICY_KEYS, "inventory.policy")
    if any(policy[key] is not True for key in POLICY_KEYS):
        raise DistributionContractError("every inventory policy switch must fail closed")
    sources = document["sources"]
    if not isinstance(sources, list) or not sources:
        raise DistributionContractError("inventory.sources must be a non-empty list")
    seen: set[str] = set()
    for index, source in enumerate(sources):
        label = f"inventory.sources[{index}]"
        if not isinstance(source, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(
            source,
            SOURCE_REQUIRED_KEYS,
            label,
            optional=SOURCE_OPTIONAL_KEYS,
        )
        source_id = source["id"]
        if not isinstance(source_id, str) or not ID_RE.fullmatch(source_id):
            raise DistributionContractError(f"{label}.id is invalid")
        if source_id in seen:
            raise DistributionContractError(f"duplicate source id: {source_id}")
        seen.add(source_id)
        _require_nonempty_string(source["project"], f"{label}.project", maximum=128)
        _validate_https_url(source["officialRepository"], f"{label}.officialRepository")
        if source["integrationStatus"] not in INTEGRATION_STATUSES:
            raise DistributionContractError(f"{label}.integrationStatus is unsupported")
        if source["integrationMode"] not in INTEGRATION_MODES:
            raise DistributionContractError(f"{label}.integrationMode is unsupported")
        if source["distributionMode"] not in DISTRIBUTION_MODES:
            raise DistributionContractError(f"{label}.distributionMode is unsupported")
        if source["copiedIntoRepository"] is not False:
            raise DistributionContractError(f"{label} cannot claim unreviewed copied source")
        _validate_pin(source["pin"], f"{label}.pin")
        audited_commit = source.get("auditedUpstreamCommit")
        if audited_commit is not None and (
            not isinstance(audited_commit, str) or not COMMIT_RE.fullmatch(audited_commit)
        ):
            raise DistributionContractError(
                f"{label}.auditedUpstreamCommit must be a full lowercase Git SHA"
            )
        license_conclusion = source["licenseConclusion"]
        if not isinstance(license_conclusion, str) or not LICENSE_RE.fullmatch(license_conclusion):
            raise DistributionContractError(f"{label}.licenseConclusion is invalid")
        declared = source.get("declaredLicenses")
        if declared is not None:
            _validate_text_list(declared, f"{label}.declaredLicenses")
            if len(declared) != len(set(declared)):
                raise DistributionContractError(f"{label}.declaredLicenses contains duplicates")
        _validate_license_evidence(source["licenseEvidence"], f"{label}.licenseEvidence")
        _validate_text_list(source["noticeObligations"], f"{label}.noticeObligations")
        _validate_text_list(source["validationNotes"], f"{label}.validationNotes")
        tier = source["validationTier"]
        if tier not in VALIDATION_TIERS:
            raise DistributionContractError(f"{label}.validationTier is unsupported")
        if source["integrationMode"] in {
            "external-launch-only",
            "contract-only",
        } and (
            source["distributionMode"] != "not-distributed"
            or source["integrationStatus"] not in {"evaluated", "planned"}
        ):
            raise DistributionContractError(
                f"{label} external or contract-only source cannot be bundled"
            )
        if license_conclusion == "NOASSERTION" and (
            not declared or tier != "legal-review-required"
        ):
            raise DistributionContractError(
                f"{label} NOASSERTION requires declared licenses and legal review"
            )
    return document


def load_upstream_source_inventory(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DistributionContractError(f"unable to read inventory: {path}") from exc
    return validate_upstream_source_inventory(document)


def validate_capability_policy(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise DistributionContractError("capability policy must be an object")
    _require_exact_keys(document, CAPABILITY_POLICY_KEYS, "capability policy")
    if document["schemaVersion"] != 1 or document["kind"] != "dronedream-capability-policy":
        raise DistributionContractError("capability policy identity is unsupported")
    if document["policyId"] != "core-capabilities" or not SEMVER_RE.fullmatch(
        str(document["policyVersion"])
    ):
        raise DistributionContractError("capability policy id or version is invalid")
    if document["defaultDecision"] != "deny" or document["frontendIsAuthority"] is not False:
        raise DistributionContractError("capability policy must deny by default below the frontend")
    llm_boundary = document["llmControlBoundary"]
    if llm_boundary != {
        "generationBoundaryOnly": True,
        "highFrequencyController": "px4-or-vehicle-autopilot",
    }:
        raise DistributionContractError("LLM control boundary cannot enter the flight loop")
    target_context = document["targetContext"]
    expected_target_context = {
        "required": True,
        "kinds": ["simulation", "hitl", "real-hardware"],
        "authorityLayers": ["backend", "runtime", "native"],
        "unknownTargetDecision": "deny",
    }
    if target_context != expected_target_context:
        raise DistributionContractError("target context must be authoritative and fail closed")
    condition_definitions = document["conditionDefinitions"]
    if not isinstance(condition_definitions, list) or not condition_definitions:
        raise DistributionContractError("conditionDefinitions must be a non-empty list")
    conditions: set[str] = set()
    for index, condition in enumerate(condition_definitions):
        label = f"conditionDefinitions[{index}]"
        if not isinstance(condition, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(condition, CONDITION_KEYS, label)
        condition_id = condition["id"]
        if not isinstance(condition_id, str) or not ID_RE.fullmatch(condition_id):
            raise DistributionContractError(f"{label}.id is invalid")
        if condition_id in conditions:
            raise DistributionContractError(f"duplicate condition id: {condition_id}")
        conditions.add(condition_id)
        _require_nonempty_string(condition["description"], f"{label}.description")
        layers = _validate_unique_text_list(condition["enforcedBy"], f"{label}.enforcedBy")
        if not layers <= CONDITION_LAYERS or "frontend" in layers:
            raise DistributionContractError(f"{label} has an unsupported authority layer")
    capabilities = document["capabilities"]
    if not isinstance(capabilities, list) or not capabilities:
        raise DistributionContractError("capabilities must be a non-empty list")
    capability_ids: set[str] = set()
    for index, capability in enumerate(capabilities):
        label = f"capabilities[{index}]"
        if not isinstance(capability, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(capability, CAPABILITY_KEYS, label)
        capability_id = capability["id"]
        if not isinstance(capability_id, str) or not DOTTED_ID_RE.fullmatch(capability_id):
            raise DistributionContractError(f"{label}.id is invalid")
        if capability_id in capability_ids:
            raise DistributionContractError(f"duplicate capability id: {capability_id}")
        capability_ids.add(capability_id)
        if capability["risk"] not in RISK_LEVELS:
            raise DistributionContractError(f"{label}.risk is unsupported")
        targets = _validate_unique_text_list(capability["targetKinds"], f"{label}.targetKinds")
        layers = _validate_unique_text_list(
            capability["requiredEnforcementLayers"],
            f"{label}.requiredEnforcementLayers",
        )
        if not targets <= TARGET_KINDS or not layers <= ENFORCEMENT_LAYERS:
            raise DistributionContractError(f"{label} contains an unsupported target or layer")
        if (
            capability["risk"] == "safety-critical"
            and targets
            & {
                "hitl",
                "real-hardware",
            }
            and layers != ENFORCEMENT_LAYERS
        ):
            raise DistributionContractError(
                f"{label} safety-critical hardware authority requires backend, runtime, and native"
            )
        decisions = capability["decisions"]
        if not isinstance(decisions, dict):
            raise DistributionContractError(f"{label}.decisions must be an object")
        _require_exact_keys(decisions, EDITION_IDS, f"{label}.decisions")
        for edition_id in sorted(EDITION_IDS):
            decision = decisions[edition_id]
            decision_label = f"{label}.decisions.{edition_id}"
            if not isinstance(decision, dict):
                raise DistributionContractError(f"{decision_label} must be an object")
            _require_exact_keys(decision, DECISION_KEYS, decision_label)
            if decision["decision"] not in DECISIONS:
                raise DistributionContractError(f"{decision_label}.decision is unsupported")
            referenced_conditions = _validate_unique_text_list(
                decision["conditions"],
                decision_label + ".conditions",
                allow_empty=True,
            )
            if not referenced_conditions <= conditions:
                raise DistributionContractError(f"{decision_label} references an unknown condition")
            if decision["decision"] == "deny" and referenced_conditions:
                raise DistributionContractError(
                    f"{decision_label} deny must not imply bypass conditions"
                )
            if decision["decision"] == "conditioned" and not referenced_conditions:
                raise DistributionContractError(
                    f"{decision_label} conditioned decision requires conditions"
                )
            _require_nonempty_string(decision["reason"], decision_label + ".reason")
        if capability_id.startswith("hardware.") and decisions["sim"]["decision"] != "deny":
            raise DistributionContractError(f"{capability_id} must be denied by the Sim edition")
        if capability_id.startswith("simulation.") and decisions["field"]["decision"] != "deny":
            raise DistributionContractError(f"{capability_id} must be denied by the Field edition")
        if capability_id == "hardware.hitl.execute" and decisions["field"]["decision"] != "deny":
            raise DistributionContractError(
                "hardware.hitl.execute must be denied by the Field edition"
            )
    required_hardware = {
        "hardware.arm",
        "hardware.flight",
        "hardware.parameter.write",
    }
    if not required_hardware <= capability_ids:
        raise DistributionContractError("core hardware safety capabilities are incomplete")
    return document


def validate_edition_manifest(
    document: Any,
    *,
    policy: dict[str, Any],
    policy_sha256: str,
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise DistributionContractError("edition manifest must be an object")
    _require_exact_keys(document, EDITION_KEYS, "edition manifest")
    if document["schemaVersion"] != 1 or document["kind"] != "dronedream-edition-manifest":
        raise DistributionContractError("edition manifest identity is unsupported")
    edition_id = document["editionId"]
    if edition_id not in EDITION_IDS or not SEMVER_RE.fullmatch(str(document["editionVersion"])):
        raise DistributionContractError("edition id or version is invalid")
    if document["productDisplayVersion"] != "1.0.0":
        raise DistributionContractError("closed beta product display version must remain 1.0.0")
    for field in ("displayName", "description"):
        localized = document[field]
        if not isinstance(localized, dict):
            raise DistributionContractError(f"edition.{field} must be localized")
        _require_exact_keys(localized, {"en", "zh-CN"}, f"edition.{field}")
        for locale in ("en", "zh-CN"):
            _require_nonempty_string(localized[locale], f"edition.{field}.{locale}")
    policy_binding = document["capabilityPolicy"]
    if policy_binding != {
        "policyId": policy["policyId"],
        "policyVersion": policy["policyVersion"],
        "sha256": policy_sha256,
    }:
        raise DistributionContractError("edition capability policy hash or version drifted")
    modules = document["modules"]
    if not isinstance(modules, dict):
        raise DistributionContractError("edition.modules must be an object")
    _require_exact_keys(modules, {"required", "optional", "forbidden"}, "edition.modules")
    required_modules = _validate_unique_text_list(modules["required"], "edition.modules.required")
    optional_modules = _validate_unique_text_list(
        modules["optional"], "edition.modules.optional", allow_empty=True
    )
    forbidden_modules = _validate_unique_text_list(
        modules["forbidden"], "edition.modules.forbidden", allow_empty=True
    )
    if (
        required_modules & optional_modules
        or required_modules & forbidden_modules
        or optional_modules & forbidden_modules
    ):
        raise DistributionContractError("edition module sets must be disjoint")
    capabilities = document["capabilities"]
    if not isinstance(capabilities, dict):
        raise DistributionContractError("edition.capabilities must be an object")
    _require_exact_keys(
        capabilities,
        {"enabledOrConditioned", "forbidden"},
        "edition.capabilities",
    )
    enabled = _validate_unique_text_list(
        capabilities["enabledOrConditioned"],
        "edition.capabilities.enabledOrConditioned",
    )
    forbidden = _validate_unique_text_list(
        capabilities["forbidden"],
        "edition.capabilities.forbidden",
        allow_empty=True,
    )
    if enabled & forbidden:
        raise DistributionContractError("edition capability sets must be disjoint")
    expected_enabled = {
        capability["id"]
        for capability in policy["capabilities"]
        if capability["decisions"][edition_id]["decision"] != "deny"
    }
    expected_forbidden = {
        capability["id"]
        for capability in policy["capabilities"]
        if capability["decisions"][edition_id]["decision"] == "deny"
    }
    if enabled != expected_enabled or forbidden != expected_forbidden:
        raise DistributionContractError("edition capability lists drifted from policy decisions")
    source_policy = document["sourcePolicy"]
    expected_product_branch = EDITION_BRANCHES[edition_id]
    if source_policy != {
        "developmentBranch": expected_product_branch,
        "integrationBranch": "main",
        "editionSourceDivergenceAllowed": False,
        "hotfixMustReturnToCore": True,
        "commonCoreHashRequired": True,
    }:
        raise DistributionContractError("edition source policy permits code divergence")
    release_channel = document["releaseChannel"]
    expected_branch = expected_product_branch
    if not isinstance(release_channel, dict):
        raise DistributionContractError("edition.releaseChannel must be an object")
    _require_exact_keys(
        release_channel,
        {"branch", "creationState", "promotionManifestRequired", "forcePushAllowed"},
        "edition.releaseChannel",
    )
    if (
        release_channel["branch"] != expected_branch
        or release_channel["creationState"] != "long-lived-product-branch"
        or release_channel["promotionManifestRequired"] is not True
        or release_channel["forcePushAllowed"] is not False
    ):
        raise DistributionContractError("edition release channel is unsafe")
    runtime_profile = document["runtimeProfile"]
    qualification = document["qualification"]
    if not isinstance(runtime_profile, dict) or not isinstance(qualification, dict):
        raise DistributionContractError("edition runtime and qualification policies are required")
    if qualification.get("receiptCompatibilityFailClosed") is not True:
        raise DistributionContractError("qualification receipt compatibility must fail closed")
    if edition_id == "sim" and (
        "hardware-bridge" not in forbidden_modules
        or not runtime_profile.get("includesLargeSimulator")
    ):
        raise DistributionContractError("Sim must include simulation and forbid hardware")
    if edition_id == "field" and (
        "runtime-simulation" not in forbidden_modules
        or runtime_profile.get("includesLargeSimulator") is not False
        or qualification.get("mayConsumeTrustedReceipt") is not True
    ):
        raise DistributionContractError(
            "Field must remain lightweight and consume trusted qualification"
        )
    if edition_id in {"lab", "field"} and (
        document["implementationStatus"] != "contract-only"
        or document["validationTier"] != "contract-only"
    ):
        raise DistributionContractError(
            "hardware editions cannot claim implementation before E5 validation"
        )
    _validate_text_list(document["knownGaps"], "edition.knownGaps")
    return document


def _load_json_document(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DistributionContractError(f"unable to read {label}: {path}") from exc
    if not isinstance(document, dict):
        raise DistributionContractError(f"{label} must be an object")
    return document


def load_capability_policy(path: Path) -> dict[str, Any]:
    return validate_capability_policy(_load_json_document(path, "capability policy"))


def load_edition_manifests(paths: list[Path], *, policy_path: Path) -> dict[str, dict[str, Any]]:
    policy = load_capability_policy(policy_path)
    policy_sha256 = sha256_file(policy_path)
    editions: dict[str, dict[str, Any]] = {}
    for path in paths:
        document = validate_edition_manifest(
            _load_json_document(path, "edition manifest"),
            policy=policy,
            policy_sha256=policy_sha256,
        )
        edition_id = document["editionId"]
        if edition_id in editions:
            raise DistributionContractError(f"duplicate edition id: {edition_id}")
        editions[edition_id] = document
    if set(editions) != EDITION_IDS:
        raise DistributionContractError(
            "exactly sim, lab, field, and autonomy editions are required"
        )
    return editions


def validate_vehicle_pack_manifest(
    document: Any,
    *,
    upstream_inventory: dict[str, Any],
    capability_policy_sha256: str,
    verified_signature_payload_sha256: str | None = None,
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise DistributionContractError("Vehicle Pack manifest must be an object")
    _require_exact_keys(document, VEHICLE_PACK_KEYS, "Vehicle Pack manifest")
    if document["schemaVersion"] != 1 or document["kind"] != "dronedream-vehicle-pack":
        raise DistributionContractError("Vehicle Pack identity is unsupported")
    if not isinstance(document["packId"], str) or not ID_RE.fullmatch(document["packId"]):
        raise DistributionContractError("Vehicle Pack id is invalid")
    if not SEMVER_RE.fullmatch(str(document["packVersion"])):
        raise DistributionContractError("Vehicle Pack version is invalid")
    display_name = document["displayName"]
    if not isinstance(display_name, dict):
        raise DistributionContractError("Vehicle Pack displayName must be localized")
    _require_exact_keys(display_name, {"en", "zh-CN"}, "Vehicle Pack displayName")
    for locale in ("en", "zh-CN"):
        _require_nonempty_string(display_name[locale], f"Vehicle Pack displayName.{locale}")
    _require_nonempty_string(document["manufacturer"], "Vehicle Pack manufacturer")
    if document["vehicleClass"] not in VEHICLE_CLASSES:
        raise DistributionContractError("Vehicle Pack class is unsupported")
    regions = _validate_unique_text_list(
        document["availabilityRegions"], "Vehicle Pack availabilityRegions"
    )
    editions = _validate_unique_text_list(
        document["supportedEditions"], "Vehicle Pack supportedEditions"
    )
    if not regions <= REGIONS or not editions <= EDITION_IDS:
        raise DistributionContractError("Vehicle Pack region or edition is unsupported")
    validation_status = document["validationStatus"]
    validation_tier = document["validationTier"]
    if (
        validation_status not in VEHICLE_VALIDATION_STATUSES
        or validation_tier not in VEHICLE_VALIDATION_TIERS
    ):
        raise DistributionContractError("Vehicle Pack validation claim is unsupported")
    expected_tier_by_status = {
        "contract-only": "contract-only",
        "planned": "planned",
    }
    if validation_status in expected_tier_by_status and (
        validation_tier != expected_tier_by_status[validation_status]
    ):
        raise DistributionContractError("Vehicle Pack validation status and tier disagree")
    if validation_status == "validated" and validation_tier not in {
        "sim-validated",
        "hardware-validated",
    }:
        raise DistributionContractError("validated Vehicle Pack requires a validated tier")

    autopilot = document["autopilot"]
    if not isinstance(autopilot, dict):
        raise DistributionContractError("Vehicle Pack autopilot must be an object")
    _require_exact_keys(autopilot, VEHICLE_AUTOPILOT_KEYS, "Vehicle Pack autopilot")
    if (
        autopilot["family"] not in AUTOPILOT_FAMILIES
        or autopilot["adapterStatus"] not in ADAPTER_STATUSES
    ):
        raise DistributionContractError("Vehicle Pack autopilot contract is unsupported")
    _validate_unique_text_list(
        autopilot["supportedFirmwareVersions"],
        "Vehicle Pack supportedFirmwareVersions",
    )

    controllers = document["controllers"]
    if not isinstance(controllers, list):
        raise DistributionContractError("Vehicle Pack controllers must be a list")
    controller_keys: set[tuple[str, str]] = set()
    for index, controller in enumerate(controllers):
        label = f"Vehicle Pack controllers[{index}]"
        if not isinstance(controller, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(controller, VEHICLE_CONTROLLER_KEYS, label)
        vendor = _require_nonempty_string(controller["vendor"], f"{label}.vendor")
        model = _require_nonempty_string(controller["model"], f"{label}.model")
        key = (vendor.casefold(), model.casefold())
        if key in controller_keys:
            raise DistributionContractError(f"{label} duplicates a controller")
        controller_keys.add(key)
        if controller["status"] not in VEHICLE_VALIDATION_STATUSES:
            raise DistributionContractError(f"{label}.status is unsupported")
        controller_regions = _validate_unique_text_list(controller["regions"], f"{label}.regions")
        if not controller_regions <= regions:
            raise DistributionContractError(f"{label}.regions exceed pack availability")

    upstream_sources = {source["id"]: source for source in upstream_inventory["sources"]}
    known_source_ids = set(upstream_sources)
    source_bindings = document["sourceBindings"]
    if not isinstance(source_bindings, list) or not source_bindings:
        raise DistributionContractError("Vehicle Pack sourceBindings must be non-empty")
    bound_source_ids: set[str] = set()
    for index, binding in enumerate(source_bindings):
        label = f"Vehicle Pack sourceBindings[{index}]"
        if not isinstance(binding, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(binding, VEHICLE_SOURCE_BINDING_KEYS, label)
        source_id = binding["sourceId"]
        if source_id not in known_source_ids or source_id in bound_source_ids:
            raise DistributionContractError(f"{label} is unknown or duplicated")
        bound_source_ids.add(source_id)
        if not isinstance(binding["pinSha256"], str) or not SHA256_RE.fullmatch(
            binding["pinSha256"]
        ):
            raise DistributionContractError(f"{label}.pinSha256 is invalid")
        expected_pin_sha256 = sha256_canonical_json(upstream_sources[source_id]["pin"])
        if binding["pinSha256"] != expected_pin_sha256:
            raise DistributionContractError(f"{label}.pinSha256 drifted from upstream inventory")

    licenses = document["licenses"]
    if not isinstance(licenses, list) or not licenses:
        raise DistributionContractError("Vehicle Pack licenses must be non-empty")
    license_ids: set[str] = set()
    for index, license_binding in enumerate(licenses):
        label = f"Vehicle Pack licenses[{index}]"
        if not isinstance(license_binding, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(license_binding, VEHICLE_LICENSE_KEYS, label)
        license_id = license_binding["id"]
        if not isinstance(license_id, str) or not ID_RE.fullmatch(license_id):
            raise DistributionContractError(f"{label}.id is invalid")
        if license_id in license_ids:
            raise DistributionContractError(f"duplicate Vehicle Pack license: {license_id}")
        license_ids.add(license_id)
        _require_nonempty_string(license_binding["spdxExpression"], f"{label}.spdxExpression")
        notice_path = license_binding["noticePath"]
        if not isinstance(notice_path, str) or not SAFE_RELATIVE_PATH_RE.fullmatch(notice_path):
            raise DistributionContractError(f"{label}.noticePath is unsafe")
        if license_binding["redistribution"] not in {
            "bundled",
            "external-launch",
            "not-distributed",
        }:
            raise DistributionContractError(f"{label}.redistribution is unsupported")

    components = document["components"]
    if not isinstance(components, dict):
        raise DistributionContractError("Vehicle Pack components must be an object")
    _require_exact_keys(components, VEHICLE_COMPONENT_IDS, "Vehicle Pack components")
    artifact_count = 0
    validation_artifact_count = 0
    for component_id in sorted(VEHICLE_COMPONENT_IDS):
        component = components[component_id]
        label = f"Vehicle Pack components.{component_id}"
        if not isinstance(component, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(component, VEHICLE_COMPONENT_KEYS, label)
        if component["status"] not in VEHICLE_COMPONENT_STATUSES:
            raise DistributionContractError(f"{label}.status is unsupported")
        component_sources = _validate_unique_text_list(
            component["sourceIds"], f"{label}.sourceIds", allow_empty=True
        )
        if not component_sources <= bound_source_ids:
            raise DistributionContractError(f"{label} references an unbound source")
        artifacts = component["artifacts"]
        if not isinstance(artifacts, list):
            raise DistributionContractError(f"{label}.artifacts must be a list")
        seen_paths: set[str] = set()
        for artifact_index, artifact in enumerate(artifacts):
            artifact_label = f"{label}.artifacts[{artifact_index}]"
            if not isinstance(artifact, dict):
                raise DistributionContractError(f"{artifact_label} must be an object")
            _require_exact_keys(artifact, VEHICLE_ARTIFACT_KEYS, artifact_label)
            artifact_path = artifact["path"]
            if (
                not isinstance(artifact_path, str)
                or not SAFE_RELATIVE_PATH_RE.fullmatch(artifact_path)
                or artifact_path in seen_paths
            ):
                raise DistributionContractError(f"{artifact_label}.path is unsafe or duplicated")
            seen_paths.add(artifact_path)
            if not isinstance(artifact["sizeBytes"], int) or artifact["sizeBytes"] < 0:
                raise DistributionContractError(f"{artifact_label}.sizeBytes is invalid")
            if not isinstance(artifact["sha256"], str) or not SHA256_RE.fullmatch(
                artifact["sha256"]
            ):
                raise DistributionContractError(f"{artifact_label}.sha256 is invalid")
            artifact_license_ids = _validate_unique_text_list(
                artifact["licenseIds"], f"{artifact_label}.licenseIds"
            )
            if not artifact_license_ids <= license_ids:
                raise DistributionContractError(f"{artifact_label} references an unknown license")
            artifact_count += 1
            if component_id == "validation":
                validation_artifact_count += 1

    safety = document["safety"]
    if not isinstance(safety, dict):
        raise DistributionContractError("Vehicle Pack safety must be an object")
    _require_exact_keys(safety, VEHICLE_SAFETY_KEYS, "Vehicle Pack safety")
    if (
        safety["capabilityPolicySha256"] != capability_policy_sha256
        or safety["frontendIsAuthority"] is not False
        or safety["hardwareActionsRequireValidatedTier"] is not True
    ):
        raise DistributionContractError("Vehicle Pack safety authority drifted")
    bounds = safety["parameterBounds"]
    if not isinstance(bounds, list) or not bounds:
        raise DistributionContractError("Vehicle Pack parameter bounds must be non-empty")
    bound_names: set[str] = set()
    for index, bound in enumerate(bounds):
        label = f"Vehicle Pack safety.parameterBounds[{index}]"
        if not isinstance(bound, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(bound, VEHICLE_PARAMETER_BOUND_KEYS, label)
        name = bound["name"]
        if (
            not isinstance(name, str)
            or not PARAMETER_NAME_RE.fullmatch(name)
            or name in bound_names
        ):
            raise DistributionContractError(f"{label}.name is invalid or duplicated")
        bound_names.add(name)
        if (
            not isinstance(bound["minimum"], (int, float))
            or isinstance(bound["minimum"], bool)
            or not isinstance(bound["maximum"], (int, float))
            or isinstance(bound["maximum"], bool)
            or bound["minimum"] > bound["maximum"]
        ):
            raise DistributionContractError(f"{label} has invalid bounds")
        _require_nonempty_string(bound["unit"], f"{label}.unit")

    integrity = document["integrity"]
    if not isinstance(integrity, dict):
        raise DistributionContractError("Vehicle Pack integrity must be an object")
    _require_exact_keys(integrity, VEHICLE_INTEGRITY_KEYS, "Vehicle Pack integrity")
    if integrity["canonicalization"] != "RFC8785-JCS":
        raise DistributionContractError("Vehicle Pack canonicalization is unsupported")
    if not isinstance(integrity["payloadSha256"], str) or not SHA256_RE.fullmatch(
        integrity["payloadSha256"]
    ):
        raise DistributionContractError("Vehicle Pack payload hash is invalid")
    signature = integrity["signature"]
    if not isinstance(signature, dict):
        raise DistributionContractError("Vehicle Pack signature must be an object")
    _require_exact_keys(signature, VEHICLE_SIGNATURE_KEYS, "Vehicle Pack signature")
    if signature["algorithm"] != "Ed25519" or signature["state"] not in {
        "verified",
        "not-issued",
    }:
        raise DistributionContractError("Vehicle Pack signature contract is unsupported")
    if signature["state"] == "verified":
        if (
            not isinstance(signature["keyId"], str)
            or not ED25519_KEY_ID_RE.fullmatch(signature["keyId"])
            or not isinstance(signature["detachedSignatureSha256"], str)
            or not SHA256_RE.fullmatch(signature["detachedSignatureSha256"])
        ):
            raise DistributionContractError("verified Vehicle Pack signature is incomplete")
    elif signature["keyId"] is not None or signature["detachedSignatureSha256"] is not None:
        raise DistributionContractError("unissued Vehicle Pack signature must not imply trust")
    if validation_status == "validated" and (
        signature["state"] != "verified" or artifact_count == 0 or validation_artifact_count == 0
    ):
        raise DistributionContractError(
            "validated Vehicle Pack requires signed payload and validation artifacts"
        )
    if validation_status == "validated" and (
        verified_signature_payload_sha256 != integrity["payloadSha256"]
    ):
        raise DistributionContractError(
            "validated Vehicle Pack requires external cryptographic signature verification"
        )
    if validation_tier == "sim-validated" and (
        not editions & {"sim", "lab"} or components["sim"]["status"] not in {"included", "external"}
    ):
        raise DistributionContractError(
            "sim-validated Vehicle Pack requires a supported simulation edition and component"
        )
    if validation_tier == "hardware-validated" and (
        not editions & {"lab", "field"}
        or components["hardware"]["status"] != "included"
        or not controllers
    ):
        raise DistributionContractError(
            "hardware-validated Vehicle Pack requires hardware artifacts and controllers"
        )
    _validate_text_list(document["knownGaps"], "Vehicle Pack knownGaps")
    return document


def load_vehicle_pack_manifests(
    paths: list[Path],
    *,
    upstream_inventory_path: Path,
    capability_policy_path: Path,
) -> dict[str, dict[str, Any]]:
    upstream_inventory = load_upstream_source_inventory(upstream_inventory_path)
    capability_policy = load_capability_policy(capability_policy_path)
    del capability_policy
    capability_policy_sha256 = sha256_file(capability_policy_path)
    packs: dict[str, dict[str, Any]] = {}
    for path in paths:
        document = validate_vehicle_pack_manifest(
            _load_json_document(path, "Vehicle Pack manifest"),
            upstream_inventory=upstream_inventory,
            capability_policy_sha256=capability_policy_sha256,
        )
        pack_id = document["packId"]
        if pack_id in packs:
            raise DistributionContractError(f"duplicate Vehicle Pack id: {pack_id}")
        packs[pack_id] = document
    if not packs:
        raise DistributionContractError("at least one Vehicle Pack manifest is required")
    return packs


def validate_vehicle_pack_registry(
    document: Any,
    *,
    vehicle_packs_by_path: dict[str, dict[str, Any]],
    vehicle_pack_manifest_sha256: dict[str, str],
    source_registry_document: dict[str, Any] | None = None,
    source_registry_sha256: str | None = None,
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise DistributionContractError("Vehicle Pack registry must be an object")
    if document.get("kind") == "dronedream-vehicle-pack-profile-registry":
        return validate_vehicle_pack_profile_registry(
            document,
            vehicle_packs_by_path=vehicle_packs_by_path,
            vehicle_pack_manifest_sha256=vehicle_pack_manifest_sha256,
            source_registry_document=source_registry_document,
            source_registry_sha256=source_registry_sha256,
        )
    _require_exact_keys(document, VEHICLE_PACK_REGISTRY_KEYS, "Vehicle Pack registry")
    if document["schemaVersion"] != 1 or document["kind"] != "dronedream-vehicle-pack-registry":
        raise DistributionContractError("Vehicle Pack registry identity is unsupported")
    if not isinstance(document["registryId"], str) or not ID_RE.fullmatch(document["registryId"]):
        raise DistributionContractError("Vehicle Pack registry id is invalid")
    if not SEMVER_RE.fullmatch(str(document["registryVersion"])):
        raise DistributionContractError("Vehicle Pack registry version is invalid")
    audit_date = document["auditDate"]
    if not isinstance(audit_date, str) or not DATE_RE.fullmatch(audit_date):
        raise DistributionContractError("Vehicle Pack registry auditDate must be YYYY-MM-DD")

    policy = document["policy"]
    if not isinstance(policy, dict):
        raise DistributionContractError("Vehicle Pack registry policy must be an object")
    _require_exact_keys(
        policy,
        VEHICLE_PACK_REGISTRY_POLICY_KEYS,
        "Vehicle Pack registry policy",
    )
    if (
        policy["minimumPackCount"] != 6
        or policy["maximumPackCount"] != 8
        or policy["goldenCandidateCount"] != 3
    ):
        raise DistributionContractError("Vehicle Pack registry count policy drifted")
    boolean_policy_keys = VEHICLE_PACK_REGISTRY_POLICY_KEYS - {
        "minimumPackCount",
        "maximumPackCount",
        "goldenCandidateCount",
    }
    if any(policy[key] is not True for key in boolean_policy_keys):
        raise DistributionContractError("Vehicle Pack registry safety policy must fail closed")

    entries = document["packs"]
    if not isinstance(entries, list) or not (
        policy["minimumPackCount"] <= len(entries) <= policy["maximumPackCount"]
    ):
        raise DistributionContractError("Vehicle Pack registry must contain 6 to 8 packs")
    expected_paths = set(vehicle_packs_by_path)
    if set(vehicle_pack_manifest_sha256) != expected_paths:
        raise DistributionContractError("Vehicle Pack registry verifier inputs disagree")

    seen_pack_ids: set[str] = set()
    seen_paths: set[str] = set()
    golden_count = 0
    for index, entry in enumerate(entries):
        label = f"Vehicle Pack registry packs[{index}]"
        if not isinstance(entry, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(entry, VEHICLE_PACK_REGISTRY_ENTRY_KEYS, label)
        pack_id = entry["packId"]
        if not isinstance(pack_id, str) or not ID_RE.fullmatch(pack_id) or pack_id in seen_pack_ids:
            raise DistributionContractError(f"{label}.packId is invalid or duplicated")
        seen_pack_ids.add(pack_id)

        manifest_path = entry["manifestPath"]
        if (
            not isinstance(manifest_path, str)
            or not SAFE_RELATIVE_PATH_RE.fullmatch(manifest_path)
            or not manifest_path.startswith("distribution/vehicle-packs/")
            or not manifest_path.endswith(".json")
            or manifest_path.endswith("/registry.v1.json")
            or manifest_path in seen_paths
        ):
            raise DistributionContractError(f"{label}.manifestPath is unsafe or duplicated")
        seen_paths.add(manifest_path)
        pack = vehicle_packs_by_path.get(manifest_path)
        if pack is None:
            raise DistributionContractError(f"{label}.manifestPath was not independently supplied")
        if pack["packId"] != pack_id:
            raise DistributionContractError(f"{label}.packId drifted from its manifest")

        manifest_sha256 = entry["manifestSha256"]
        if (
            not isinstance(manifest_sha256, str)
            or not SHA256_RE.fullmatch(manifest_sha256)
            or manifest_sha256 != vehicle_pack_manifest_sha256[manifest_path]
        ):
            raise DistributionContractError(f"{label}.manifestSha256 drifted from file bytes")
        if entry["currentValidationStatus"] != pack["validationStatus"]:
            raise DistributionContractError(
                f"{label}.currentValidationStatus drifted from manifest"
            )
        if entry["currentValidationTier"] != pack["validationTier"]:
            raise DistributionContractError(f"{label}.currentValidationTier drifted from manifest")

        segments = _validate_unique_text_list(entry["segments"], f"{label}.segments")
        if not segments <= VEHICLE_PACK_SEGMENTS:
            raise DistributionContractError(f"{label}.segments contains an unsupported segment")
        if not isinstance(entry["goldenCandidate"], bool):
            raise DistributionContractError(f"{label}.goldenCandidate must be boolean")
        if entry["goldenCandidate"]:
            golden_count += 1
            if (
                pack["validationStatus"] == "planned"
                or pack["autopilot"]["family"] != "px4"
                or pack["autopilot"]["adapterStatus"] == "planned"
            ):
                raise DistributionContractError(
                    f"{label} cannot be a golden candidate before its PX4 contract exists"
                )
        if entry["productAvailability"] not in VEHICLE_PRODUCT_AVAILABILITY:
            raise DistributionContractError(f"{label}.productAvailability is unsupported")
        regions = _validate_unique_text_list(entry["supportRegions"], f"{label}.supportRegions")
        if regions != set(pack["availabilityRegions"]):
            raise DistributionContractError(f"{label}.supportRegions drifted from manifest")

        evidence_items = entry["availabilityEvidence"]
        if not isinstance(evidence_items, list) or not evidence_items:
            raise DistributionContractError(f"{label}.availabilityEvidence must be non-empty")
        evidence_urls: set[str] = set()
        for evidence_index, evidence in enumerate(evidence_items):
            evidence_label = f"{label}.availabilityEvidence[{evidence_index}]"
            if not isinstance(evidence, dict):
                raise DistributionContractError(f"{evidence_label} must be an object")
            _require_exact_keys(
                evidence,
                VEHICLE_PACK_AVAILABILITY_EVIDENCE_KEYS,
                evidence_label,
            )
            url = _validate_https_url(evidence["url"], f"{evidence_label}.url")
            if url in evidence_urls:
                raise DistributionContractError(f"{evidence_label}.url is duplicated")
            evidence_urls.add(url)
            _require_nonempty_string(evidence["scope"], f"{evidence_label}.scope")
            observed_date = evidence["observedDate"]
            if (
                not isinstance(observed_date, str)
                or not DATE_RE.fullmatch(observed_date)
                or observed_date > audit_date
            ):
                raise DistributionContractError(
                    f"{evidence_label}.observedDate must not follow registry auditDate"
                )

        if entry["productAvailability"] == "simulation-only" and (
            pack["components"]["hardware"]["status"] != "unsupported" or pack["controllers"]
        ):
            raise DistributionContractError(
                f"{label}.productAvailability disagrees with physical components"
            )

    if seen_paths != expected_paths:
        raise DistributionContractError(
            "Vehicle Pack registry does not exactly cover supplied manifests"
        )
    if golden_count != policy["goldenCandidateCount"]:
        raise DistributionContractError("Vehicle Pack registry golden candidate count drifted")
    return document


def validate_vehicle_pack_profile_registry(
    document: Any,
    *,
    vehicle_packs_by_path: dict[str, dict[str, Any]],
    vehicle_pack_manifest_sha256: dict[str, str],
    source_registry_document: dict[str, Any] | None = None,
    source_registry_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate the immutable X500-only catalog projection used by Sim payloads."""

    if not isinstance(document, dict):
        raise DistributionContractError("Vehicle Pack profile registry must be an object")
    _require_exact_keys(
        document,
        VEHICLE_PACK_PROFILE_REGISTRY_KEYS,
        "Vehicle Pack profile registry",
    )
    if (
        document["schemaVersion"] != 1
        or document["kind"] != "dronedream-vehicle-pack-profile-registry"
        or document["registryId"] != "sim-only-x500"
        or document["registryVersion"] != "1.0.0"
        or document["profileId"] != "sim-only"
    ):
        raise DistributionContractError("Vehicle Pack profile registry identity is unsupported")

    source = document["sourceRegistry"]
    if not isinstance(source, dict):
        raise DistributionContractError("Vehicle Pack profile source registry must be an object")
    _require_exact_keys(source, VEHICLE_PACK_PROFILE_SOURCE_KEYS, "profile source registry")
    if (
        source["path"] != "distribution/vehicle-packs/registry.v1.json"
        or source["registryId"] != "initial-vehicle-packs"
        or source["registryVersion"] != "1.0.0"
        or not isinstance(source["sha256"], str)
        or not SHA256_RE.fullmatch(source["sha256"])
        or not isinstance(source["auditDate"], str)
        or not DATE_RE.fullmatch(source["auditDate"])
    ):
        raise DistributionContractError("Vehicle Pack profile source identity drifted")

    policy = document["policy"]
    if not isinstance(policy, dict):
        raise DistributionContractError("Vehicle Pack profile policy must be an object")
    _require_exact_keys(policy, VEHICLE_PACK_PROFILE_POLICY_KEYS, "Vehicle Pack profile policy")
    if policy != {
        "exactPackCount": 1,
        "allowedPackIds": ["px4-gazebo-x500-reference"],
        "hardwareMetadataAllowed": False,
        "validatedRequiresSignedReceipt": True,
        "stockDoesNotImplyCompatibility": True,
        "parameterBoundsAreProvisionalUntilValidated": True,
    }:
        raise DistributionContractError("Vehicle Pack profile policy drifted")

    expected_path = "distribution/vehicle-packs/px4-gazebo-x500-reference.v1.json"
    if set(vehicle_packs_by_path) != {expected_path} or set(vehicle_pack_manifest_sha256) != {
        expected_path
    }:
        raise DistributionContractError(
            "Sim-only Vehicle Pack registry requires exactly the X500 reference manifest"
        )
    entries = document["packs"]
    if not isinstance(entries, list) or len(entries) != 1:
        raise DistributionContractError("Vehicle Pack profile registry must contain one pack")
    entry = entries[0]
    if not isinstance(entry, dict):
        raise DistributionContractError("Vehicle Pack profile registry entry must be an object")
    _require_exact_keys(entry, VEHICLE_PACK_REGISTRY_ENTRY_KEYS, "profile registry entry")
    pack = vehicle_packs_by_path[expected_path]
    if entry["packId"] != "px4-gazebo-x500-reference" or pack["packId"] != entry["packId"]:
        raise DistributionContractError("Vehicle Pack profile pack identity drifted")
    if entry["manifestPath"] != expected_path:
        raise DistributionContractError("Vehicle Pack profile manifest path drifted")
    if entry["manifestSha256"] != vehicle_pack_manifest_sha256[
        expected_path
    ] or not SHA256_RE.fullmatch(str(entry["manifestSha256"])):
        raise DistributionContractError("Vehicle Pack profile manifest hash drifted")
    if (
        entry["currentValidationStatus"] != pack["validationStatus"]
        or entry["currentValidationTier"] != pack["validationTier"]
    ):
        raise DistributionContractError("Vehicle Pack profile validation claim drifted")
    if entry["productAvailability"] != "simulation-only":
        raise DistributionContractError("Vehicle Pack profile must remain simulation-only")
    if pack["components"]["hardware"]["status"] != "unsupported" or pack["controllers"]:
        raise DistributionContractError("Vehicle Pack profile contains physical hardware metadata")
    segments = _validate_unique_text_list(entry["segments"], "profile registry entry.segments")
    if not segments or not segments <= VEHICLE_PACK_SEGMENTS:
        raise DistributionContractError("Vehicle Pack profile segments are unsupported")
    if not isinstance(entry["goldenCandidate"], bool):
        raise DistributionContractError("Vehicle Pack profile goldenCandidate must be boolean")
    regions = _validate_unique_text_list(
        entry["supportRegions"], "profile registry entry.supportRegions"
    )
    if regions != set(pack["availabilityRegions"]):
        raise DistributionContractError("Vehicle Pack profile regions drifted")
    evidence_items = entry["availabilityEvidence"]
    if not isinstance(evidence_items, list) or not evidence_items:
        raise DistributionContractError("Vehicle Pack profile availability evidence is required")
    for index, evidence in enumerate(evidence_items):
        label = f"profile registry entry.availabilityEvidence[{index}]"
        if not isinstance(evidence, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(evidence, VEHICLE_PACK_AVAILABILITY_EVIDENCE_KEYS, label)
        _validate_https_url(evidence["url"], f"{label}.url")
        _require_nonempty_string(evidence["scope"], f"{label}.scope")
        observed_date = evidence["observedDate"]
        if (
            not isinstance(observed_date, str)
            or not DATE_RE.fullmatch(observed_date)
            or observed_date > source["auditDate"]
        ):
            raise DistributionContractError(
                f"{label}.observedDate must not follow source registry auditDate"
            )

    if (source_registry_document is None) != (source_registry_sha256 is None):
        raise DistributionContractError("Vehicle Pack source registry binding is incomplete")
    if source_registry_document is not None and source_registry_sha256 is not None:
        if source_registry_sha256 != source["sha256"]:
            raise DistributionContractError("Vehicle Pack source registry hash drifted")
        if (
            source_registry_document.get("kind") != "dronedream-vehicle-pack-registry"
            or source_registry_document.get("registryId") != source["registryId"]
            or source_registry_document.get("registryVersion") != source["registryVersion"]
            or source_registry_document.get("auditDate") != source["auditDate"]
        ):
            raise DistributionContractError("Vehicle Pack source registry identity drifted")
        source_entries = source_registry_document.get("packs")
        if not isinstance(source_entries, list):
            raise DistributionContractError("Vehicle Pack source registry entries are invalid")
        matching = [item for item in source_entries if item.get("packId") == entry["packId"]]
        if matching != [entry]:
            raise DistributionContractError("Vehicle Pack profile projection drifted from source")
    return document


def load_vehicle_pack_registry(
    path: Path,
    *,
    vehicle_pack_paths: list[Path],
    upstream_inventory_path: Path,
    capability_policy_path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    packs_by_id = load_vehicle_pack_manifests(
        vehicle_pack_paths,
        upstream_inventory_path=upstream_inventory_path,
        capability_policy_path=capability_policy_path,
    )
    packs_by_path: dict[str, dict[str, Any]] = {}
    manifest_shas: dict[str, str] = {}
    resolved_root = repository_root.resolve()
    for vehicle_pack_path in vehicle_pack_paths:
        try:
            relative_path = vehicle_pack_path.resolve().relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise DistributionContractError(
                f"Vehicle Pack manifest is outside repository root: {vehicle_pack_path}"
            ) from exc
        raw_document = _load_json_document(vehicle_pack_path, "Vehicle Pack manifest")
        pack_id = raw_document.get("packId")
        if not isinstance(pack_id, str):
            raise DistributionContractError("Vehicle Pack registry input has no valid pack id")
        pack = packs_by_id.get(pack_id)
        if pack is None or relative_path in packs_by_path:
            raise DistributionContractError(
                "Vehicle Pack registry input path is duplicated or invalid"
            )
        packs_by_path[relative_path] = pack
        manifest_shas[relative_path] = sha256_file(vehicle_pack_path)
    return validate_vehicle_pack_registry(
        _load_json_document(path, "Vehicle Pack registry"),
        vehicle_packs_by_path=packs_by_path,
        vehicle_pack_manifest_sha256=manifest_shas,
    )


def _validate_composite_component_ref(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DistributionContractError(f"{label} must be an object")
    _require_exact_keys(value, COMPOSITE_COMPONENT_REF_KEYS, label)
    for field in ("componentId", "version", "buildId", "validationTier"):
        _require_nonempty_string(value[field], f"{label}.{field}")
    if not isinstance(value["sourceCommit"], str) or not COMMIT_RE.fullmatch(value["sourceCommit"]):
        raise DistributionContractError(f"{label}.sourceCommit is invalid")
    for field in ("manifestSha256", "artifactSha256"):
        if not isinstance(value[field], str) or not SHA256_RE.fullmatch(value[field]):
            raise DistributionContractError(f"{label}.{field} is invalid")
    if not isinstance(value["artifactBytes"], int) or value["artifactBytes"] < 0:
        raise DistributionContractError(f"{label}.artifactBytes is invalid")
    if value["signatureState"] not in SIGNATURE_STATES:
        raise DistributionContractError(f"{label}.signatureState is unsupported")
    return value


def validate_composite_installation_manifest(
    document: Any,
    *,
    edition: dict[str, Any],
    edition_manifest_sha256: str,
    vehicle_packs: dict[str, dict[str, Any]],
    vehicle_pack_manifest_sha256: dict[str, str],
    expected_source_commit: str | None = None,
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise DistributionContractError("composite installation manifest must be an object")
    _require_exact_keys(
        document,
        COMPOSITE_INSTALLATION_KEYS,
        "composite installation manifest",
    )
    if (
        document["schemaVersion"] != 1
        or document["kind"] != "dronedream-composite-installation"
        or not SEMVER_RE.fullmatch(str(document["inventoryVersion"]))
    ):
        raise DistributionContractError("composite installation identity is unsupported")
    source_commit = document["sourceCommit"]
    if not isinstance(source_commit, str) or not COMMIT_RE.fullmatch(source_commit):
        raise DistributionContractError("composite sourceCommit is invalid")
    if expected_source_commit is not None and source_commit != expected_source_commit:
        raise DistributionContractError("composite sourceCommit drifted from expected source")
    if not isinstance(document["commonCoreHash"], str) or not SHA256_RE.fullmatch(
        document["commonCoreHash"]
    ):
        raise DistributionContractError("composite commonCoreHash is invalid")
    if document["productDisplayVersion"] != "1.0.0":
        raise DistributionContractError("closed beta product display version must remain 1.0.0")
    if document["region"] not in REGIONS or document["targetArchitecture"] != "windows-x86_64":
        raise DistributionContractError("composite target is unsupported")

    edition_ref = document["edition"]
    if not isinstance(edition_ref, dict):
        raise DistributionContractError("composite edition reference must be an object")
    _require_exact_keys(edition_ref, COMPOSITE_EDITION_KEYS, "composite edition")
    expected_edition_ref = {
        "editionId": edition["editionId"],
        "editionVersion": edition["editionVersion"],
        "manifestSha256": edition_manifest_sha256,
    }
    if edition_ref != expected_edition_ref:
        raise DistributionContractError("composite edition reference drifted")
    edition_id = edition["editionId"]

    components = document["components"]
    if not isinstance(components, dict):
        raise DistributionContractError("composite components must be an object")
    _require_exact_keys(components, COMPOSITE_COMPONENT_KEYS, "composite components")
    component_refs = {
        component_id: _validate_composite_component_ref(
            components[component_id], f"composite components.{component_id}"
        )
        for component_id in sorted(COMPOSITE_COMPONENT_KEYS)
    }
    if component_refs["desktop"]["componentId"] != "desktop-core":
        raise DistributionContractError("composite desktop component id is invalid")
    if component_refs["runtimeBase"]["componentId"] != "runtime-base":
        raise DistributionContractError("composite Runtime Base component id is invalid")
    if component_refs["enginePack"]["componentId"] != "engine-pack":
        raise DistributionContractError("composite Engine Pack component id is invalid")
    for component_id in ("desktop", "enginePack"):
        if component_refs[component_id]["sourceCommit"] != source_commit:
            raise DistributionContractError(
                f"composite {component_id} must bind the common sourceCommit"
            )

    selected_modules = _validate_unique_text_list(
        document["selectedModules"], "composite selectedModules"
    )
    required_modules = set(edition["modules"]["required"])
    optional_modules = set(edition["modules"]["optional"])
    forbidden_modules = set(edition["modules"]["forbidden"])
    if (
        not required_modules <= selected_modules
        or not selected_modules <= required_modules | optional_modules
        or selected_modules & forbidden_modules
    ):
        raise DistributionContractError("composite selectedModules violate edition policy")
    capabilities = _validate_unique_text_list(document["capabilities"], "composite capabilities")
    if capabilities != set(edition["capabilities"]["enabledOrConditioned"]):
        raise DistributionContractError("composite capabilities drifted from edition")

    vehicle_refs = document["vehiclePacks"]
    if not isinstance(vehicle_refs, list) or not vehicle_refs:
        raise DistributionContractError("composite vehiclePacks must be non-empty")
    selected_pack_ids: set[str] = set()
    vehicle_artifact_bytes = 0
    all_vehicle_packs_validated = True
    all_vehicle_signatures_verified = True
    for index, vehicle_ref in enumerate(vehicle_refs):
        label = f"composite vehiclePacks[{index}]"
        if not isinstance(vehicle_ref, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(vehicle_ref, COMPOSITE_VEHICLE_REF_KEYS, label)
        pack_id = vehicle_ref["packId"]
        if pack_id not in vehicle_packs or pack_id in selected_pack_ids:
            raise DistributionContractError(f"{label}.packId is unknown or duplicated")
        if pack_id not in vehicle_pack_manifest_sha256:
            raise DistributionContractError(f"{label} is missing a manifest hash")
        selected_pack_ids.add(pack_id)
        pack = vehicle_packs[pack_id]
        expected_vehicle_ref = {
            "packId": pack_id,
            "packVersion": pack["packVersion"],
            "manifestSha256": vehicle_pack_manifest_sha256[pack_id],
            "payloadSha256": pack["integrity"]["payloadSha256"],
            "artifactSha256": vehicle_ref["artifactSha256"],
            "artifactBytes": vehicle_ref["artifactBytes"],
            "signatureState": pack["integrity"]["signature"]["state"],
            "validationTier": pack["validationTier"],
        }
        if vehicle_ref != expected_vehicle_ref:
            raise DistributionContractError(f"{label} drifted from Vehicle Pack manifest")
        if (
            edition_id not in pack["supportedEditions"]
            or document["region"] not in pack["availabilityRegions"]
        ):
            raise DistributionContractError(f"{label} is incompatible with edition or region")
        if not isinstance(vehicle_ref["artifactBytes"], int) or vehicle_ref["artifactBytes"] < 0:
            raise DistributionContractError(f"{label}.artifactBytes is invalid")
        if not isinstance(vehicle_ref["artifactSha256"], str) or not SHA256_RE.fullmatch(
            vehicle_ref["artifactSha256"]
        ):
            raise DistributionContractError(f"{label}.artifactSha256 is invalid")
        vehicle_artifact_bytes += vehicle_ref["artifactBytes"]
        all_vehicle_packs_validated &= pack["validationStatus"] == "validated"
        all_vehicle_signatures_verified &= vehicle_ref["signatureState"] == "verified"

    resource = document["resourceEstimate"]
    if not isinstance(resource, dict):
        raise DistributionContractError("composite resourceEstimate must be an object")
    _require_exact_keys(resource, COMPOSITE_RESOURCE_KEYS, "composite resourceEstimate")
    for field in ("downloadBytes", "installedBytes"):
        if not isinstance(resource[field], int) or resource[field] < 0:
            raise DistributionContractError(f"composite resourceEstimate.{field} is invalid")
    expected_download_bytes = vehicle_artifact_bytes + sum(
        component["artifactBytes"] for component in component_refs.values()
    )
    if resource["downloadBytes"] != expected_download_bytes:
        raise DistributionContractError("composite downloadBytes do not match artifacts")
    if resource["installedBytes"] < resource["downloadBytes"]:
        raise DistributionContractError("composite installedBytes cannot be below downloadBytes")
    if not isinstance(resource["requiresWsl"], bool) or not isinstance(
        resource["requiresGazebo"], bool
    ):
        raise DistributionContractError("composite resource booleans are invalid")
    includes_simulator = edition["runtimeProfile"]["includesLargeSimulator"]
    if resource["requiresGazebo"] is not includes_simulator:
        raise DistributionContractError("composite Gazebo requirement drifted from edition")
    if edition_id == "field" and resource["requiresWsl"]:
        raise DistributionContractError("Field lightweight contract cannot require WSL")

    installability = document["installability"]
    if not isinstance(installability, dict):
        raise DistributionContractError("composite installability must be an object")
    _require_exact_keys(
        installability,
        COMPOSITE_INSTALLABILITY_KEYS,
        "composite installability",
    )
    if installability["state"] not in {"installable", "planned"}:
        raise DistributionContractError("composite installability state is unsupported")
    blockers = _validate_unique_text_list(
        installability["blockers"],
        "composite installability.blockers",
        allow_empty=True,
    )
    if installability["physicalCapabilityStatus"] not in {
        "disabled",
        "contract-only",
        "validated",
    }:
        raise DistributionContractError("composite physical capability status is unsupported")
    if edition_id == "sim" and installability["physicalCapabilityStatus"] != "disabled":
        raise DistributionContractError("Sim physical capabilities must be disabled")
    if (
        edition_id in {"lab", "field"}
        and edition["validationTier"] == "contract-only"
        and (installability["physicalCapabilityStatus"] != "contract-only")
    ):
        raise DistributionContractError("hardware edition cannot overstate physical validation")
    if installability["state"] == "installable":
        if blockers:
            raise DistributionContractError("installable composite cannot retain blockers")
        if edition["implementationStatus"] != "integrated-contract":
            raise DistributionContractError("contract-only edition cannot be installable")
        if not all_vehicle_packs_validated or not all_vehicle_signatures_verified:
            raise DistributionContractError(
                "installable composite requires validated signed Vehicle Packs"
            )
        for component_id in ("runtimeBase", "enginePack"):
            if component_refs[component_id]["signatureState"] != "verified":
                raise DistributionContractError(
                    "installable composite requires signed Runtime Base and Engine Pack"
                )
    elif not blockers:
        raise DistributionContractError("planned composite must explain its blockers")

    license_notice = document["licenseNotice"]
    if not isinstance(license_notice, dict):
        raise DistributionContractError("composite licenseNotice must be an object")
    _require_exact_keys(
        license_notice,
        COMPOSITE_LICENSE_NOTICE_KEYS,
        "composite licenseNotice",
    )
    if not isinstance(license_notice["path"], str) or not SAFE_RELATIVE_PATH_RE.fullmatch(
        license_notice["path"]
    ):
        raise DistributionContractError("composite license notice path is unsafe")
    if not isinstance(license_notice["sha256"], str) or not SHA256_RE.fullmatch(
        license_notice["sha256"]
    ):
        raise DistributionContractError("composite license notice hash is invalid")
    if not isinstance(license_notice["sizeBytes"], int) or license_notice["sizeBytes"] <= 0:
        raise DistributionContractError("composite license notice size is invalid")
    return document


def _validate_promotion_component_ref(
    value: Any,
    label: str,
    *,
    expected: dict[str, Any],
) -> None:
    if not isinstance(value, dict):
        raise DistributionContractError(f"{label} must be an object")
    _require_exact_keys(value, PROMOTION_COMPONENT_KEYS, label)
    expected_ref = {
        "manifestSha256": expected["manifestSha256"],
        "artifactSha256": expected["artifactSha256"],
        "buildId": expected["buildId"],
    }
    if value != expected_ref:
        raise DistributionContractError(f"{label} drifted from composite installation")


def validate_release_promotion_manifest(
    document: Any,
    *,
    edition: dict[str, Any],
    edition_manifest_sha256: str,
    composite: dict[str, Any],
    composite_manifest_sha256: str,
    observed_branch_head: str | None = None,
    observed_metadata_only_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Validate a release-channel promotion without creating or mutating a branch."""

    if not isinstance(document, dict):
        raise DistributionContractError("release promotion manifest must be an object")
    _require_exact_keys(document, RELEASE_PROMOTION_KEYS, "release promotion manifest")
    if (
        document["schemaVersion"] != 1
        or document["kind"] != "dronedream-release-promotion"
        or not SEMVER_RE.fullmatch(str(document["promotionVersion"]))
    ):
        raise DistributionContractError("release promotion identity is unsupported")
    promotion_id = _require_nonempty_string(
        document["promotionId"], "release promotion promotionId", maximum=128
    )
    if not DOTTED_ID_RE.fullmatch(promotion_id):
        raise DistributionContractError("release promotion promotionId is invalid")
    state = document["state"]
    if state not in {"planned", "promotable"}:
        raise DistributionContractError("release promotion state is unsupported")
    blockers = _validate_unique_text_list(
        document["blockers"], "release promotion blockers", allow_empty=True
    )
    source_commit = document["sourceCommit"]
    if not isinstance(source_commit, str) or not COMMIT_RE.fullmatch(source_commit):
        raise DistributionContractError("release promotion sourceCommit is invalid")
    if source_commit != composite["sourceCommit"]:
        raise DistributionContractError("release promotion source drifted from composite")
    common_core_hash = document["commonCoreHash"]
    if not isinstance(common_core_hash, str) or not SHA256_RE.fullmatch(common_core_hash):
        raise DistributionContractError("release promotion commonCoreHash is invalid")
    if common_core_hash != composite["commonCoreHash"]:
        raise DistributionContractError("release promotion common core drifted from composite")
    if document["productDisplayVersion"] != composite["productDisplayVersion"]:
        raise DistributionContractError("release promotion product version drifted")

    edition_ref = document["edition"]
    if not isinstance(edition_ref, dict):
        raise DistributionContractError("release promotion edition must be an object")
    _require_exact_keys(edition_ref, PROMOTION_EDITION_KEYS, "release promotion edition")
    expected_edition_ref = {
        "editionId": edition["editionId"],
        "editionManifestSha256": edition_manifest_sha256,
        "compositeManifestSha256": composite_manifest_sha256,
    }
    if (
        edition_ref != expected_edition_ref
        or composite["edition"]["editionId"] != edition["editionId"]
    ):
        raise DistributionContractError("release promotion edition binding drifted")

    branch_policy = document["branchPolicy"]
    if not isinstance(branch_policy, dict):
        raise DistributionContractError("release promotion branchPolicy must be an object")
    _require_exact_keys(
        branch_policy, PROMOTION_BRANCH_POLICY_KEYS, "release promotion branchPolicy"
    )
    if branch_policy["targetBranch"] != edition["releaseChannel"]["branch"]:
        raise DistributionContractError("release promotion target branch drifted from edition")
    if branch_policy["creationState"] not in PROMOTION_BRANCH_CREATION_STATES:
        raise DistributionContractError("release promotion branch creation state is unsupported")
    if branch_policy["prOnly"] is not True or branch_policy["forcePushAllowed"] is not False:
        raise DistributionContractError("release promotion must be PR-only and forbid force-push")
    proposed_head = branch_policy["proposedHeadCommit"]
    if not isinstance(proposed_head, str) or not COMMIT_RE.fullmatch(proposed_head):
        raise DistributionContractError("release promotion proposed branch head is invalid")
    head_classification = branch_policy["headClassification"]
    declared_paths = branch_policy["metadataOnlyChangedPaths"]
    _validate_unique_text_list(
        declared_paths,
        "release promotion metadataOnlyChangedPaths",
        allow_empty=True,
    )
    for path in declared_paths:
        if not SAFE_RELATIVE_PATH_RE.fullmatch(path) or not path.startswith(
            PROMOTION_METADATA_PREFIXES
        ):
            raise DistributionContractError(
                "release promotion metadata-only path is outside the allowlist"
            )
    if head_classification == "exact-source":
        if proposed_head != source_commit or declared_paths:
            raise DistributionContractError(
                "exact-source promotion must use sourceCommit with no changed paths"
            )
        if observed_metadata_only_paths not in (None, []):
            raise DistributionContractError(
                "exact-source promotion cannot have observed metadata-only changes"
            )
    elif head_classification == "edition-metadata-only":
        if proposed_head == source_commit or not declared_paths:
            raise DistributionContractError(
                "metadata-only promotion requires a later head and changed paths"
            )
        if observed_metadata_only_paths is None:
            raise DistributionContractError(
                "metadata-only promotion requires observed Git changed paths"
            )
        observed_paths = sorted(observed_metadata_only_paths)
        if observed_paths != sorted(declared_paths):
            raise DistributionContractError(
                "metadata-only promotion paths drifted from observed Git diff"
            )
    else:
        raise DistributionContractError("release promotion head classification is unsupported")
    if observed_branch_head is not None:
        if not COMMIT_RE.fullmatch(observed_branch_head) or observed_branch_head != proposed_head:
            raise DistributionContractError("release promotion branch head drifted")
    elif branch_policy["creationState"] in PROMOTION_BRANCH_CREATION_STATES:
        raise DistributionContractError(
            "long-lived product branch requires an independently observed branch head"
        )

    artifact = document["artifact"]
    if not isinstance(artifact, dict):
        raise DistributionContractError("release promotion artifact must be an object")
    _require_exact_keys(artifact, PROMOTION_ARTIFACT_KEYS, "release promotion artifact")
    if artifact["fileName"] != edition["artifactBaseName"]:
        raise DistributionContractError("release promotion artifact filename drifted from edition")
    if not isinstance(artifact["sha256"], str) or not SHA256_RE.fullmatch(artifact["sha256"]):
        raise DistributionContractError("release promotion artifact SHA-256 is invalid")
    if not isinstance(artifact["bytes"], int) or artifact["bytes"] < 0:
        raise DistributionContractError("release promotion artifact size is invalid")
    if artifact["authenticodeState"] not in {"valid", "not-signed"}:
        raise DistributionContractError("release promotion Authenticode state is unsupported")
    if artifact["updaterSignatureState"] not in {"verified", "not-issued"}:
        raise DistributionContractError("release promotion updater signature state is unsupported")

    _validate_promotion_component_ref(
        document["runtimeBase"],
        "release promotion runtimeBase",
        expected=composite["components"]["runtimeBase"],
    )
    _validate_promotion_component_ref(
        document["enginePack"],
        "release promotion enginePack",
        expected=composite["components"]["enginePack"],
    )

    vehicle_refs = document["vehiclePacks"]
    if not isinstance(vehicle_refs, list) or not vehicle_refs:
        raise DistributionContractError("release promotion vehiclePacks must be non-empty")
    expected_vehicle_refs = {
        ref["packId"]: {
            "packId": ref["packId"],
            "manifestSha256": ref["manifestSha256"],
            "artifactSha256": ref["artifactSha256"],
        }
        for ref in composite["vehiclePacks"]
    }
    actual_vehicle_refs: dict[str, dict[str, Any]] = {}
    for index, ref in enumerate(vehicle_refs):
        label = f"release promotion vehiclePacks[{index}]"
        if not isinstance(ref, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(ref, PROMOTION_VEHICLE_PACK_KEYS, label)
        pack_id = ref["packId"]
        if pack_id in actual_vehicle_refs:
            raise DistributionContractError("release promotion Vehicle Pack is duplicated")
        actual_vehicle_refs[pack_id] = ref
    if actual_vehicle_refs != expected_vehicle_refs:
        raise DistributionContractError("release promotion Vehicle Packs drifted from composite")

    capabilities = _validate_unique_text_list(
        document["capabilities"], "release promotion capabilities"
    )
    if capabilities != set(composite["capabilities"]):
        raise DistributionContractError("release promotion capabilities drifted from composite")
    if document["validationTier"] != edition["validationTier"]:
        raise DistributionContractError("release promotion validation tier drifted from edition")
    if document["licenseNotice"] != composite["licenseNotice"]:
        raise DistributionContractError("release promotion license notice drifted from composite")

    supersedes = document["supersedes"]
    if not isinstance(supersedes, list):
        raise DistributionContractError("release promotion supersedes must be a list")
    superseded: dict[str, str] = {}
    for index, ref in enumerate(supersedes):
        label = f"release promotion supersedes[{index}]"
        if not isinstance(ref, dict):
            raise DistributionContractError(f"{label} must be an object")
        _require_exact_keys(ref, PROMOTION_SUPERSEDES_KEYS, label)
        previous_id = _require_nonempty_string(ref["promotionId"], f"{label}.promotionId")
        previous_sha = ref["artifactSha256"]
        if (
            not DOTTED_ID_RE.fullmatch(previous_id)
            or not isinstance(previous_sha, str)
            or not SHA256_RE.fullmatch(previous_sha)
            or previous_id in superseded
        ):
            raise DistributionContractError(f"{label} is invalid or duplicated")
        superseded[previous_id] = previous_sha
    rollback = document["rollback"]
    if not isinstance(rollback, dict):
        raise DistributionContractError("release promotion rollback must be an object")
    _require_exact_keys(rollback, PROMOTION_ROLLBACK_KEYS, "release promotion rollback")
    if rollback["policy"] != "previous-verified-promotion":
        raise DistributionContractError("release promotion rollback policy is unsupported")
    rollback_id = rollback["targetPromotionId"]
    rollback_sha = rollback["targetArtifactSha256"]
    if not superseded:
        if rollback_id is not None or rollback_sha is not None:
            raise DistributionContractError("first promotion cannot name a rollback target")
    elif (
        not isinstance(rollback_id, str)
        or rollback_id not in superseded
        or rollback_sha != superseded[rollback_id]
    ):
        raise DistributionContractError("release promotion rollback target is not superseded")

    if state == "planned":
        if not blockers:
            raise DistributionContractError("planned release promotion must explain blockers")
    else:
        if blockers:
            raise DistributionContractError("promotable release promotion cannot retain blockers")
        if composite["installability"]["state"] != "installable":
            raise DistributionContractError("promotable release requires an installable composite")
        if artifact["bytes"] <= 0 or artifact["updaterSignatureState"] != "verified":
            raise DistributionContractError(
                "promotable release requires a non-empty updater-signed artifact"
            )
    return document


def validate_release_promotion_set(
    promotions: list[dict[str, Any]],
) -> None:
    """Enforce one-source/common-core parity across every edition channel."""

    if len(promotions) != len(EDITION_IDS):
        raise DistributionContractError("release promotion set must contain all product editions")
    by_edition = {promotion["edition"]["editionId"]: promotion for promotion in promotions}
    if set(by_edition) != EDITION_IDS or len(by_edition) != len(promotions):
        raise DistributionContractError(
            "release promotion set editions are incomplete or duplicated"
        )
    if len({promotion["sourceCommit"] for promotion in promotions}) != 1:
        raise DistributionContractError("release promotion set source commits diverged")
    if len({promotion["commonCoreHash"] for promotion in promotions}) != 1:
        raise DistributionContractError("release promotion set common core hashes diverged")
    if len({promotion["productDisplayVersion"] for promotion in promotions}) != 1:
        raise DistributionContractError("release promotion set product versions diverged")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    upstream = subparsers.add_parser("upstream", help="validate an upstream inventory")
    upstream.add_argument("inventory", type=Path)
    editions = subparsers.add_parser("editions", help="validate the capability policy and editions")
    editions.add_argument("--policy", type=Path, required=True)
    editions.add_argument("manifests", nargs="+", type=Path)
    vehicle_packs_parser = subparsers.add_parser(
        "vehicle-packs", help="validate Vehicle Pack manifests"
    )
    vehicle_packs_parser.add_argument("--inventory", type=Path, required=True)
    vehicle_packs_parser.add_argument("--policy", type=Path, required=True)
    vehicle_packs_parser.add_argument("manifests", nargs="+", type=Path)
    vehicle_pack_registry = subparsers.add_parser(
        "vehicle-pack-registry",
        help="validate the initial Vehicle Pack registry against independently supplied manifests",
    )
    vehicle_pack_registry.add_argument("--inventory", type=Path, required=True)
    vehicle_pack_registry.add_argument("--policy", type=Path, required=True)
    vehicle_pack_registry.add_argument(
        "--vehicle-pack",
        type=Path,
        action="append",
        required=True,
    )
    vehicle_pack_registry.add_argument("registry", type=Path)
    composite = subparsers.add_parser(
        "composite", help="validate a composite installation manifest"
    )
    composite.add_argument("--edition", type=Path, required=True)
    composite.add_argument("--policy", type=Path, required=True)
    composite.add_argument("--inventory", type=Path, required=True)
    composite.add_argument("--vehicle-pack", type=Path, action="append", required=True)
    composite.add_argument("--expected-source", required=True)
    composite.add_argument("manifest", type=Path)
    promotion = subparsers.add_parser(
        "promotion", help="validate a release promotion manifest without changing branches"
    )
    promotion.add_argument("--edition", type=Path, required=True)
    promotion.add_argument("--policy", type=Path, required=True)
    promotion.add_argument("--inventory", type=Path, required=True)
    promotion.add_argument("--vehicle-pack", type=Path, action="append", required=True)
    promotion.add_argument("--composite", type=Path, required=True)
    promotion.add_argument("--expected-source", required=True)
    promotion.add_argument("--observed-branch-head")
    promotion.add_argument("--observed-metadata-path", action="append")
    promotion.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "upstream":
            load_upstream_source_inventory(args.inventory)
        elif args.command == "editions":
            load_edition_manifests(args.manifests, policy_path=args.policy)
        elif args.command == "vehicle-packs":
            load_vehicle_pack_manifests(
                args.manifests,
                upstream_inventory_path=args.inventory,
                capability_policy_path=args.policy,
            )
        elif args.command == "vehicle-pack-registry":
            load_vehicle_pack_registry(
                args.registry,
                vehicle_pack_paths=args.vehicle_pack,
                upstream_inventory_path=args.inventory,
                capability_policy_path=args.policy,
                repository_root=Path(__file__).resolve().parents[2],
            )
        elif args.command in {"composite", "promotion"}:
            policy = load_capability_policy(args.policy)
            edition = validate_edition_manifest(
                _load_json_document(args.edition, "edition manifest"),
                policy=policy,
                policy_sha256=sha256_file(args.policy),
            )
            pack_manifests = load_vehicle_pack_manifests(
                args.vehicle_pack,
                upstream_inventory_path=args.inventory,
                capability_policy_path=args.policy,
            )
            vehicle_pack_shas = {
                pack["packId"]: sha256_file(path)
                for path, pack in zip(
                    args.vehicle_pack,
                    (
                        _load_json_document(path, "Vehicle Pack manifest")
                        for path in args.vehicle_pack
                    ),
                    strict=True,
                )
            }
            composite_path = args.manifest if args.command == "composite" else args.composite
            composite_document = validate_composite_installation_manifest(
                _load_json_document(composite_path, "composite installation manifest"),
                edition=edition,
                edition_manifest_sha256=sha256_file(args.edition),
                vehicle_packs=pack_manifests,
                vehicle_pack_manifest_sha256=vehicle_pack_shas,
                expected_source_commit=args.expected_source,
            )
            if args.command == "promotion":
                validate_release_promotion_manifest(
                    _load_json_document(args.manifest, "release promotion manifest"),
                    edition=edition,
                    edition_manifest_sha256=sha256_file(args.edition),
                    composite=composite_document,
                    composite_manifest_sha256=sha256_file(args.composite),
                    observed_branch_head=args.observed_branch_head,
                    observed_metadata_only_paths=args.observed_metadata_path,
                )
        else:
            raise DistributionContractError(f"unsupported command: {args.command}")
    except DistributionContractError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
