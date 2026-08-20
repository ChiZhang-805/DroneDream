"""Scaffolding, deterministic packaging, signing, and local plugin sandbox."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from dronedream_agent_app.plugin_manager import PluginManager
from dronedream_agent_app.storage import AppStore

from .plugin_contracts import PluginManifest
from .plugin_panels import validate_panel_document
from .plugin_trust import unsigned_manifest_sha256

_IGNORED_PARTS = frozenset({".git", ".venv", "build", "dist", "__pycache__", ".pytest_cache"})


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def scaffold_plugin(
    root: Path,
    *,
    plugin_id: str,
    name: str,
    publisher: str,
    kind: Literal["mcp", "ui"] = "mcp",
) -> Path:
    if root.exists() and any(root.iterdir()):
        raise ValueError("PLUGIN_SCAFFOLD_DIRECTORY_NOT_EMPTY")
    root.mkdir(parents=True, exist_ok=True)
    capability_id = f"{plugin_id}.inspect"
    if kind == "ui":
        panel = {
            "schema_version": "dronedream.ui-panel.v1",
            "title": name,
            "sections": [
                {
                    "section_id": "status",
                    "title": "状态",
                    "widgets": [
                        {
                            "widget_id": "plugin-health",
                            "kind": "status",
                            "label": "健康",
                            "source": "plugin",
                            "path": "health",
                        }
                    ],
                    "actions": [{"action_id": "plugin.healthcheck", "label": "健康检查"}],
                }
            ],
        }
        _write_json(root / "ui" / "panel.json", panel)
        manifest: dict[str, Any] = {
            "plugin_id": plugin_id,
            "name": name,
            "version": "0.1.0",
            "description": f"{name} declarative panel.",
            "publisher": publisher,
            "runtime": {"kind": "ui-declarative"},
            "capabilities": [
                {
                    "capability_id": capability_id,
                    "kind": "ui-panel",
                    "name": name,
                    "description": f"Render {name} without executable UI code.",
                    "authority": "read",
                    "metadata": {"entrypoint": "ui/panel.json"},
                }
            ],
            "permissions": ["ui.panel"],
            "placement": {
                "category_id": "general",
                "category_label": "通用",
                "slot_id": "general.panels",
                "slot_label": "面板",
                "activation_mode": "multiple",
                "scope": "interface",
                "failure_mode": "isolate",
                "swap_policy": "anytime",
            },
        }
    else:
        server_source = (
            "from dronedream_plugin_sdk import McpPluginServer, ToolContext, ToolSpec\n\n"
            'INPUT = {"type": "object", "additionalProperties": False, '
            '"properties": {"text": {"type": "string"}}}\n'
            'OUTPUT = {"type": "object", "additionalProperties": False, '
            '"required": ["accepted"], "properties": {"accepted": {"type": "boolean"}, '
            '"echo": {"type": "string"}}}\n\n'
            "def inspect(value: dict, context: ToolContext) -> dict:\n"
            '    context.progress(0.5, "inspecting")\n'
            '    return {"accepted": True, "echo": str(value.get("text", ""))}\n\n'
            f'McpPluginServer(name={name!r}, version="0.1.0", tools=[\n'
            f'    ToolSpec(name={capability_id!r}, description="Inspect a bounded input.",\n'
            "             input_schema=INPUT, output_schema=OUTPUT, handler=inspect)\n"
            "]).run()\n"
        )
        (root / "plugin_server.py").write_text(server_source, encoding="utf-8")
        (root / "build.ps1").write_text(
            "$ErrorActionPreference='Stop'\n"
            "python -m PyInstaller --onefile --name plugin plugin_server.py "
            "--distpath bin --workpath build --specpath build\n",
            encoding="utf-8",
        )
        manifest = {
            "plugin_id": plugin_id,
            "name": name,
            "version": "0.1.0",
            "description": f"{name} MCP tool.",
            "publisher": publisher,
            "runtime": {"kind": "mcp-stdio", "command": ["bin/plugin.exe"]},
            "capabilities": [
                {
                    "capability_id": capability_id,
                    "kind": "tool",
                    "name": name,
                    "description": "Inspect a bounded input.",
                    "authority": "read",
                    "input_schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"text": {"type": "string"}},
                    },
                    "output_schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["accepted"],
                        "properties": {
                            "accepted": {"type": "boolean"},
                            "echo": {"type": "string"},
                        },
                    },
                }
            ],
            "permissions": ["process.spawn", "mission.read"],
            "placement": {
                "category_id": "tools",
                "category_label": "工具",
                "slot_id": "tools.external",
                "slot_label": "外部工具",
                "activation_mode": "multiple",
                "scope": "mission",
                "failure_mode": "isolate",
                "swap_policy": "next-mission",
            },
        }
    _write_json(root / "plugin.json", manifest)
    (root / "README.md").write_text(
        f"# {name}\n\nValidate, package, and sandbox with `dronedream-plugin`.\n",
        encoding="utf-8",
    )
    return root


def _package_files(root: Path) -> dict[str, bytes]:
    values: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "plugin.json":
            continue
        relative = path.relative_to(root)
        if any(part in _IGNORED_PARTS for part in relative.parts):
            continue
        if path.name.endswith((".key", ".pem")) or path.name == "publisher-key.json":
            continue
        values[relative.as_posix()] = path.read_bytes()
    return values


def generate_publisher_key(path: Path, *, key_id: str, publisher: str) -> dict[str, str]:
    if path.exists():
        raise ValueError("PLUGIN_PUBLISHER_KEY_EXISTS")
    private = Ed25519PrivateKey.generate()
    private_bytes = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_bytes = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    payload = {
        "schema_version": "dronedream.publisher-key.v1",
        "key_id": key_id,
        "publisher": publisher,
        "private_key_base64": base64.b64encode(private_bytes).decode("ascii"),
        "public_key_base64": base64.b64encode(public_bytes).decode("ascii"),
    }
    _write_json(path, payload)
    return {key: value for key, value in payload.items() if key != "private_key_base64"}


def _load_signing_key(path: Path) -> tuple[str, str, Ed25519PrivateKey]:
    value = json.loads(path.read_text(encoding="utf-8"))
    private = Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(str(value["private_key_base64"]), validate=True)
    )
    return str(value["key_id"]), str(value["publisher"]), private


def build_plugin_bundle(
    root: Path, output: Path, *, signing_key: Path | None = None
) -> dict[str, object]:
    raw = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("PLUGIN_MANIFEST_INVALID")
    files = _package_files(root)
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": raw.get("name"),
                "version": raw.get("version"),
            }
        },
        "components": [],
    }
    files["sbom.cdx.json"] = (
        json.dumps(sbom, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    raw["file_sha256"] = {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}
    provenance = dict(raw.get("provenance", {}))
    provenance.update(
        {
            "build_system": "dronedream-plugin-sdk",
            "build_timestamp": datetime.now(UTC).isoformat(),
            "sbom_sha256": raw["file_sha256"]["sbom.cdx.json"],
        }
    )
    raw["provenance"] = provenance
    raw.pop("signature", None)
    manifest = PluginManifest.model_validate(raw)
    if manifest.runtime.kind == "ui-declarative":
        panel_entrypoints = [
            item.metadata.get("entrypoint")
            for item in manifest.capabilities
            if item.kind == "ui-panel"
        ]
        for entrypoint in panel_entrypoints:
            if isinstance(entrypoint, str):
                validate_panel_document(json.loads(files[entrypoint]))
    if signing_key is not None:
        key_id, publisher, private = _load_signing_key(signing_key)
        if publisher != manifest.publisher:
            raise ValueError("PLUGIN_SIGNING_PUBLISHER_MISMATCH")
        digest = unsigned_manifest_sha256(manifest)
        raw["signature"] = {
            "algorithm": "ed25519",
            "publisher_key_id": key_id,
            "signed_manifest_sha256": digest,
            "signature_base64": base64.b64encode(private.sign(bytes.fromhex(digest))).decode(),
            "signed_at": datetime.now(UTC).isoformat(),
        }
        manifest = PluginManifest.model_validate(raw)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, value in {
            "plugin.json": (manifest.model_dump_json(indent=2) + "\n").encode(),
            **files,
        }.items():
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, value)
    return {
        "plugin_id": manifest.plugin_id,
        "version": manifest.version,
        "output": str(output.resolve()),
        "package_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "signed": manifest.signature is not None,
        "files": len(files),
    }


def validate_plugin_source(root: Path) -> dict[str, object]:
    manifest = PluginManifest.model_validate_json(
        (root / "plugin.json").read_text(encoding="utf-8")
    )
    files = _package_files(root)
    missing_runtime: list[str] = []
    if (
        manifest.runtime.kind == "mcp-stdio"
        and manifest.runtime.command
        and manifest.runtime.command[0] not in files
    ):
        missing_runtime.append(manifest.runtime.command[0])
    return {
        "plugin_id": manifest.plugin_id,
        "version": manifest.version,
        "runtime_kind": manifest.runtime.kind,
        "capabilities": len(manifest.capabilities),
        "files": len(files),
        "ready_to_package": not missing_runtime,
        "missing_runtime": missing_runtime,
    }


def sandbox_plugin_bundle(bundle: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="dronedream-plugin-sandbox-") as temporary:
        store = AppStore(Path(temporary) / "store")
        manager = PluginManager(store)
        try:
            imported = manager.import_bundle(bundle)
            plugin_id = str(imported["plugin_id"])
            manager.approve_local_package(plugin_id)
            manager.enable(plugin_id)
            checked = manager.healthcheck(plugin_id)
            manager.disable(plugin_id)
            return {
                "plugin_id": plugin_id,
                "version": imported["version"],
                "health": checked["health"],
                "quarantined": checked["status"] == "quarantined",
                "lifecycle_events": len(store.list_plugin_events(plugin_id)),
            }
        finally:
            manager.close()
            store.close()
