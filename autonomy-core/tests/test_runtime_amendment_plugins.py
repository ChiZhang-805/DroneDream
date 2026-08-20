from __future__ import annotations

from types import SimpleNamespace

from dronedream_agent_plugins.runtime_amendment_plugins import _classify


def test_redirect_outranks_hover_and_continue_safety_wording() -> None:
    value = {
        "message_kind": "mission_amendment",
        "requested_action": "pause",
        "target_entity": "校园门口的保安亭",
        "requires_plan_revision": False,
        "summary": "Change destination after stable hover.",
        "parameters": {},
    }
    message = SimpleNamespace(
        text=(
            "不要继续去原来的外卖点了。我的外卖现在在校园门口的保安亭，"
            "请先安全悬停，再根据当前位置改道去校园门口，确认安全后继续执行。"
        )
    )
    prepared = SimpleNamespace(contract=SimpleNamespace(return_node="office"))

    classified = _classify(
        value=value,
        message=message,
        prepared=prepared,
    )

    assert classified["requested_action"] == "redirect"
    assert classified["target_entity"] == "校园门口的保安亭"
    assert classified["requires_plan_revision"] is True
