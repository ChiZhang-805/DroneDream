#!/usr/bin/env python3
"""Validate DroneDream distribution contracts without third-party packages."""

from __future__ import annotations

import argparse
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
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
LICENSE_RE = re.compile(
    r"^(?:[A-Za-z0-9.+-]+(?: (?:AND|OR) [A-Za-z0-9.+-]+)*|NOASSERTION)$"
)
IMMUTABLE_RAW_LICENSE_RE = re.compile(
    r"^https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/"
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    args = parser.parse_args()
    try:
        load_upstream_source_inventory(args.inventory)
    except DistributionContractError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
