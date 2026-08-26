"""Strict declarative plugin panels with bounded data binding and actions."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PanelWidgetKind = Literal[
    "text",
    "status",
    "metric",
    "log",
    "table",
    "replay",
    "telemetry",
    "configuration-form",
]
PanelSource = Literal["static", "plugin", "configuration", "events", "runtime", "task", "evidence"]
PanelActionId = Literal["panel.refresh", "plugin.healthcheck", "plugin.disable"]


class PanelModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PanelAction(PanelModel):
    action_id: PanelActionId
    label: str = Field(min_length=1, max_length=48)
    style: Literal["default", "primary", "danger"] = "default"
    confirmation: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def require_destructive_confirmation(self) -> PanelAction:
        if self.action_id == "plugin.disable" and not self.confirmation:
            raise ValueError("destructive panel action requires confirmation")
        return self


class PanelWidget(PanelModel):
    widget_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,79}$")
    kind: PanelWidgetKind
    label: str = Field(min_length=1, max_length=80)
    source: PanelSource
    path: str = Field(default="", max_length=160)
    value: str | int | float | bool | None = None
    unit: str | None = Field(default=None, max_length=24)
    limit: int = Field(default=20, ge=1, le=100)
    columns: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if value and re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", value) is None:
            raise ValueError("invalid panel data path")
        return value

    @model_validator(mode="after")
    def validate_binding(self) -> PanelWidget:
        if self.source == "static" and self.value is None:
            raise ValueError("static widget requires value")
        if self.source != "static" and self.kind != "configuration-form" and not self.path:
            raise ValueError("bound widget requires path")
        if self.kind == "configuration-form" and self.source != "configuration":
            raise ValueError("configuration form must use configuration source")
        return self


class PanelSection(PanelModel):
    section_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,79}$")
    title: str = Field(min_length=1, max_length=80)
    widgets: list[PanelWidget] = Field(default_factory=list, max_length=40)
    actions: list[PanelAction] = Field(default_factory=list, max_length=8)


class DeclarativePanelDocument(PanelModel):
    schema_version: Literal["dronedream.ui-panel.v1"] = "dronedream.ui-panel.v1"
    title: str = Field(min_length=1, max_length=120)
    sections: list[PanelSection] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def validate_size_and_identity(self) -> DeclarativePanelDocument:
        widget_ids = [widget.widget_id for section in self.sections for widget in section.widgets]
        if len(widget_ids) != len(set(widget_ids)):
            raise ValueError("duplicate panel widget id")
        if len(json.dumps(self.model_dump(mode="json"), ensure_ascii=False)) > 256_000:
            raise ValueError("panel document too large")
        return self


def normalize_legacy_panel(value: dict[str, Any]) -> dict[str, Any]:
    """Keep v0 text-only packages readable without weakening the v1 validator."""

    if value.get("schema_version") == "dronedream.ui-panel.v1":
        return value
    sections: list[dict[str, Any]] = []
    for section_index, section in enumerate(value.get("sections", [])):
        if not isinstance(section, dict):
            return value
        widgets = [
            {
                "widget_id": f"legacy-{section_index}-{item_index}",
                "kind": "text",
                "label": "信息",
                "source": "static",
                "value": item,
            }
            for item_index, item in enumerate(section.get("items", []))
        ]
        sections.append(
            {
                "section_id": f"legacy-{section_index}",
                "title": section.get("title", "信息"),
                "widgets": widgets,
            }
        )
    return {
        "schema_version": "dronedream.ui-panel.v1",
        "title": value.get("title", "插件"),
        "sections": sections,
    }


def validate_panel_document(value: object) -> DeclarativePanelDocument:
    if not isinstance(value, dict):
        raise ValueError("UI_PLUGIN_DOCUMENT_INVALID")
    return DeclarativePanelDocument.model_validate(normalize_legacy_panel(value))


def _at_path(value: object, path: str) -> object:
    current = value
    for part in path.split(".") if path else []:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return None
    return current


def materialize_panel(
    document: DeclarativePanelDocument,
    *,
    sources: dict[str, object],
    configuration_schema: dict[str, Any],
) -> dict[str, object]:
    payload = document.model_dump(mode="json")
    for section in payload["sections"]:
        for widget in section["widgets"]:
            if widget["source"] == "static":
                continue
            if widget["kind"] == "configuration-form":
                if configuration_schema:
                    jsonschema.validators.validator_for(configuration_schema).check_schema(
                        configuration_schema
                    )
                widget["schema"] = configuration_schema
                widget["resolved"] = sources.get("configuration", {})
                continue
            resolved = _at_path(sources.get(str(widget["source"]), {}), str(widget["path"]))
            if isinstance(resolved, list):
                resolved = resolved[: int(widget["limit"])]
            widget["resolved"] = resolved
    return payload
