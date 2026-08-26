from __future__ import annotations

import sys
from pathlib import Path

import pytest

import dronedream_agent_core.capability_broker as broker_module
from dronedream_agent_core.capability_broker import (
    CapabilityBrokerError,
    CapabilityBrokerHostServices,
    CoreCapabilityBroker,
)
from dronedream_agent_core.plugin_contracts import (
    CapabilityBrokerReceipt,
    PluginManifest,
)


class _CredentialResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def resolve(self, reference: str, *, plugin_id: str) -> str:
        self.calls.append((reference, plugin_id))
        return "test-secret-never-returned-to-plugin"


class _Headers:
    def items(self):
        return [("content-type", "application/json"), ("set-cookie", "secret-cookie")]


class _Response:
    status = 200
    headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _maximum: int) -> bytes:
        return b'{"ok":true}'


class _Opener:
    def __init__(self) -> None:
        self.authorization = ""

    def open(self, request, *, timeout: float):
        assert timeout > 0
        self.authorization = request.get_header("Authorization")
        return _Response()


def _manifest(
    *,
    permissions: list[str],
    hosts: list[str] | None = None,
) -> PluginManifest:
    return PluginManifest.model_validate(
        {
            "plugin_id": "test.capability-client",
            "name": "Capability client",
            "version": "1.0.0",
            "description": "Exercises the core-owned capability broker.",
            "publisher": "DroneDream",
            "runtime": {
                "kind": "builtin-python",
                "entrypoint": "tests.test_capability_broker:definition",
            },
            "resource_policy": {
                "maximum_message_bytes": 4096,
                "allowed_network_hosts": hosts or [],
            },
            "capabilities": [
                {
                    "capability_id": "test.capability-client.invoke",
                    "kind": "tool",
                    "name": "Invoke",
                    "description": "Invoke a broker capability.",
                    "authority": "read",
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                }
            ],
            "permissions": permissions,
        }
    )


def test_filesystem_access_is_root_scoped_and_receipted(tmp_path: Path):
    assets = tmp_path / "assets"
    output = tmp_path / "output"
    assets.mkdir()
    (assets / "map.json").write_text('{"map":true}', encoding="utf-8")
    receipts: list[CapabilityBrokerReceipt] = []
    core = CoreCapabilityBroker(
        read_roots={"assets": assets},
        write_roots={"output": output},
        receipt_sink=receipts.append,
    )
    scoped = core.scope(_manifest(permissions=["asset.read", "mission.write-output"]))

    assert scoped.read_bytes("assets", "map.json") == b'{"map":true}'
    scoped.write_bytes("output", "nested/result.json", b'{"accepted":true}')
    assert (output / "nested" / "result.json").read_bytes() == b'{"accepted":true}'
    with pytest.raises(CapabilityBrokerError, match="BROKER_PATH_INVALID"):
        scoped.read_bytes("assets", "../outside.txt")
    assert [item.operation for item in receipts[:2]] == [
        "filesystem.read",
        "filesystem.write",
    ]
    assert all("map.json" not in item.model_dump_json() for item in receipts)


def test_permission_is_enforced_at_call_time(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "map.json").write_text("{}", encoding="utf-8")
    scoped = CoreCapabilityBroker(read_roots={"assets": assets}).scope(_manifest(permissions=[]))
    with pytest.raises(CapabilityBrokerError, match="BROKER_PERMISSION_DENIED"):
        scoped.read_bytes("assets", "map.json")


def test_network_broker_injects_opaque_credential_and_strips_sensitive_headers(
    monkeypatch: pytest.MonkeyPatch,
):
    resolver = _CredentialResolver()
    receipts: list[CapabilityBrokerReceipt] = []
    opener = _Opener()
    monkeypatch.setattr(
        broker_module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(broker_module, "build_opener", lambda *_args: opener)
    scoped = CoreCapabilityBroker(credential_resolver=resolver, receipt_sink=receipts.append).scope(
        _manifest(
            permissions=["network.external", "credential.reference"],
            hosts=["api.example.com"],
        )
    )

    response = scoped.request(
        "GET",
        "https://api.example.com/weather",
        credential_reference="weather-primary",
    )
    assert response.json() == {"ok": True}
    assert "set-cookie" not in response.headers
    assert resolver.calls == [("weather-primary", "test.capability-client")]
    assert opener.authorization == "Bearer test-secret-never-returned-to-plugin"
    assert all("test-secret" not in item.model_dump_json() for item in receipts)


def test_network_broker_denies_private_addresses(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        broker_module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    scoped = CoreCapabilityBroker().scope(
        _manifest(permissions=["network.external"], hosts=["metadata.example.com"])
    )
    with pytest.raises(CapabilityBrokerError, match="BROKER_NETWORK_PRIVATE_ADDRESS_DENIED"):
        scoped.request("GET", "https://metadata.example.com/latest")


def test_process_broker_uses_exact_executable_without_shell(tmp_path: Path):
    executable = Path(sys.executable)
    scoped = CoreCapabilityBroker(allowed_executables={"python": executable}).scope(
        _manifest(permissions=["process.spawn"])
    )
    result = scoped.spawn("python", ["-c", "print('broker-ok')"])
    assert result.returncode == 0
    assert result.stdout.strip() == "broker-ok"


def test_mcp_host_service_returns_only_encoded_file_bytes(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "semantic.json").write_bytes(b'{"safe":true}')
    host = CapabilityBrokerHostServices(
        CoreCapabilityBroker(read_roots={"assets": assets}).scope(
            _manifest(permissions=["asset.read"])
        )
    )

    result = host(
        "dronedream/filesystem/read",
        {"root": "assets", "path": "semantic.json"},
    )

    assert result == {"body_base64": "eyJzYWZlIjp0cnVlfQ=="}
    with pytest.raises(CapabilityBrokerError, match="BROKER_METHOD_DENIED"):
        host("dronedream/credential/read", {})
