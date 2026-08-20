"""Typed plugin registry with explicit authority and hash-bound receipts."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar
from uuid import uuid4

import jsonschema
from pydantic import BaseModel

from .contracts import ToolReceipt
from .extensions import ExtensionExecutionError, ExtensionRegistry
from .hashing import canonical_json, sha256_json
from .plugin_contracts import PluginHookReceipt

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)
ToolAuthority = Literal["read", "plan", "simulate", "actuate"]


class ToolExecutionError(RuntimeError):
    """A plugin call failed with a hash-bound receipt safe to persist as evidence."""

    def __init__(self, receipt: ToolReceipt) -> None:
        super().__init__(receipt.issue_codes[0] if receipt.issue_codes else "TOOL_CALL_FAILED")
        self.receipt = receipt


@dataclass(frozen=True)
class ToolPlugin(Generic[InputT, OutputT]):
    tool_id: str
    version: str
    authority: ToolAuthority
    input_type: type[InputT] | None
    output_type: type[OutputT] | None
    handler: Callable[[Any], Any]
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    plugin_id: str | None = None
    plugin_package_sha256: str | None = None
    routing_metadata: dict[str, Any] = field(default_factory=dict)
    slot_id: str | None = None

    def __post_init__(self) -> None:
        if self.input_type is None and self.input_schema is None:
            raise ValueError("tool plugin requires input type or schema")
        if self.output_type is None and self.output_schema is None:
            raise ValueError("tool plugin requires output type or schema")

    def resolved_input_schema(self) -> dict[str, Any]:
        if self.input_type is not None:
            return self.input_type.model_json_schema()
        assert self.input_schema is not None
        return self.input_schema

    def resolved_output_schema(self) -> dict[str, Any]:
        if self.output_type is not None:
            return self.output_type.model_json_schema()
        assert self.output_schema is not None
        return self.output_schema


class ToolRegistry:
    def __init__(self, *, allowed_authorities: set[ToolAuthority]) -> None:
        self._allowed = frozenset(allowed_authorities)
        self._plugins: dict[str, ToolPlugin] = {}
        self._extensions: ExtensionRegistry | None = None
        self._hook_receipt_sink: Callable[[list[PluginHookReceipt]], None] | None = None
        self._cache: dict[str, dict[str, object]] = {}
        self._cache_lock = threading.RLock()
        self._runtime_lock = threading.Lock()
        self._runtime_total_call_count = 0
        self._runtime_budgeted_call_count = 0
        self._runtime_total_call_limit = 256
        self._runtime_budgeted_call_limit = 256
        self._runtime_budget_exempt_slots: frozenset[str] = frozenset()
        self._runtime_timeout_seconds = 60.0

    def configure_runtime_limits(
        self,
        *,
        maximum_calls: int,
        timeout_seconds: float,
        maximum_total_calls: int = 256,
        budget_exempt_slot_ids: set[str] | frozenset[str] | None = None,
    ) -> None:
        """Reset per-mission optional and total tool limits.

        ``maximum_calls`` limits model-routed/advisory tools. Deterministic tools
        in ``budget_exempt_slot_ids`` still count against the independent total
        ceiling, so optional plugins cannot consume the calls required for route,
        clearance, ranking, or track export.
        """

        with self._runtime_lock:
            self._runtime_total_call_count = 0
            self._runtime_budgeted_call_count = 0
            self._runtime_total_call_limit = max(1, min(1024, maximum_total_calls))
            self._runtime_budgeted_call_limit = max(0, min(256, maximum_calls))
            self._runtime_budget_exempt_slots = frozenset(budget_exempt_slot_ids or ())
            self._runtime_timeout_seconds = max(0.1, min(300.0, timeout_seconds))

    def _claim_runtime_call(self, plugin: ToolPlugin[Any, Any]) -> None:
        with self._runtime_lock:
            if self._runtime_total_call_count >= self._runtime_total_call_limit:
                raise RuntimeError("HARNESS_TOTAL_TOOL_CALL_BUDGET_EXCEEDED")
            budget_exempt = plugin.slot_id in self._runtime_budget_exempt_slots
            if (
                not budget_exempt
                and self._runtime_budgeted_call_count >= self._runtime_budgeted_call_limit
            ):
                raise RuntimeError("HARNESS_OPTIONAL_TOOL_CALL_BUDGET_EXCEEDED")
            self._runtime_total_call_count += 1
            if not budget_exempt:
                self._runtime_budgeted_call_count += 1

    def configure_extensions(
        self,
        registry: ExtensionRegistry,
        *,
        receipt_sink: Callable[[list[PluginHookReceipt]], None] | None = None,
    ) -> None:
        self._extensions = registry
        self._hook_receipt_sink = receipt_sink

    def _middleware(
        self, hook: str, value: Any, *, plugin: ToolPlugin
    ) -> tuple[Any, PluginHookReceipt | None]:
        if self._extensions is None:
            return value, None
        try:
            output, receipts = self._extensions.invoke_pipeline(
                "tools.middleware",
                hook,
                value,
                tool={
                    "tool_id": plugin.tool_id,
                    "plugin_id": plugin.plugin_id,
                    "authority": plugin.authority,
                    "slot_id": plugin.slot_id,
                },
            )
        except ExtensionExecutionError as error:
            if self._hook_receipt_sink is not None:
                self._hook_receipt_sink([error.receipt])
            return None, error.receipt
        if self._hook_receipt_sink is not None and receipts:
            self._hook_receipt_sink(receipts)
        return output, None

    def register(self, plugin: ToolPlugin) -> None:
        if plugin.tool_id in self._plugins:
            raise ValueError(f"duplicate tool id: {plugin.tool_id}")
        self._plugins[plugin.tool_id] = plugin

    def _execution_policy(self, plugin: ToolPlugin) -> dict[str, object]:
        if self._extensions is None:
            return {"maximum_attempts": 1, "cache": False, "parallelism": 1}
        try:
            output, receipts = self._extensions.invoke_single(
                "tools.execution-policy",
                "resolve_tool_execution",
                required=True,
                tool={
                    "tool_id": plugin.tool_id,
                    "plugin_id": plugin.plugin_id,
                    "authority": plugin.authority,
                    "slot_id": plugin.slot_id,
                },
            )
        except ExtensionExecutionError as error:
            if self._hook_receipt_sink is not None:
                self._hook_receipt_sink([error.receipt])
            raise RuntimeError("TOOL_EXECUTION_POLICY_FAILED") from error
        if self._hook_receipt_sink is not None and receipts:
            self._hook_receipt_sink(receipts)
        if not isinstance(output, dict):
            raise RuntimeError("TOOL_EXECUTION_POLICY_INVALID")
        return output

    def call_batch(
        self, calls: list[tuple[str, BaseModel | dict[str, object]]]
    ) -> list[tuple[BaseModel | dict[str, object], ToolReceipt]]:
        if not calls:
            return []
        maximum = 1
        for tool_id, _value in calls:
            plugin = self._plugins.get(tool_id)
            if plugin is None:
                raise KeyError(f"unknown tool: {tool_id}")
            maximum = max(maximum, int(self._execution_policy(plugin).get("parallelism", 1)))
        with ThreadPoolExecutor(max_workers=min(maximum, len(calls), 8)) as executor:
            futures = [executor.submit(self.call, tool_id, value) for tool_id, value in calls]
            return [future.result() for future in futures]

    def tool_for_slot(self, slot_id: str) -> str:
        matches = self.tool_ids_for_slot(slot_id)
        if len(matches) != 1:
            raise KeyError(f"plugin slot {slot_id} has {len(matches)} active implementations")
        return matches[0]

    def tool_ids_for_slot(self, slot_id: str) -> list[str]:
        return sorted(
            plugin.tool_id for plugin in self._plugins.values() if plugin.slot_id == slot_id
        )

    def call_slot(
        self, slot_id: str, value: BaseModel | dict[str, object]
    ) -> tuple[BaseModel | dict[str, object], ToolReceipt]:
        return self.call(self.tool_for_slot(slot_id), value)

    def catalog(self) -> list[dict[str, object]]:
        return [
            {
                "tool_id": plugin.tool_id,
                "version": plugin.version,
                "authority": plugin.authority,
                "plugin_id": plugin.plugin_id,
                "plugin_package_sha256": plugin.plugin_package_sha256,
                "routing_metadata": plugin.routing_metadata,
                "slot_id": plugin.slot_id,
                "input_schema": plugin.resolved_input_schema(),
                "output_schema": plugin.resolved_output_schema(),
            }
            for plugin in sorted(self._plugins.values(), key=lambda value: value.tool_id)
        ]

    def call(
        self, tool_id: str, value: BaseModel | dict[str, object]
    ) -> tuple[BaseModel | dict[str, object], ToolReceipt]:
        plugin = self._plugins.get(tool_id)
        if plugin is None:
            raise KeyError(f"unknown tool: {tool_id}")
        self._claim_runtime_call(plugin)
        raw_input = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        policy = self._execution_policy(plugin)
        raw_input, middleware_failure = self._middleware(
            "before_tool_call", raw_input, plugin=plugin
        )
        if middleware_failure is not None:
            input_hash = middleware_failure.input_sha256
            raise ToolExecutionError(
                ToolReceipt(
                    call_id=f"tool-{uuid4().hex[:24]}",
                    tool_id=plugin.tool_id,
                    tool_version=plugin.version,
                    plugin_id=plugin.plugin_id,
                    plugin_package_sha256=plugin.plugin_package_sha256,
                    outcome="rejected",
                    input_sha256=input_hash,
                    output_sha256=sha256_json({}),
                    output={},
                    issue_codes=middleware_failure.issue_codes,
                )
            )
        input_hash = sha256_json(raw_input)
        cache_key = sha256_json(
            {"tool_id": plugin.tool_id, "version": plugin.version, "input": raw_input}
        )
        if policy.get("cache") is True and plugin.authority in {"read", "plan"}:
            with self._cache_lock:
                cached = self._cache.get(cache_key)
            if cached is not None:
                output_payload = dict(cached)
                output = (
                    plugin.output_type.model_validate(output_payload)
                    if plugin.output_type is not None
                    else output_payload
                )
                return output, ToolReceipt(
                    call_id=f"tool-{uuid4().hex[:24]}",
                    tool_id=plugin.tool_id,
                    tool_version=plugin.version,
                    plugin_id=plugin.plugin_id,
                    plugin_package_sha256=plugin.plugin_package_sha256,
                    outcome="accepted",
                    input_sha256=input_hash,
                    output_sha256=sha256_json(output_payload),
                    output=output_payload,
                    issue_codes=["CACHE_HIT"],
                )

        def failed(issue_code: str, *, outcome: str = "failed") -> ToolExecutionError:
            return ToolExecutionError(
                ToolReceipt(
                    call_id=f"tool-{uuid4().hex[:24]}",
                    tool_id=plugin.tool_id,
                    tool_version=plugin.version,
                    plugin_id=plugin.plugin_id,
                    plugin_package_sha256=plugin.plugin_package_sha256,
                    outcome=outcome,
                    input_sha256=input_hash,
                    output_sha256=sha256_json({}),
                    output={},
                    issue_codes=[issue_code],
                )
            )

        if plugin.authority not in self._allowed:
            raise failed("AUTHORITY_NOT_GRANTED", outcome="rejected")
        try:
            if len(canonical_json(raw_input).encode("utf-8")) > 256 * 1024:
                raise ValueError("TOOL_INPUT_TOO_LARGE")
            if plugin.input_type is not None:
                validated_input: BaseModel | dict[str, object] = plugin.input_type.model_validate(
                    value
                )
            else:
                jsonschema.validate(raw_input, plugin.resolved_input_schema())
                if not isinstance(raw_input, dict):
                    raise ValueError("tool input schema must describe an object")
                validated_input = raw_input
        except Exception as error:
            raise failed(f"TOOL_INPUT_INVALID:{type(error).__name__}"[:96]) from error
        try:
            maximum_attempts = max(1, min(3, int(policy.get("maximum_attempts", 1))))
            last_error: Exception | None = None
            raw_output: Any = None
            for _attempt in range(maximum_attempts):
                try:
                    executor = ThreadPoolExecutor(max_workers=1)
                    future = executor.submit(plugin.handler, validated_input)
                    try:
                        raw_output = future.result(timeout=self._runtime_timeout_seconds)
                    finally:
                        executor.shutdown(wait=False, cancel_futures=True)
                    last_error = None
                    break
                except Exception as error:
                    last_error = error
            if last_error is not None:
                raise last_error
            if plugin.output_type is not None:
                output: BaseModel | dict[str, object] = plugin.output_type.model_validate(
                    raw_output
                )
                payload = output.model_dump(mode="json")
            else:
                payload = (
                    raw_output.model_dump(mode="json")
                    if isinstance(raw_output, BaseModel)
                    else raw_output
                )
                jsonschema.validate(payload, plugin.resolved_output_schema())
                if not isinstance(payload, dict):
                    raise ValueError("tool output schema must describe an object")
                output = payload
            if policy.get("cache") is True and plugin.authority in {"read", "plan"}:
                with self._cache_lock:
                    self._cache[cache_key] = dict(payload)
            if len(canonical_json(payload).encode("utf-8")) > 1024 * 1024:
                raise ValueError("TOOL_OUTPUT_TOO_LARGE")
            payload, middleware_failure = self._middleware(
                "after_tool_call", payload, plugin=plugin
            )
            if middleware_failure is not None:
                raise ValueError(middleware_failure.issue_codes[0])
            if plugin.output_type is not None:
                output = plugin.output_type.model_validate(payload)
            else:
                jsonschema.validate(payload, plugin.resolved_output_schema())
                output = payload
        except Exception as error:
            raise failed(f"TOOL_EXECUTION_FAILED:{type(error).__name__}"[:96]) from error
        receipt = ToolReceipt(
            call_id=f"tool-{uuid4().hex[:24]}",
            tool_id=plugin.tool_id,
            tool_version=plugin.version,
            plugin_id=plugin.plugin_id,
            plugin_package_sha256=plugin.plugin_package_sha256,
            outcome="accepted",
            input_sha256=input_hash,
            output_sha256=sha256_json(output),
            output=payload,
        )
        return output, receipt
