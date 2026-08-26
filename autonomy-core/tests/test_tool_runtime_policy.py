from __future__ import annotations

import time

import pytest
from pydantic import BaseModel

from dronedream_agent_core.tools import ToolExecutionError, ToolPlugin, ToolRegistry


class _Payload(BaseModel):
    value: int


def _registry(handler) -> ToolRegistry:
    registry = ToolRegistry(allowed_authorities={"read"})
    registry.register(
        ToolPlugin(
            tool_id="test.policy-tool",
            version="1.0.0",
            authority="read",
            input_type=_Payload,
            output_type=_Payload,
            handler=handler,
        )
    )
    return registry


def test_tool_registry_enforces_per_mission_call_budget() -> None:
    registry = _registry(lambda value: value)
    registry.configure_runtime_limits(maximum_calls=1, timeout_seconds=1)

    result, _receipt = registry.call("test.policy-tool", {"value": 1})

    assert result == _Payload(value=1)
    with pytest.raises(RuntimeError, match="HARNESS_OPTIONAL_TOOL_CALL_BUDGET_EXCEEDED"):
        registry.call("test.policy-tool", {"value": 2})


def test_tool_registry_enforces_runtime_timeout() -> None:
    def slow(value: _Payload) -> _Payload:
        time.sleep(0.15)
        return value

    registry = _registry(slow)
    registry.configure_runtime_limits(maximum_calls=2, timeout_seconds=0.1)

    with pytest.raises(ToolExecutionError) as raised:
        registry.call("test.policy-tool", {"value": 1})

    assert raised.value.receipt.issue_codes == ["TOOL_EXECUTION_FAILED:TimeoutError"]
