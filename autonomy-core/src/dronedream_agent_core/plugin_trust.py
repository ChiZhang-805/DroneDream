"""Ed25519 publisher trust, exact-package local approval, and revocation checks."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

from .hashing import sha256_json
from .plugin_contracts import PluginManifest


class TrustStoreError(RuntimeError):
    """The trust store or a requested trust transition is invalid."""


class PluginTrustDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["verified", "local-approved", "unverified", "revoked"]
    issue_codes: list[str] = Field(default_factory=list)
    publisher_key_id: str | None = None
    manifest_sha256: str
    package_sha256: str


def unsigned_manifest_sha256(manifest: PluginManifest) -> str:
    payload = manifest.model_dump(mode="json", exclude={"signature"})
    return sha256_json(payload)


class PluginTrustStore:
    """Small durable trust store; approvals are bound to immutable package hashes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(self._empty())

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "schema_version": "dronedream.plugin-trust-store.v1",
            "publishers": {},
            "revoked_publisher_keys": [],
            "revoked_packages": [],
            "revoked_plugins": [],
            "local_approvals": {},
        }

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise TrustStoreError("PLUGIN_TRUST_STORE_INVALID") from error
        if not isinstance(value, dict) or value.get("schema_version") != (
            "dronedream.plugin-trust-store.v1"
        ):
            raise TrustStoreError("PLUGIN_TRUST_STORE_INVALID")
        return value

    def _write(self, value: dict[str, Any]) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".plugin-trust-", suffix=".json", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def add_publisher(
        self,
        *,
        key_id: str,
        publisher: str,
        public_key_base64: str,
    ) -> None:
        try:
            public_key = base64.b64decode(public_key_base64, validate=True)
            Ed25519PublicKey.from_public_bytes(public_key)
        except (ValueError, TypeError) as error:
            raise TrustStoreError("PLUGIN_PUBLISHER_KEY_INVALID") from error
        if len(public_key) != 32:
            raise TrustStoreError("PLUGIN_PUBLISHER_KEY_INVALID")
        value = self._load()
        publishers = value.setdefault("publishers", {})
        if not isinstance(publishers, dict):
            raise TrustStoreError("PLUGIN_TRUST_STORE_INVALID")
        publishers[key_id] = {
            "publisher": publisher,
            "public_key_base64": public_key_base64,
            "added_at": datetime.now(UTC).isoformat(),
        }
        self._write(value)

    def approve_local(self, manifest: PluginManifest, package_sha256: str) -> None:
        value = self._load()
        approvals = value.setdefault("local_approvals", {})
        if not isinstance(approvals, dict):
            raise TrustStoreError("PLUGIN_TRUST_STORE_INVALID")
        approvals[package_sha256] = {
            "plugin_id": manifest.plugin_id,
            "version": manifest.version,
            "approved_at": datetime.now(UTC).isoformat(),
        }
        self._write(value)

    def revoke_package(self, package_sha256: str) -> None:
        value = self._load()
        revoked = value.setdefault("revoked_packages", [])
        if not isinstance(revoked, list):
            raise TrustStoreError("PLUGIN_TRUST_STORE_INVALID")
        if package_sha256 not in revoked:
            revoked.append(package_sha256)
        approvals = value.setdefault("local_approvals", {})
        if isinstance(approvals, dict):
            approvals.pop(package_sha256, None)
        self._write(value)

    def revoke_publisher_key(self, key_id: str) -> None:
        value = self._load()
        revoked = value.setdefault("revoked_publisher_keys", [])
        if not isinstance(revoked, list):
            raise TrustStoreError("PLUGIN_TRUST_STORE_INVALID")
        if key_id not in revoked:
            revoked.append(key_id)
        self._write(value)

    def verify(self, manifest: PluginManifest, package_sha256: str) -> PluginTrustDecision:
        value = self._load()
        manifest_sha256 = unsigned_manifest_sha256(manifest)
        plugin_coordinate = f"{manifest.plugin_id}@{manifest.version}"
        if package_sha256 in value.get("revoked_packages", []) or plugin_coordinate in value.get(
            "revoked_plugins", []
        ):
            return PluginTrustDecision(
                status="revoked",
                issue_codes=["PLUGIN_PACKAGE_REVOKED"],
                manifest_sha256=manifest_sha256,
                package_sha256=package_sha256,
            )

        signature = manifest.signature
        if signature is not None:
            key_id = signature.publisher_key_id
            if key_id in value.get("revoked_publisher_keys", []):
                return PluginTrustDecision(
                    status="revoked",
                    issue_codes=["PLUGIN_PUBLISHER_KEY_REVOKED"],
                    publisher_key_id=key_id,
                    manifest_sha256=manifest_sha256,
                    package_sha256=package_sha256,
                )
        approval = value.get("local_approvals", {}).get(package_sha256)
        if isinstance(approval, dict) and (approval.get("plugin_id"), approval.get("version")) == (
            manifest.plugin_id,
            manifest.version,
        ):
            return PluginTrustDecision(
                status="local-approved",
                manifest_sha256=manifest_sha256,
                package_sha256=package_sha256,
            )

        if signature is not None:
            key_id = signature.publisher_key_id
            publisher = value.get("publishers", {}).get(key_id)
            if not isinstance(publisher, dict):
                return PluginTrustDecision(
                    status="unverified",
                    issue_codes=["PLUGIN_PUBLISHER_UNKNOWN"],
                    publisher_key_id=key_id,
                    manifest_sha256=manifest_sha256,
                    package_sha256=package_sha256,
                )
            if publisher.get("publisher") != manifest.publisher:
                issue = "PLUGIN_PUBLISHER_NAME_MISMATCH"
            elif signature.signed_manifest_sha256 != manifest_sha256:
                issue = "PLUGIN_SIGNED_MANIFEST_HASH_MISMATCH"
            else:
                try:
                    public_bytes = base64.b64decode(
                        str(publisher["public_key_base64"]), validate=True
                    )
                    signed = base64.b64decode(signature.signature_base64, validate=True)
                    Ed25519PublicKey.from_public_bytes(public_bytes).verify(
                        signed, bytes.fromhex(manifest_sha256)
                    )
                except (InvalidSignature, ValueError, TypeError, KeyError):
                    issue = "PLUGIN_SIGNATURE_INVALID"
                else:
                    return PluginTrustDecision(
                        status="verified",
                        publisher_key_id=key_id,
                        manifest_sha256=manifest_sha256,
                        package_sha256=package_sha256,
                    )
            return PluginTrustDecision(
                status="unverified",
                issue_codes=[issue],
                publisher_key_id=key_id,
                manifest_sha256=manifest_sha256,
                package_sha256=package_sha256,
            )

        return PluginTrustDecision(
            status="unverified",
            issue_codes=["PLUGIN_SIGNATURE_REQUIRED"],
            manifest_sha256=manifest_sha256,
            package_sha256=package_sha256,
        )
