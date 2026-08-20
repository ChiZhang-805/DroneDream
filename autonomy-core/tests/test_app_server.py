from __future__ import annotations

import hashlib
import io
import json
import zipfile

from fastapi.testclient import TestClient

from dronedream_agent_app.server import create_app
from dronedream_agent_app.storage import AppStore


class _MemoryVault:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def put(self, name: str, secret: str) -> None:
        self.values[name] = secret

    def get(self, name: str) -> str:
        return self.values[name]

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def _ui_plugin_bundle(version: str) -> bytes:
    panel = b'{"title":"Mission audit"}\n'
    manifest = {
        "schema_version": "dronedream.plugin-manifest.v1",
        "plugin_id": "example.mission-audit",
        "name": "Mission Audit",
        "version": version,
        "description": "Inspect immutable mission evidence.",
        "publisher": "Example",
        "api_version": "1.0",
        "minimum_app_version": "0.1.0",
        "runtime": {"kind": "ui-declarative"},
        "capabilities": [
            {
                "capability_id": "example.mission-audit.panel",
                "kind": "ui-panel",
                "name": "Mission Audit",
                "description": "Show mission evidence.",
                "authority": "read",
                "metadata": {"entrypoint": "ui/panel.json"},
            }
        ],
        "permissions": ["mission.read", "ui.panel"],
        "file_sha256": {"ui/panel.json": hashlib.sha256(panel).hexdigest()},
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("plugin.json", json.dumps(manifest))
        archive.writestr("ui/panel.json", panel)
    return output.getvalue()


def test_loopback_api_requires_random_session_token(tmp_path):
    token = "a" * 64
    client = TestClient(create_app(store=AppStore(tmp_path), token=token))

    assert client.get("/health").status_code == 200
    assert client.get("/v1/bootstrap").status_code == 401
    response = client.get("/v1/bootstrap", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert len(response.json()["models"]) == 7


def test_attachment_is_bound_to_its_task_thread(tmp_path):
    token = "b" * 64
    client = TestClient(create_app(store=AppStore(tmp_path), token=token))
    headers = {"Authorization": f"Bearer {token}"}
    thread = client.post(
        "/v1/threads",
        headers=headers,
        json={"title": "附件任务", "selected_model": "gpt-5.4"},
    ).json()

    response = client.post(
        f"/v1/threads/{thread['thread_id']}/attachments",
        headers=headers,
        files={"attachment": ("requirements.md", "到保安亭取外卖", "text/markdown")},
    )

    assert response.status_code == 201
    assert response.json()["thread_id"] == thread["thread_id"]
    assert response.json()["extracted_text"] == "到保安亭取外卖"


def test_connector_credential_api_never_returns_secret(tmp_path):
    token = "d" * 64
    headers = {"Authorization": f"Bearer {token}"}
    vault = _MemoryVault()
    client = TestClient(
        create_app(
            store=AppStore(tmp_path),
            token=token,
            connector_credential_vault=vault,
        )
    )

    response = client.post(
        "/v1/connector-credentials",
        headers=headers,
        json={
            "display_name": "PagerDuty",
            "secret": "pd-secret-value",
            "allowed_plugin_ids": ["connector.alerts.pagerduty"],
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert "pd-secret-value" not in response.text
    assert vault.values[created["reference"]] == "pd-secret-value"
    bootstrap = client.get("/v1/bootstrap", headers=headers)
    assert "pd-secret-value" not in bootstrap.text
    assert bootstrap.json()["connector_credentials"][0]["allowed_plugin_ids"] == [
        "connector.alerts.pagerduty"
    ]
    removed = client.delete(f"/v1/connector-credentials/{created['reference']}", headers=headers)
    assert removed.status_code == 200
    assert created["reference"] not in vault.values


def test_plugin_api_is_authenticated_transactional_and_versioned(tmp_path):
    token = "c" * 64
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(create_app(store=AppStore(tmp_path), token=token))

    assert client.get("/v1/plugins", headers=headers).status_code == 200
    protected = client.post("/v1/plugins/runtime.safe-hold/disable", headers=headers)
    assert protected.status_code == 409

    disabled = client.post("/v1/plugins/model.kimi/disable", headers=headers)
    assert disabled.status_code == 200
    assert len(client.get("/v1/bootstrap", headers=headers).json()["models"]) == 5

    imported = client.post(
        "/v1/plugins/import",
        headers=headers,
        files={"bundle": ("mission-audit.zip", _ui_plugin_bundle("1.0.0"), "application/zip")},
    )
    assert imported.status_code == 201
    assert imported.json()["version"] == "1.0.0"
    assert (
        client.post(
            "/v1/plugins/example.mission-audit/trust-local-package", headers=headers
        ).status_code
        == 200
    )
    assert (
        client.post("/v1/plugins/example.mission-audit/enable", headers=headers).status_code == 200
    )
    panel = client.get("/v1/plugins/example.mission-audit/panel", headers=headers)
    assert panel.status_code == 200
    assert panel.json()["title"] == "Mission audit"

    staged = client.post(
        "/v1/plugins/import",
        headers=headers,
        files={"bundle": ("mission-audit.zip", _ui_plugin_bundle("1.1.0"), "application/zip")},
    )
    assert staged.status_code == 201
    assert staged.json()["staged_version"] == "1.1.0"

    activated = client.post(
        "/v1/plugins/example.mission-audit/activate",
        headers=headers,
        json={"version": "1.1.0"},
    )
    assert activated.status_code == 200
    detail = client.get("/v1/plugins/example.mission-audit", headers=headers).json()
    assert detail["version"] == "1.1.0"
    assert len(detail["versions"]) == 2
    assert detail["events"]

    removed = client.delete("/v1/plugins/example.mission-audit", headers=headers)
    assert removed.status_code == 200
    assert removed.json()["status"] == "uninstalled"
