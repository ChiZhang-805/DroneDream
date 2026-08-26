"""Merge and validate mission-domain action packs without weakening core boundaries."""

from __future__ import annotations

from typing import Any

from .contracts import ActionDefinition, DomainActionCatalog
from .hashing import sha256_json


class DomainActionError(RuntimeError):
    pass


def merge_action_packs(values: list[Any]) -> DomainActionCatalog:
    actions: dict[str, ActionDefinition] = {}
    domains: set[str] = set()
    for raw_pack in values:
        if not isinstance(raw_pack, dict):
            raise DomainActionError("DOMAIN_ACTION_PACK_INVALID")
        domain_id = raw_pack.get("domain_id")
        raw_actions = raw_pack.get("actions")
        if not isinstance(domain_id, str) or not isinstance(raw_actions, list):
            raise DomainActionError("DOMAIN_ACTION_PACK_INVALID")
        domains.add(domain_id)
        for raw_action in raw_actions:
            action = ActionDefinition.model_validate(raw_action)
            if action.domain_id != domain_id:
                raise DomainActionError(f"DOMAIN_ACTION_PACK_DOMAIN_MISMATCH:{action.action_id}")
            previous = actions.get(action.action_id)
            if previous is not None and previous != action:
                raise DomainActionError(f"DOMAIN_ACTION_CONFLICT:{action.action_id}")
            actions[action.action_id] = action
    if "takeoff" not in actions or "land" not in actions:
        raise DomainActionError("DOMAIN_ACTION_CORE_BOUNDARY_MISSING")
    ordered = [actions[action_id] for action_id in sorted(actions)]
    catalog_payload = {
        "domains": sorted(domains),
        "actions": [item.model_dump(mode="json") for item in ordered],
    }
    return DomainActionCatalog(
        catalog_id=f"actions.{sha256_json(catalog_payload)[:24]}",
        domain_ids=sorted(domains),
        actions=ordered,
    )


def action_ids(catalog: DomainActionCatalog) -> set[str]:
    return {item.action_id for item in catalog.actions}


def movement_action_ids(catalog: DomainActionCatalog) -> set[str]:
    return {item.action_id for item in catalog.actions if item.movement}


def action_by_id(catalog: DomainActionCatalog, action_id: str) -> ActionDefinition:
    for action in catalog.actions:
        if action.action_id == action_id:
            return action
    raise DomainActionError(f"DOMAIN_ACTION_UNKNOWN:{action_id}")
