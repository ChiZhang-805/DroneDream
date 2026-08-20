"""Ordered, failure-aware dispatch for non-tool Harness plugin capabilities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from .hashing import sha256_json
from .plugin_contracts import (
    PluginActivationMode,
    PluginFailureMode,
    PluginHookReceipt,
    PluginSwapPolicy,
)


class ExtensionExecutionError(RuntimeError):
    """A fail-closed Harness extension rejected or failed an invocation."""

    def __init__(self, receipt: PluginHookReceipt) -> None:
        issue = receipt.issue_codes[0] if receipt.issue_codes else "PLUGIN_HOOK_FAILED"
        super().__init__(issue)
        self.receipt = receipt


@dataclass(frozen=True)
class ExtensionPlugin:
    plugin_id: str
    version: str
    package_sha256: str
    capability_id: str
    slot_id: str
    activation_mode: PluginActivationMode
    failure_mode: PluginFailureMode
    swap_policy: PluginSwapPolicy
    pipeline_order: int
    runs_after: tuple[str, ...]
    runs_before: tuple[str, ...]
    hooks: dict[str, Callable[..., Any]]


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {"python_type": type(value).__name__}


class ExtensionRegistry:
    """Resolve exclusive, fan-out, and ordered-pipeline Harness extension slots."""

    def __init__(self) -> None:
        self._plugins: dict[tuple[str, str], ExtensionPlugin] = {}

    def register(self, plugin: ExtensionPlugin) -> None:
        key = (plugin.plugin_id, plugin.capability_id)
        if key in self._plugins:
            raise ValueError(
                f"duplicate extension plugin capability: {plugin.plugin_id}:{plugin.capability_id}"
            )
        self._plugins[key] = plugin
        self._validate_slot(plugin.slot_id)

    def catalog(self) -> list[dict[str, object]]:
        return [
            {
                "plugin_id": item.plugin_id,
                "version": item.version,
                "package_sha256": item.package_sha256,
                "capability_id": item.capability_id,
                "slot_id": item.slot_id,
                "activation_mode": item.activation_mode,
                "failure_mode": item.failure_mode,
                "swap_policy": item.swap_policy,
                "pipeline_order": item.pipeline_order,
                "hooks": sorted(item.hooks),
            }
            for item in sorted(
                self._plugins.values(),
                key=lambda value: (value.plugin_id, value.capability_id),
            )
        ]

    def plugins_for_slot(self, slot_id: str, hook: str | None = None) -> list[ExtensionPlugin]:
        values = [item for item in self._plugins.values() if item.slot_id == slot_id]
        if hook is not None:
            values = [item for item in values if hook in item.hooks]
        if not values:
            return []
        mode = values[0].activation_mode
        if mode == "pipeline":
            return self._ordered_pipeline(values)
        return sorted(
            values,
            key=lambda item: (item.pipeline_order, item.plugin_id, item.capability_id),
        )

    def _validate_slot(self, slot_id: str) -> None:
        values = [item for item in self._plugins.values() if item.slot_id == slot_id]
        modes = {item.activation_mode for item in values}
        if len(modes) > 1:
            raise ValueError(f"mixed activation modes in extension slot: {slot_id}")
        if values and values[0].activation_mode == "single" and len(values) > 1:
            raise ValueError(f"multiple implementations in single extension slot: {slot_id}")
        if values and values[0].activation_mode == "pipeline":
            self._ordered_pipeline(values)

    @staticmethod
    def _ordered_pipeline(values: list[ExtensionPlugin]) -> list[ExtensionPlugin]:
        def key(item: ExtensionPlugin) -> str:
            return f"{item.plugin_id}#{item.capability_id}"

        by_id = {key(item): item for item in values}
        plugin_keys: dict[str, list[str]] = {}
        for instance_id, item in by_id.items():
            plugin_keys.setdefault(item.plugin_id, []).append(instance_id)
            plugin_keys.setdefault(item.capability_id, []).append(instance_id)
        edges: dict[str, set[str]] = {instance_id: set() for instance_id in by_id}
        indegree: dict[str, int] = {instance_id: 0 for instance_id in by_id}
        for item in values:
            item_key = key(item)
            for predecessor in item.runs_after:
                for predecessor_key in plugin_keys.get(predecessor, []):
                    if item_key not in edges[predecessor_key]:
                        edges[predecessor_key].add(item_key)
                        indegree[item_key] += 1
            for successor in item.runs_before:
                for successor_key in plugin_keys.get(successor, []):
                    if successor_key not in edges[item_key]:
                        edges[item_key].add(successor_key)
                        indegree[successor_key] += 1
        ready = sorted(
            (by_id[plugin_id] for plugin_id, degree in indegree.items() if degree == 0),
            key=lambda item: (item.pipeline_order, item.plugin_id, item.capability_id),
        )
        ordered: list[ExtensionPlugin] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for successor in sorted(edges[key(current)]):
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    ready.append(by_id[successor])
                    ready.sort(
                        key=lambda item: (
                            item.pipeline_order,
                            item.plugin_id,
                            item.capability_id,
                        )
                    )
        if len(ordered) != len(values):
            raise ValueError("plugin pipeline ordering cycle")
        return ordered

    @staticmethod
    def _receipt(
        plugin: ExtensionPlugin,
        hook: str,
        *,
        outcome: str,
        input_payload: Any,
        output_payload: Any,
        issue_codes: list[str] | None = None,
    ) -> PluginHookReceipt:
        return PluginHookReceipt(
            invocation_id=f"hook-{uuid4().hex[:24]}",
            plugin_id=plugin.plugin_id,
            plugin_version=plugin.version,
            plugin_package_sha256=plugin.package_sha256,
            capability_id=plugin.capability_id,
            slot_id=plugin.slot_id,
            hook=hook,
            outcome=outcome,  # type: ignore[arg-type]
            input_sha256=sha256_json(_jsonable(input_payload)),
            output_sha256=sha256_json(_jsonable(output_payload)),
            issue_codes=issue_codes or [],
            created_at=datetime.now(UTC),
        )

    def _invoke(
        self,
        plugin: ExtensionPlugin,
        hook: str,
        kwargs: dict[str, Any],
    ) -> tuple[Any, PluginHookReceipt]:
        handler = plugin.hooks[hook]
        try:
            output = handler(**kwargs)
        except Exception as error:
            receipt = self._receipt(
                plugin,
                hook,
                outcome="failed",
                input_payload=kwargs,
                output_payload={},
                issue_codes=[f"PLUGIN_HOOK_FAILED:{type(error).__name__}"],
            )
            if plugin.failure_mode == "fail-closed":
                raise ExtensionExecutionError(receipt) from error
            return None, receipt
        return output, self._receipt(
            plugin,
            hook,
            outcome="accepted",
            input_payload=kwargs,
            output_payload=output,
        )

    def invoke_single(
        self,
        slot_id: str,
        hook: str,
        *,
        required: bool = False,
        **kwargs: Any,
    ) -> tuple[Any | None, list[PluginHookReceipt]]:
        plugins = self.plugins_for_slot(slot_id, hook)
        if not plugins:
            if required:
                raise KeyError(f"required extension slot missing: {slot_id}:{hook}")
            return None, []
        if len(plugins) != 1:
            raise ValueError(f"extension single slot has {len(plugins)} handlers: {slot_id}")
        output, receipt = self._invoke(plugins[0], hook, kwargs)
        return output, [receipt]

    def invoke_multiple(
        self, slot_id: str, hook: str, **kwargs: Any
    ) -> tuple[list[Any], list[PluginHookReceipt]]:
        outputs: list[Any] = []
        receipts: list[PluginHookReceipt] = []
        for plugin in self.plugins_for_slot(slot_id, hook):
            output, receipt = self._invoke(plugin, hook, kwargs)
            receipts.append(receipt)
            if receipt.outcome == "accepted":
                outputs.append(output)
        return outputs, receipts

    def invoke_pipeline(
        self,
        slot_id: str,
        hook: str,
        value: Any,
        **kwargs: Any,
    ) -> tuple[Any, list[PluginHookReceipt]]:
        current = value
        receipts: list[PluginHookReceipt] = []
        for plugin in self.plugins_for_slot(slot_id, hook):
            output, receipt = self._invoke(plugin, hook, {"value": current, **kwargs})
            receipts.append(receipt)
            if receipt.outcome == "accepted":
                if output is None:
                    invalid = self._receipt(
                        plugin,
                        hook,
                        outcome="failed",
                        input_payload={"value": current, **kwargs},
                        output_payload={},
                        issue_codes=["PLUGIN_PIPELINE_RETURNED_NONE"],
                    )
                    receipts[-1] = invalid
                    if plugin.failure_mode == "fail-closed":
                        raise ExtensionExecutionError(invalid)
                    continue
                current = output
        return current, receipts
