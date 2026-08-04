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
LICENSE_RE = re.compile(
    r"^(?:[A-Za-z0-9.+-]+(?: (?:AND|OR) [A-Za-z0-9.+-]+)*|NOASSERTION)$"
)
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
EDITION_IDS = {"sim", "lab", "field"}
ENFORCEMENT_LAYERS = {"backend", "runtime", "native"}
CONDITION_LAYERS = ENFORCEMENT_LAYERS | {"operator"}
TARGET_KINDS = {"installation", "simulation", "hitl", "real-hardware"}
RISK_LEVELS = {"read-only", "controlled", "safety-critical"}
DECISIONS = {"allow", "conditioned", "deny"}
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


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


def _validate_unique_text_list(
    value: Any, label: str, *, allow_empty: bool = False
) -> set[str]:
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
    if not isinstance(document["auditDate"], str) or not DATE_RE.fullmatch(
        document["auditDate"]
    ):
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
        if not isinstance(license_conclusion, str) or not LICENSE_RE.fullmatch(
            license_conclusion
        ):
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
        if capability["risk"] == "safety-critical" and targets & {
            "hitl",
            "real-hardware",
        } and layers != ENFORCEMENT_LAYERS:
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
                raise DistributionContractError(
                    f"{decision_label} references an unknown condition"
                )
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
            raise DistributionContractError(
                f"{capability_id} must be denied by the Sim edition"
            )
        if capability_id.startswith("simulation.") and decisions["field"]["decision"] != "deny":
            raise DistributionContractError(
                f"{capability_id} must be denied by the Field edition"
            )
        if (
            capability_id == "hardware.hitl.execute"
            and decisions["field"]["decision"] != "deny"
        ):
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
    if source_policy != {
        "developmentBranch": "codex/software",
        "integrationBranch": "main",
        "editionSourceDivergenceAllowed": False,
        "hotfixMustReturnToCore": True,
        "commonCoreHashRequired": True,
    }:
        raise DistributionContractError("edition source policy permits code divergence")
    release_channel = document["releaseChannel"]
    expected_branch = f"codex/release-{edition_id}"
    if not isinstance(release_channel, dict):
        raise DistributionContractError("edition.releaseChannel must be an object")
    _require_exact_keys(
        release_channel,
        {"branch", "creationState", "promotionManifestRequired", "forcePushAllowed"},
        "edition.releaseChannel",
    )
    if (
        release_channel["branch"] != expected_branch
        or release_channel["creationState"] not in {"planned-not-created", "created-protected"}
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
        or not runtime_profile.get(
            "includesLargeSimulator"
        )
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


def load_edition_manifests(
    paths: list[Path], *, policy_path: Path
) -> dict[str, dict[str, Any]]:
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
        raise DistributionContractError("exactly sim, lab, and field editions are required")
    return editions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    upstream = subparsers.add_parser("upstream", help="validate an upstream inventory")
    upstream.add_argument("inventory", type=Path)
    editions = subparsers.add_parser("editions", help="validate the capability policy and editions")
    editions.add_argument("--policy", type=Path, required=True)
    editions.add_argument("manifests", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "upstream":
            load_upstream_source_inventory(args.inventory)
        else:
            load_edition_manifests(args.manifests, policy_path=args.policy)
    except DistributionContractError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
