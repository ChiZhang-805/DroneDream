from __future__ import annotations

import pytest
from pydantic import ValidationError

from dronedream_agent_core.plugin_panels import materialize_panel, validate_panel_document


def _document() -> dict[str, object]:
    return {
        "schema_version": "dronedream.ui-panel.v1",
        "title": "Mission telemetry",
        "sections": [
            {
                "section_id": "runtime",
                "title": "Runtime",
                "widgets": [
                    {
                        "widget_id": "runtime-ready",
                        "kind": "status",
                        "label": "Ready",
                        "source": "runtime",
                        "path": "ready",
                    },
                    {
                        "widget_id": "recent-events",
                        "kind": "log",
                        "label": "Events",
                        "source": "events",
                        "path": "items",
                        "limit": 2,
                    },
                    {
                        "widget_id": "configuration",
                        "kind": "configuration-form",
                        "label": "Configuration",
                        "source": "configuration",
                    },
                ],
                "actions": [
                    {"action_id": "panel.refresh", "label": "Refresh"},
                    {
                        "action_id": "plugin.disable",
                        "label": "Disable",
                        "style": "danger",
                        "confirmation": "Disable this plugin?",
                    },
                ],
            }
        ],
    }


def test_panel_data_binding_is_bounded_and_configuration_schema_is_core_owned():
    document = validate_panel_document(_document())
    value = materialize_panel(
        document,
        sources={
            "runtime": {"ready": True},
            "events": {"items": [{"id": 1}, {"id": 2}, {"id": 3}]},
            "configuration": {"threshold": 3},
        },
        configuration_schema={
            "type": "object",
            "properties": {"threshold": {"type": "integer"}},
        },
    )
    widgets = value["sections"][0]["widgets"]
    assert widgets[0]["resolved"] is True
    assert widgets[1]["resolved"] == [{"id": 1}, {"id": 2}]
    assert widgets[2]["resolved"] == {"threshold": 3}
    assert widgets[2]["schema"]["properties"]["threshold"]["type"] == "integer"


def test_panel_rejects_unknown_actions_and_unconfirmed_destructive_actions():
    document = _document()
    document["sections"][0]["actions"][0]["action_id"] = "shell.execute"
    with pytest.raises(ValidationError):
        validate_panel_document(document)

    document = _document()
    del document["sections"][0]["actions"][1]["confirmation"]
    with pytest.raises(ValidationError, match="requires confirmation"):
        validate_panel_document(document)


def test_legacy_text_panel_is_normalized_without_html_execution():
    value = validate_panel_document(
        {"title": "Audit", "sections": [{"title": "Summary", "items": ["Ready"]}]}
    )
    assert value.schema_version == "dronedream.ui-panel.v1"
    assert value.sections[0].widgets[0].value == "Ready"
