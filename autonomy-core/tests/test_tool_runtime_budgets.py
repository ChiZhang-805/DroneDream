import pytest
from pydantic import BaseModel

from dronedream_agent_core.tools import ToolPlugin, ToolRegistry


class _Value(BaseModel):
    value: int


def _tool(tool_id: str, slot_id: str) -> ToolPlugin[_Value, _Value]:
    return ToolPlugin(
        tool_id=tool_id,
        version="1.0.0",
        authority="plan",
        input_type=_Value,
        output_type=_Value,
        handler=lambda value: value,
        slot_id=slot_id,
    )


def test_optional_budget_cannot_starve_reserved_planning_tools() -> None:
    registry = ToolRegistry(allowed_authorities={"plan"})
    registry.register(_tool("optional", "mission.advice"))
    registry.register(_tool("route", "planning.route-strategy"))
    registry.configure_runtime_limits(
        maximum_calls=1,
        maximum_total_calls=4,
        timeout_seconds=1,
        budget_exempt_slot_ids={"planning.route-strategy"},
    )

    registry.call("optional", _Value(value=1))
    with pytest.raises(RuntimeError, match="HARNESS_OPTIONAL_TOOL_CALL_BUDGET_EXCEEDED"):
        registry.call("optional", _Value(value=2))

    output, _receipt = registry.call("route", _Value(value=3))
    assert output == _Value(value=3)


def test_reserved_tools_still_obey_independent_total_ceiling() -> None:
    registry = ToolRegistry(allowed_authorities={"plan"})
    registry.register(_tool("route", "planning.route-strategy"))
    registry.configure_runtime_limits(
        maximum_calls=0,
        maximum_total_calls=1,
        timeout_seconds=1,
        budget_exempt_slot_ids={"planning.route-strategy"},
    )

    registry.call("route", _Value(value=1))
    with pytest.raises(RuntimeError, match="HARNESS_TOTAL_TOOL_CALL_BUDGET_EXCEEDED"):
        registry.call("route", _Value(value=2))
