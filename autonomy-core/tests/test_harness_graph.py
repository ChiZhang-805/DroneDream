from __future__ import annotations

import time

import pytest

from dronedream_agent_core.harness_graph import (
    HarnessBudget,
    HarnessGraphError,
    HarnessGraphExecutor,
    HarnessNodeSpec,
    HarnessRuntimePolicy,
    HarnessTopology,
    resolve_harness_runtime_policy,
)


def _topology(*nodes: HarnessNodeSpec, parallelism: int = 4) -> HarnessTopology:
    return HarnessTopology(
        topology_id="harness.test-topology",
        name="Test topology",
        nodes=list(nodes),
        maximum_parallelism=parallelism,
    )


def test_harness_graph_executes_dependencies_and_parallel_nodes() -> None:
    calls: list[str] = []

    def first(values: dict[str, object]) -> str:
        calls.append("first")
        return f"{values['request']}:intent"

    def left(values: dict[str, object]) -> str:
        calls.append("left")
        return f"{values['intent']}:left"

    def right(values: dict[str, object]) -> str:
        calls.append("right")
        return f"{values['intent']}:right"

    executor = HarnessGraphExecutor(handlers={"first": first, "left": left, "right": right})
    result = executor.run(
        _topology(
            HarnessNodeSpec(
                node_id="stage.intent",
                handler_id="first",
                required_inputs=["request"],
                output_key="intent",
            ),
            HarnessNodeSpec(
                node_id="stage.left-review",
                handler_id="left",
                depends_on=["stage.intent"],
                required_inputs=["intent"],
                output_key="left_review",
            ),
            HarnessNodeSpec(
                node_id="stage.right-review",
                handler_id="right",
                depends_on=["stage.intent"],
                required_inputs=["intent"],
                output_key="right_review",
            ),
        ),
        {"request": "mission"},
    )

    assert calls[0] == "first"
    assert set(calls[1:]) == {"left", "right"}
    assert result.outputs["left_review"] == "mission:intent:left"
    assert result.outputs["right_review"] == "mission:intent:right"
    assert [receipt.state for receipt in result.receipts] == [
        "accepted",
        "accepted",
        "accepted",
    ]


def test_harness_graph_retry_fallback_cache_and_observer() -> None:
    attempts = 0
    fallback_calls = 0
    events: list[str] = []

    def broken(_: dict[str, object]) -> object:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("unavailable")

    def fallback(values: dict[str, object]) -> dict[str, object]:
        nonlocal fallback_calls
        fallback_calls += 1
        return {"safe": True, "request": values["request"]}

    executor = HarnessGraphExecutor(
        handlers={"primary": broken},
        fallback_handlers={"safe": fallback},
        observers=[lambda event, _payload: events.append(event)],
    )
    topology = _topology(
        HarnessNodeSpec(
            node_id="stage.resolver",
            handler_id="primary",
            fallback_handler_id="safe",
            failure_mode="fallback",
            required_inputs=["request"],
            output_key="result",
            retry_limit=2,
            cacheable=True,
        )
    )

    first = executor.run(topology, {"request": "deliver"})
    second = executor.run(topology, {"request": "deliver"})

    assert attempts == 6
    assert fallback_calls == 2
    assert first.outputs["result"] == {"safe": True, "request": "deliver"}
    assert second.outputs["result"] == first.outputs["result"]
    assert first.receipts[0].state == "fallback"
    assert "node.fallback" in events


def test_harness_graph_isolates_advisory_node_but_fails_closed_core() -> None:
    def broken(_: dict[str, object]) -> object:
        raise RuntimeError("broken")

    isolated = HarnessGraphExecutor(handlers={"broken": broken}).run(
        _topology(
            HarnessNodeSpec(
                node_id="stage.advisory",
                handler_id="broken",
                failure_mode="isolate",
            )
        ),
        {"request": "mission"},
    )
    assert isolated.receipts[0].state == "isolated"

    with pytest.raises(HarnessGraphError, match="HARNESS_NODE_FAILED"):
        HarnessGraphExecutor(handlers={"broken": broken}).run(
            _topology(
                HarnessNodeSpec(
                    node_id="stage.core-gate",
                    handler_id="broken",
                    node_kind="core",
                )
            ),
            {"request": "mission"},
        )


