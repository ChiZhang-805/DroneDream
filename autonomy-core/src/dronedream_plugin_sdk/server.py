"""Small dependency-light MCP server with schema validation and cancellation."""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jsonschema


@dataclass(frozen=True)
class ToolContext:
    request_id: str
    cancelled: threading.Event
    configuration: dict[str, Any]
    _notify: Callable[[dict[str, Any]], None] = field(repr=False)

    def progress(self, progress: float, message: str = "") -> None:
        self._notify(
            {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {
                    "requestId": self.request_id,
                    "progress": max(0.0, min(1.0, float(progress))),
                    "message": message[:300],
                },
            }
        )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: Callable[[dict[str, Any], ToolContext], dict[str, Any]]


class McpPluginServer:
    """Serve declared tools over newline-delimited MCP JSON-RPC."""

    def __init__(self, *, name: str, version: str, tools: list[ToolSpec]) -> None:
        self.name = name
        self.version = version
        self.tools = {tool.name: tool for tool in tools}
        if len(self.tools) != len(tools):
            raise ValueError("duplicate tool name")
        for tool in tools:
            jsonschema.validators.validator_for(tool.input_schema).check_schema(tool.input_schema)
            jsonschema.validators.validator_for(tool.output_schema).check_schema(tool.output_schema)
        self.configuration: dict[str, Any] = {}
        self._cancelled: dict[str, threading.Event] = {}
        self._write_lock = threading.Lock()

    def _write(self, value: dict[str, Any]) -> None:
        rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            sys.stdout.write(rendered + "\n")
            sys.stdout.flush()

    def _result(self, request_id: object, result: object) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _error(self, request_id: object, code: int, message: str) -> None:
        self._write(
            {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
        )

    def _call_tool(self, request_id: str, params: dict[str, Any]) -> None:
        name = params.get("name")
        arguments = params.get("arguments", {})
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None or not isinstance(arguments, dict):
            return self._error(request_id, -32602, "TOOL_CALL_INVALID")
        cancellation = threading.Event()
        self._cancelled[request_id] = cancellation
        try:
            jsonschema.validate(arguments, tool.input_schema)
            output = tool.handler(
                arguments,
                ToolContext(request_id, cancellation, dict(self.configuration), self._write),
            )
            if cancellation.is_set():
                return self._error(request_id, -32800, "REQUEST_CANCELLED")
            jsonschema.validate(output, tool.output_schema)
            self._result(
                request_id,
                {
                    "content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False)}],
                    "structuredContent": output,
                    "isError": False,
                },
            )
        except jsonschema.ValidationError:
            self._error(request_id, -32602, "TOOL_SCHEMA_VALIDATION_FAILED")
        except Exception as error:
            self._error(request_id, -32000, f"TOOL_EXECUTION_FAILED:{type(error).__name__}")
        finally:
            self._cancelled.pop(request_id, None)

    def dispatch(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params", {})
        if method == "notifications/cancelled" and isinstance(params, dict):
            cancelled = self._cancelled.get(str(params.get("requestId", "")))
            if cancelled is not None:
                cancelled.set()
            return
        if method == "notifications/initialized":
            return
        if request_id is None:
            return
        if method == "initialize":
            options = params.get("initializationOptions", {}) if isinstance(params, dict) else {}
            configuration = options.get("configuration", {}) if isinstance(options, dict) else {}
            self.configuration = configuration if isinstance(configuration, dict) else {}
            return self._result(
                request_id,
                {
                    "protocolVersion": "dronedream.plugin.v1",
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": self.name, "version": self.version},
                },
            )
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            return self._result(
                request_id,
                {
                    "tools": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": tool.input_schema,
                            "outputSchema": tool.output_schema,
                        }
                        for tool in self.tools.values()
                    ]
                },
            )
        if method == "tools/call" and isinstance(params, dict):
            return self._call_tool(str(request_id), params)
        if method == "resources/list":
            return self._result(request_id, {"resources": []})
        self._error(request_id, -32601, "METHOD_NOT_FOUND")

    def run(self) -> None:
        for line in sys.stdin:
            try:
                message = json.loads(line)
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise ValueError
                self.dispatch(message)
            except (ValueError, json.JSONDecodeError):
                self._error(None, -32700, "PARSE_ERROR")
