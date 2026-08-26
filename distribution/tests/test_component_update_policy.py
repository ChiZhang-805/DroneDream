from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "distribution/tools/component_update_policy.py"
CONTRACT_PATH = ROOT / "distribution/desktop/component-update-policy.v1.json"
SCHEMA_PATH = ROOT / "distribution/schemas/desktop-component-update-policy.schema.json"

SPEC = importlib.util.spec_from_file_location("component_update_policy", TOOL_PATH)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tool
SPEC.loader.exec_module(tool)


def _document() -> dict[str, object]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _candidate(
    sequence: int = 2,
    *,
    trusted: bool = True,
    compatible: bool = True,
    policy: str = "recommended",
) -> dict[str, object]:
    return {
        "sequence": sequence,
        "version": "1.0.1",
        "trusted": trusted,
        "compatible": compatible,
        "policy": policy,
    }


def test_policy_schema_and_contract_are_closed() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert schema["properties"]["components"]["minItems"] == 6
    document = tool.load_contract(ROOT)
    assert document["updateOrder"] == list(tool.UPDATE_ORDER)


def test_user_state_can_never_be_an_update_payload() -> None:
    user_state = tool.load_contract(ROOT)["components"][-1]
    assert user_state["componentId"] == "user-state"
    assert user_state["defaultPolicy"] == "never"
    assert user_state["updateMechanism"] == "none"
    assert user_state["rollbackStrategy"] == "never-touch"


def test_non_user_components_reject_unknown_default_update_policies() -> None:
    changed = deepcopy(_document())
    changed["components"][0]["defaultPolicy"] = "surprise"
    with pytest.raises(tool.ComponentUpdatePolicyError, match="default update policy"):
        tool.validate_contract(changed)


def test_unknown_components_and_dependency_reordering_fail_closed() -> None:
    policy = tool.load_contract(ROOT)
    with pytest.raises(tool.ComponentUpdatePolicyError, match="unknown"):
        tool.plan_updates(policy, {}, {"surprise-payload": _candidate()})
    changed = deepcopy(_document())
    changed["components"][1]["requires"] = ["engine-pack"]
    with pytest.raises(tool.ComponentUpdatePolicyError, match="dependency order"):
        tool.validate_contract(changed)


def test_trust_compatibility_and_replay_are_not_installable() -> None:
    policy = tool.load_contract(ROOT)
    plan = tool.plan_updates(
        policy,
        {"desktop-app": 4, "engine-pack": 1},
        {
            "desktop-app": _candidate(5, trusted=False),
            "engine-pack": _candidate(2, compatible=False, policy="required"),
            "asset-pack": _candidate(1),
        },
    )
    assert [entry["status"] for entry in plan] == [
        "rejected-untrusted",
        "blocked-incompatible",
        "deferred-manager-unavailable",
    ]


def test_only_implemented_managers_produce_ready_updates() -> None:
    policy = tool.load_contract(ROOT)
    plan = tool.plan_updates(
        policy,
        {"desktop-app": 1, "engine-pack": 1},
        {
            "desktop-app": _candidate(2),
            "base-runtime": _candidate(2, policy="required"),
            "engine-pack": _candidate(2, policy="required"),
            "capability-pack": _candidate(2),
        },
    )
    assert {entry["componentId"]: entry["status"] for entry in plan} == {
        "desktop-app": "ready-recommended",
        "base-runtime": "ready-required",
        "engine-pack": "ready-required",
        "capability-pack": "deferred-manager-unavailable",
    }


def test_all_game_launcher_policies_are_planned_without_touching_user_state() -> None:
    policy = tool.load_contract(ROOT)
    plan = tool.plan_updates(
        policy,
        {"desktop-app": 1, "engine-pack": 1},
        {
            "desktop-app": _candidate(2, policy="optional"),
            "engine-pack": _candidate(2, policy="automatic"),
        },
    )
    assert [entry["status"] for entry in plan] == [
        "ready-optional",
        "ready-automatic",
    ]


def test_anti_rollback_sequence_never_reinstalls_equal_or_older_payloads() -> None:
    policy = tool.load_contract(ROOT)
    plan = tool.plan_updates(
        policy,
        {"desktop-app": 7, "engine-pack": 7},
        {
            "desktop-app": _candidate(7),
            "engine-pack": _candidate(6, policy="required"),
        },
    )
    assert all(entry["status"] == "current-or-replay" for entry in plan)
