"""Validate and plan DroneDream's independently updateable desktop components."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path("distribution/desktop/component-update-policy.v1.json")
COMPONENT_IDS = (
    "desktop-app",
    "base-runtime",
    "engine-pack",
    "capability-pack",
    "asset-pack",
    "user-state",
)
UPDATE_ORDER = COMPONENT_IDS[:-1]
EDITIONS = ("universal", "sim", "lab", "field")


class ComponentUpdatePolicyError(RuntimeError):
    """Raised when component trust, ordering, or state isolation drifts."""


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ComponentUpdatePolicyError(f"{label} fields drifted")


def validate_contract(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ComponentUpdatePolicyError("component update policy must be an object")
    _exact_keys(
        document,
        {
            "schemaVersion",
            "kind",
            "contractVersion",
            "catalogTrust",
            "updateOrder",
            "components",
        },
        "component update policy",
    )
    if (
        document["schemaVersion"] != 1
        or document["kind"] != "dronedream-desktop-component-update-policy"
        or document["contractVersion"] != "1.0.0"
    ):
        raise ComponentUpdatePolicyError("component update policy identity is unsupported")
    if document["catalogTrust"] != {
        "canonicalization": "RFC8785-JCS",
        "signatureAlgorithm": "Ed25519",
        "detachedSignatureRequired": True,
        "httpsRequired": True,
        "contentHashAlgorithm": "SHA-256",
        "antiRollbackSequenceRequired": True,
        "unknownComponentAction": "reject",
    }:
        raise ComponentUpdatePolicyError("component catalog trust policy drifted")
    if tuple(document["updateOrder"]) != UPDATE_ORDER:
        raise ComponentUpdatePolicyError("component activation order drifted")

    components = document["components"]
    if not isinstance(components, list) or tuple(
        component.get("componentId") for component in components
    ) != COMPONENT_IDS:
        raise ComponentUpdatePolicyError("components must be canonical and ordered")
    component_keys = {
        "componentId",
        "displayName",
        "installScope",
        "updateMechanism",
        "implementationState",
        "defaultPolicy",
        "activationStrategy",
        "rollbackStrategy",
        "preservesUserState",
        "editions",
        "requires",
    }
    by_id = {component["componentId"]: component for component in components}
    for index, component in enumerate(components):
        component_id = component["componentId"]
        _exact_keys(component, component_keys, component_id)
        if component["editions"] != list(EDITIONS):
            raise ComponentUpdatePolicyError(f"{component_id} edition coverage drifted")
        if component["preservesUserState"] is not True:
            raise ComponentUpdatePolicyError(f"{component_id} may not mutate user state")
        dependencies = component["requires"]
        if len(dependencies) != len(set(dependencies)):
            raise ComponentUpdatePolicyError(f"{component_id} dependencies repeat")
        for dependency in dependencies:
            if dependency not in by_id or COMPONENT_IDS.index(dependency) >= index:
                raise ComponentUpdatePolicyError(
                    f"{component_id} dependency order is unsafe"
                )

    user_state = by_id["user-state"]
    if (
        user_state["updateMechanism"] != "none"
        or user_state["implementationState"] != "not-updatable"
        or user_state["defaultPolicy"] != "never"
        or user_state["rollbackStrategy"] != "never-touch"
    ):
        raise ComponentUpdatePolicyError("user state must remain outside all update payloads")
    return document


def load_contract(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_PATH
    if path.is_symlink() or not path.is_file():
        raise ComponentUpdatePolicyError("component update policy is unavailable")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ComponentUpdatePolicyError("component update policy is invalid") from error
    return validate_contract(document)


def plan_updates(
    policy: dict[str, Any],
    installed_sequences: Mapping[str, int],
    candidates: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Create a deterministic, fail-closed update plan from verified observations.

    `trusted` means the native layer has verified the detached catalog signature,
    component manifest signature, HTTPS origin, artifact size, and SHA-256. This
    planner never upgrades self-reported trust.
    """

    validate_contract(policy)
    unknown = set(candidates) - set(UPDATE_ORDER)
    if unknown:
        raise ComponentUpdatePolicyError("unknown update component was rejected")
    components = {item["componentId"]: item for item in policy["components"]}
    plan: list[dict[str, Any]] = []
    for component_id in UPDATE_ORDER:
        candidate = candidates.get(component_id)
        if candidate is None:
            continue
        required_fields = {"sequence", "version", "trusted", "compatible", "policy"}
        if set(candidate) != required_fields:
            raise ComponentUpdatePolicyError(f"{component_id} candidate fields drifted")
        if candidate["policy"] not in {"recommended", "required"}:
            raise ComponentUpdatePolicyError(f"{component_id} update policy is invalid")
        sequence = candidate["sequence"]
        installed = installed_sequences.get(component_id, 0)
        if not isinstance(sequence, int) or sequence <= 0:
            raise ComponentUpdatePolicyError(f"{component_id} sequence is invalid")
        if not candidate["trusted"]:
            status = "rejected-untrusted"
        elif not candidate["compatible"]:
            status = "blocked-incompatible"
        elif sequence <= installed:
            status = "current-or-replay"
        elif components[component_id]["implementationState"] != "implemented":
            status = (
                "blocked-manager-unavailable"
                if candidate["policy"] == "required"
                else "deferred-manager-unavailable"
            )
        else:
            status = "ready-required" if candidate["policy"] == "required" else "ready-recommended"
        plan.append(
            {
                "componentId": component_id,
                "version": candidate["version"],
                "sequence": sequence,
                "policy": candidate["policy"],
                "status": status,
                "activationStrategy": components[component_id]["activationStrategy"],
                "rollbackStrategy": components[component_id]["rollbackStrategy"],
            }
        )
    return plan