def test_harness_graph_rejects_cycle_missing_input_and_budget_overrun() -> None:
    with pytest.raises(ValueError, match="cycle"):
        _topology(
            HarnessNodeSpec(node_id="stage.one", handler_id="one", depends_on=["stage.two"]),
            HarnessNodeSpec(node_id="stage.two", handler_id="two", depends_on=["stage.one"]),
        )

    with pytest.raises(HarnessGraphError, match="HARNESS_REQUIRED_INPUT_MISSING"):
        HarnessGraphExecutor(handlers={"one": lambda values: values}).run(
            _topology(
                HarnessNodeSpec(
                    node_id="stage.one",
                    handler_id="one",
                    required_inputs=["required"],
                )
            ),
            {},
        )

    with pytest.raises(HarnessGraphError, match="HARNESS_NODE_BUDGET_EXCEEDED"):
        HarnessGraphExecutor(
            handlers={"one": lambda values: values},
            budget=HarnessBudget(maximum_nodes=1),
        ).run(
            _topology(
                HarnessNodeSpec(node_id="stage.one", handler_id="one"),
                HarnessNodeSpec(node_id="stage.two", handler_id="one"),
            ),
            {},
        )


def test_harness_graph_enforces_node_timeout() -> None:
    def slow(_: dict[str, object]) -> object:
        time.sleep(0.04)
        return {}

    with pytest.raises(HarnessGraphError, match="HARNESS_NODE_FAILED:TimeoutError"):
        HarnessGraphExecutor(handlers={"slow": slow}).run(
            _topology(
                HarnessNodeSpec(
                    node_id="stage.slow",
                    handler_id="slow",
                    timeout_seconds=0.01,
                )
            ),
            {},
        )


def test_plugin_policies_are_projected_into_runtime_without_relaxing_core_limits() -> None:
    topology = _topology(
        HarnessNodeSpec(
            node_id="stage.core-gate",
            handler_id="core",
            node_kind="core",
            retry_limit=3,
            cacheable=True,
            authority="read",
        ),
        HarnessNodeSpec(
            node_id="stage.optional-read",
            handler_id="plugin",
            node_kind="plugin",
            retry_limit=3,
            cacheable=True,
            authority="read",
        ),
        parallelism=8,
    )
    selected = {
        "scheduler": {"strategy": "sequential", "maximum_parallelism": 16},
        "retry": {"maximum_retries": 2, "provider_attempts": 4},
        "timeout": {
            "model_seconds": 999,
            "tool_seconds": 12,
            "local_stage_seconds": 9,
            "mission_seconds": 120,
        },
        "budget": {
            "maximum_model_calls": 100,
            "maximum_tool_calls": 30,
            "maximum_nodes": 20,
            "maximum_retries": 2,
            "maximum_parallelism": 8,
        },
        "fallback": {"optional_failure": "isolate"},
        "cache": {"cache_read_only": True},
    }

    policy = resolve_harness_runtime_policy(
        topology,
        selected,
        maximum_model_calls=48,
        maximum_tool_calls=16,
        model_timeout_seconds=180,
    )

    assert isinstance(policy, HarnessRuntimePolicy)
    assert policy.topology.maximum_parallelism == 1
    assert policy.maximum_model_calls == 48
    assert policy.maximum_tool_calls == 16
    assert policy.model_timeout_seconds == 180
    assert policy.tool_timeout_seconds == 12
    assert policy.topology.nodes[0].failure_mode == "fail-closed"
    assert policy.topology.nodes[0].cacheable is False
    assert policy.topology.nodes[1].cacheable is True
    assert all(node.retry_limit == 2 for node in policy.topology.nodes)
