import base64
import hashlib
import json
import zipfile
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dronedream_agent_app.plugin_manager import PluginManager
from dronedream_agent_app.storage import AppStore
from dronedream_agent_core.plugin_contracts import PluginManifest
from dronedream_agent_core.plugin_trust import unsigned_manifest_sha256


def test_signed_plugin_is_verified_and_exact_package_can_be_revoked(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    executable = b"not executed during trust verification"
    manifest_value = {
        "plugin_id": "example.signed-observer",
        "name": "Signed observer",
        "version": "1.0.0",
        "description": "Trust verification fixture.",
        "publisher": "Example Robotics",
        "runtime": {"kind": "mcp-stdio", "command": ["plugin.exe"]},
        "capabilities": [
            {
                "capability_id": "example.signed-observer.inspect",
                "kind": "tool",
                "name": "Inspect",
                "description": "Inspect a frozen mission.",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            }
        ],
        "permissions": ["process.spawn", "mission.read"],
        "file_sha256": {"plugin.exe": hashlib.sha256(executable).hexdigest()},
    }
    unsigned = PluginManifest.model_validate(manifest_value)
    manifest_sha256 = unsigned_manifest_sha256(unsigned)
    manifest_value["signature"] = {
        "algorithm": "ed25519",
        "publisher_key_id": "example-robotics.release",
        "signed_manifest_sha256": manifest_sha256,
        "signature_base64": base64.b64encode(
            private_key.sign(bytes.fromhex(manifest_sha256))
        ).decode(),
        "signed_at": datetime.now(UTC).isoformat(),
    }
    archive = tmp_path / "signed.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("plugin.json", json.dumps(manifest_value))
        bundle.writestr("plugin.exe", executable)

    manager = PluginManager(AppStore(tmp_path / "store"))
    manager.add_trusted_publisher(
        key_id="example-robotics.release",
        publisher="Example Robotics",
        public_key_base64=base64.b64encode(public_key).decode(),
    )
    installed = manager.import_bundle(archive)
    assert installed["trust_status"] == "verified"
    assert installed["trust_decision"]["publisher_key_id"] == "example-robotics.release"

    revoked = manager.revoke_package("example.signed-observer")
    assert revoked["trust_status"] == "revoked"
