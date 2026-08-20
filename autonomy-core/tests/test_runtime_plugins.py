from __future__ import annotations

from dronedream_agent_core.runtime_plugins import require_plugin_acceptance


def test_named_plugin_acceptance_builds_stable_gate_keys() -> None:
    gates, normalized = require_plugin_acceptance(
        [
            {"detector": "Runtime collision detector", "accepted": True},
            {"validator": "Flight/Envelope", "accepted": False},
        ],
        gate_prefix="runtime",
    )

    assert gates == {
        "runtime_runtime_collision_detector": True,
        "runtime_flight_envelope": False,
    }
    assert normalized[0]["accepted"] is True


def test_unnamed_and_malformed_plugin_outputs_fail_closed() -> None:
    gates, normalized = require_plugin_acceptance(
        [{"accepted": True}, "not-an-object"],
        gate_prefix="checkpoint",
    )

    assert gates == {
        "checkpoint_01": True,
        "checkpoint_02": False,
    }
    assert normalized[1]["issue_codes"] == ["PLUGIN_VERDICT_NOT_OBJECT"]


def test_duplicate_plugin_identities_get_deterministic_suffixes() -> None:
    gates, _ = require_plugin_acceptance(
        [
            {"evaluation": "clearance", "accepted": True},
            {"evaluation": "clearance", "accepted": True},
        ],
        gate_prefix="route",
    )

    assert list(gates) == ["route_clearance", "route_clearance_2"]
