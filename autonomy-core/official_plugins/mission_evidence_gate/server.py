"""Standalone MCP stdio plugin for deterministic mission-evidence requirements."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

TOOL_ID = "mission.evidence-requirements"
INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["goal", "payload_action", "constraints", "target_node", "return_node"],
    "properties": {
        "goal": {"type": "string", "minLength": 1, "maxLength": 600},
        "payload_action": {"type": "string", "enum": ["none", "pickup"]},
        "constraints": {
            "type": "array",
            "maxItems": 64,
            "items": {"type": "string", "maxLength": 160},
        },
        "target_node": {"type": "string", "minLength": 1, "maxLength": 160},
        "return_node": {"type": "string", "minLength": 1, "maxLength": 160},
    },
}
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["accepted", "risk_codes", "required_observations", "checklist_sha256"],
    "properties": {
        "accepted": {"type": "boolean"},
        "risk_codes": {
            "type": "array",
            "maxItems": 32,
            "items": {"type": "string", "pattern": "^[A-Z0-9_]+$"},
        },
        "required_observations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "items": {"type": "string", "minLength": 1, "maxLength": 160},
        },
        "checklist_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def evidence_requirements(arguments: dict[str, Any]) -> dict[str, Any]:
    required = [
        "contract and selected-asset hashes remain unchanged",
        "continuous collision and geofence gates remain true",
        "battery reserve stays above the configured threshold",
        "final PX4 state and landing contact are observed",
    ]
    risks = ["ROUTE_AND_ASSET_BINDING", "ENERGY_RESERVE", "VERIFIED_LANDING"]
    if arguments.get("payload_action") == "pickup":
        risks.extend(["PAYLOAD_IDENTITY", "PAYLOAD_ATTACHMENT"])
        required.extend(
            [
                "pickup identity is verified before capture",
                "payload attachment and mass update are observed before return",
            ]
        )
    constraints = {str(value).casefold() for value in arguments.get("constraints", [])}
    if "safety_priority" in constraints:
        risks.append("SAFE_HOLD_ON_INTERRUPTION")
        required.append("runtime amendments establish stable hold before model reasoning")
    if arguments.get("target_node") == arguments.get("return_node"):
        risks.append("ONE_WAY_TARGET_LANDING")
        required.append("target arrival and final landing refer to the same contract node")
    checklist = {"risk_codes": risks, "required_observations": required}
    return {
        "accepted": True,
        **checklist,
        "checklist_sha256": hashlib.sha256(_canonical(checklist).encode()).hexdigest(),
    }


def _manifest(executable_sha256: str, version: str) -> dict[str, Any]:
    return {
        "schema_version": "dronedream.plugin-manifest.v1",
        "plugin_id": "dronedream.mission-evidence-gate",
        "name": "Mission Evidence Gate",
        "version": version,
        "description": "为任务生成可审计的运行证据与风险检查清单。",
        "publisher": "DroneDream",
        "api_version": "1.0",
        "minimum_app_version": "0.1.0",
        "runtime": {
            "kind": "mcp-stdio",
            "command": ["bin/mission-evidence-gate.exe"],
            "protocol_version": "2025-06-18",
            "startup_timeout_seconds": 15,
            "call_timeout_seconds": 30,
        },
        "capabilities": [
            {
                "capability_id": TOOL_ID,
                "kind": "evidence",
                "name": "任务证据检查表",
                "description": "根据冻结任务合同补充运行证据要求，不产生控制指令。",
                "authority": "read",
                "input_schema": INPUT_SCHEMA,
                "output_schema": OUTPUT_SCHEMA,
                "metadata": {"recommended_when": {"payload_action_in": ["pickup"]}},
            }
        ],
        "permissions": ["mission.read", "process.spawn"],
        "file_sha256": {"bin/mission-evidence-gate.exe": executable_sha256},
        "default_enabled": False,
        "removable": True,
        "disable_allowed": True,
        "placement": {
            "category_id": "evidence",
            "category_label": "证据与数据",
            "slot_id": "evidence.advisors",
            "slot_label": "证据增强",
            "activation_mode": "multiple",
            "scope": "mission",
            "category_order": 70,
            "slot_order": 10,
            "plugin_order": 10,
        },
    }


def _response(request_id: object, result: object) -> None:
    sys.stdout.write(_canonical({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n")
    sys.stdout.flush()


def _error(request_id: object, code: int, message: str) -> None:
    value = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    sys.stdout.write(_canonical(value) + "\n")
    sys.stdout.flush()


def serve() -> int:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                continue
            request_id = request.get("id")
            method = request.get("method")
            if request_id is None:
                continue
            if method == "initialize":
                requested = request.get("params", {}).get("protocolVersion", "2025-06-18")
                _response(
                    request_id,
                    {
                        "protocolVersion": requested,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "Mission Evidence Gate", "version": "1.0.0"},
                    },
                )
            elif method == "tools/list":
                _response(
                    request_id,
                    {
                        "tools": [
                            {
                                "name": TOOL_ID,
                                "description": (
                                    "Generate deterministic runtime evidence requirements."
                                ),
                                "inputSchema": INPUT_SCHEMA,
                                "outputSchema": OUTPUT_SCHEMA,
                            }
                        ]
                    },
                )
            elif method == "tools/call":
                params = request.get("params")
                if not isinstance(params, dict) or params.get("name") != TOOL_ID:
                    _error(request_id, -32602, "unknown tool")
                    continue
                arguments = params.get("arguments")
                if not isinstance(arguments, dict):
                    _error(request_id, -32602, "arguments must be an object")
                    continue
                output = evidence_requirements(arguments)
                _response(
                    request_id,
                    {
                        "content": [{"type": "text", "text": _canonical(output)}],
                        "structuredContent": output,
                        "isError": False,
                    },
                )
            else:
                _error(request_id, -32601, "method not found")
        except Exception as error:
            _error(None, -32603, f"internal error: {type(error).__name__}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--manifest-version", default="1.0.0")
    parser.add_argument("--manifest-output")
    args, _unknown = parser.parse_known_args()
    if args.manifest_sha256:
        rendered = json.dumps(
            _manifest(args.manifest_sha256, args.manifest_version), ensure_ascii=False
        )
        if args.manifest_output:
            Path(args.manifest_output).write_text(rendered + "\n", encoding="utf-8", newline="\n")
        else:
            sys.stdout.write(rendered)
        return 0
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
