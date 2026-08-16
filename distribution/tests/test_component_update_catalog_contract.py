from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "distribution/schemas/component-update-catalog.schema.json"
KEYRING_PATH = ROOT / "distribution/desktop/component-release-public-keys.json"
POLICY_PATH = ROOT / "distribution/desktop/component-update-policy.v1.json"
BUILD_PATH = ROOT / "desktop/src-tauri/build.rs"
PRODUCTION_ENV_PATH = ROOT / "frontend/.env.production"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_catalog_schema_is_closed_and_excludes_user_state() -> None:
    schema = _json(SCHEMA_PATH)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    components = schema["properties"]["components"]
    assert components["maxItems"] == 2
    candidate = components["items"]
    assert candidate["additionalProperties"] is False
    assert set(candidate["required"]) == set(candidate["properties"])
    assert candidate["properties"]["componentId"]["enum"] == [
        "capability-pack",
        "asset-pack",
    ]
    assert "user-state" not in json.dumps(schema)


def test_catalog_artifacts_are_https_hash_and_size_bound() -> None:
    schema = _json(SCHEMA_PATH)
    artifact = schema["$defs"]["artifact"]
    assert artifact["additionalProperties"] is False
    assert set(artifact["required"]) == {"url", "sizeBytes", "sha256"}
    assert artifact["properties"]["url"]["pattern"] == "^https://"
    assert artifact["properties"]["sizeBytes"]["maximum"] == 4 * 1024**3
    assert artifact["properties"]["sha256"]["pattern"] == "^[0-9a-f]{64}$"


def test_component_catalog_key_identity_is_self_authenticating_and_domain_scoped() -> None:
    keyring = _json(KEYRING_PATH)
    assert keyring["schemaVersion"] == 1
    assert len(keyring["keys"]) == 1
    key = keyring["keys"][0]
    public_key = base64.b64decode(key["publicKeyBase64"], validate=True)
    assert len(public_key) == 32
    assert key["keyId"] == f"ed25519:{hashlib.sha256(public_key).hexdigest()}"
    assert key["algorithm"] == "Ed25519"
    assert key["status"] == "active"
    assert key["usage"] == "component-catalog"


def test_only_catalog_supported_packs_use_the_native_manager() -> None:
    policy = _json(POLICY_PATH)
    components = {entry["componentId"]: entry for entry in policy["components"]}
    assert components["capability-pack"]["updateMechanism"] == "component-pack-manager"
    assert components["asset-pack"]["updateMechanism"] == "component-pack-manager"
    assert components["user-state"]["updateMechanism"] == "none"
    assert components["user-state"]["rollbackStrategy"] == "never-touch"


def test_production_catalog_endpoint_is_public_build_configuration() -> None:
    build = BUILD_PATH.read_text(encoding="utf-8")
    production_env = PRODUCTION_ENV_PATH.read_text(encoding="utf-8")
    assert "VITE_COMPONENT_UPDATE_CATALOG_URL" in build
    assert "DRONEDREAM_PRODUCTION_COMPONENT_CATALOG_URL" in build
    assert (
        "VITE_COMPONENT_UPDATE_CATALOG_URL=https://getdronedream.com/"
        "releases/components/stable/catalog.json"
    ) in production_env
