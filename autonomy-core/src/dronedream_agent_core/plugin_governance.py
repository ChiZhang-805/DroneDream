"""Deterministic enterprise policy evaluation for plugin lifecycle mutations."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from .hashing import sha256_json
from .plugin_contracts import (
    PluginGovernanceDecision,
    PluginGovernanceOperation,
    PluginGovernancePolicy,
    PluginManifest,
)


def evaluate_plugin_governance(
    *,
    policy: PluginGovernancePolicy,
    manifest: PluginManifest,
    operation: PluginGovernanceOperation,
    trust_status: str,
    installed_external_plugins: int,
) -> PluginGovernanceDecision:
    """Return a hash-bound decision; an empty allowlist intentionally means unrestricted."""

    issue_codes: list[str] = []
    if policy.allowed_plugin_ids and manifest.plugin_id not in policy.allowed_plugin_ids:
        issue_codes.append("GOVERNANCE_PLUGIN_NOT_ALLOWED")
    if policy.allowed_publishers and manifest.publisher not in policy.allowed_publishers:
        issue_codes.append("GOVERNANCE_PUBLISHER_NOT_ALLOWED")
    denied = sorted(set(manifest.permissions).intersection(policy.denied_permissions))
    issue_codes.extend(f"GOVERNANCE_PERMISSION_DENIED:{permission}" for permission in denied)
    if manifest.provenance.update_ring not in policy.allowed_update_rings:
        issue_codes.append("GOVERNANCE_UPDATE_RING_DENIED")
    if operation == "import" and installed_external_plugins >= policy.maximum_external_plugins:
        issue_codes.append("GOVERNANCE_EXTERNAL_PLUGIN_LIMIT")
    if (
        operation in {"enable", "promote"}
        and policy.require_verified_signatures
        and trust_status != "verified"
    ):
        issue_codes.append("GOVERNANCE_VERIFIED_SIGNATURE_REQUIRED")
    if operation == "trust-local-package" and not policy.allow_local_approval:
        issue_codes.append("GOVERNANCE_LOCAL_APPROVAL_DISABLED")
    if trust_status == "revoked":
        issue_codes.append("GOVERNANCE_PACKAGE_REVOKED")
    return PluginGovernanceDecision(
        decision_id=f"plugin-policy-{uuid4().hex[:24]}",
        policy_id=policy.policy_id,
        operation=operation,
        plugin_id=manifest.plugin_id,
        version=manifest.version,
        accepted=not issue_codes,
        issue_codes=issue_codes,
        policy_sha256=sha256_json(policy.model_dump(mode="json")),
        manifest_sha256=sha256_json(manifest.model_dump(mode="json")),
        trust_status=trust_status,  # type: ignore[arg-type]
        created_at=datetime.now(UTC),
    )
