"""Core-owned capability broker for least-authority plugin I/O.

Plugins receive a scoped facade. They never receive a credential value and cannot
expand their own filesystem, network, or process authority at runtime.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import socket
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .plugin_contracts import CapabilityBrokerReceipt, PluginManifest


class CapabilityBrokerError(RuntimeError):
    """A denied or failed broker operation with a stable issue code."""

    def __init__(self, issue_code: str) -> None:
        super().__init__(issue_code)
        self.issue_code = issue_code


class CredentialResolver(Protocol):
    def resolve(self, reference: str, *, plugin_id: str) -> str: ...


class EnvironmentCredentialResolver:
    """Resolve named connector credentials without exposing the environment to plugins."""

    def __init__(self, *, prefix: str = "DRONEDREAM_CONNECTOR_") -> None:
        self.prefix = prefix

    def resolve(self, reference: str, *, plugin_id: str) -> str:
        if not reference or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
            for character in reference.lower()
        ):
            raise CapabilityBrokerError("BROKER_CREDENTIAL_REFERENCE_INVALID")
        variable = self.prefix + reference.upper().replace("-", "_")
        value = os.environ.get(variable, "")
        if not value:
            raise CapabilityBrokerError("BROKER_CREDENTIAL_UNAVAILABLE")
        return value


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise CapabilityBrokerError("BROKER_NETWORK_REDIRECT_DENIED")


@dataclass(frozen=True)
class BrokerHttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> object:
        return json.loads(self.body.decode("utf-8"))


@dataclass(frozen=True)
class BrokerProcessResult:
    returncode: int
    stdout: str
    stderr: str


class CoreCapabilityBroker:
    """Authority root used by the app to mint plugin-specific broker facades."""

    def __init__(
        self,
        *,
        read_roots: Mapping[str, Path] | None = None,
        write_roots: Mapping[str, Path] | None = None,
        allowed_executables: Mapping[str, Path] | None = None,
        credential_resolver: CredentialResolver | None = None,
        receipt_sink: Callable[[CapabilityBrokerReceipt], None] | None = None,
    ) -> None:
        self._read_roots = self._normalize_roots(read_roots or {})
        self._write_roots = self._normalize_roots(write_roots or {}, create=True)
        self._allowed_executables = {
            name: path.resolve(strict=True) for name, path in (allowed_executables or {}).items()
        }
        self._credential_resolver = credential_resolver
        self._receipt_sink = receipt_sink

    @staticmethod
    def _normalize_roots(values: Mapping[str, Path], *, create: bool = False) -> dict[str, Path]:
        roots: dict[str, Path] = {}
        for name, value in values.items():
            if not name or not name.replace("-", "").replace("_", "").isalnum():
                raise ValueError("BROKER_ROOT_NAME_INVALID")
            if create:
                value.mkdir(parents=True, exist_ok=True)
            roots[name] = value.resolve(strict=True)
        return roots

    def scope(self, manifest: PluginManifest) -> ScopedCapabilityBroker:
        return ScopedCapabilityBroker(
            manifest=manifest,
            read_roots=self._read_roots,
            write_roots=self._write_roots,
            allowed_executables=self._allowed_executables,
            credential_resolver=self._credential_resolver,
            receipt_sink=self._receipt_sink,
        )


class ScopedCapabilityBroker:
    """A non-escalatable I/O facade bound to one validated manifest."""

    def __init__(
        self,
        *,
        manifest: PluginManifest,
        read_roots: Mapping[str, Path],
        write_roots: Mapping[str, Path],
        allowed_executables: Mapping[str, Path],
        credential_resolver: CredentialResolver | None,
        receipt_sink: Callable[[CapabilityBrokerReceipt], None] | None,
    ) -> None:
        self.plugin_id = manifest.plugin_id
        self._permissions = frozenset(manifest.permissions)
        self._hosts = frozenset(
            host.lower().rstrip(".") for host in manifest.resource_policy.allowed_network_hosts
        )
        self._read_roots = dict(read_roots)
        self._write_roots = dict(write_roots)
        self._allowed_executables = dict(allowed_executables)
        self._credential_resolver = credential_resolver
        self._receipt_sink = receipt_sink
        self._maximum_bytes = manifest.resource_policy.maximum_message_bytes
        self._timeout = manifest.runtime.call_timeout_seconds

    def _receipt(
        self,
        operation: str,
        outcome: Literal["accepted", "denied", "failed"],
        resource: str,
        *,
        byte_count: int = 0,
        issue_codes: list[str] | None = None,
    ) -> None:
        if self._receipt_sink is not None:
            self._receipt_sink(
                CapabilityBrokerReceipt(
                    plugin_id=self.plugin_id,
                    operation=operation,
                    outcome=outcome,
                    resource_sha256=hashlib.sha256(resource.encode("utf-8")).hexdigest(),
                    byte_count=byte_count,
                    issue_codes=issue_codes or [],
                )
            )

    def _require(self, permission: str, *, operation: str, resource: str) -> None:
        if permission not in self._permissions:
            self._receipt(operation, "denied", resource, issue_codes=["BROKER_PERMISSION_DENIED"])
            raise CapabilityBrokerError("BROKER_PERMISSION_DENIED")

    @staticmethod
    def _resolve_beneath(root: Path, relative_path: str, *, must_exist: bool) -> Path:
        candidate_value = Path(relative_path)
        if (
            candidate_value.is_absolute()
            or ".." in candidate_value.parts
            or "\x00" in relative_path
        ):
            raise CapabilityBrokerError("BROKER_PATH_INVALID")
        candidate = (root / candidate_value).resolve(strict=must_exist)
        if candidate != root and root not in candidate.parents:
            raise CapabilityBrokerError("BROKER_PATH_ESCAPE")
        return candidate

    def read_bytes(self, root_name: str, relative_path: str) -> bytes:
        resource = f"{root_name}:{relative_path}"
        permission = "attachment.read" if root_name == "attachments" else "asset.read"
        self._require(permission, operation="filesystem.read", resource=resource)
        root = self._read_roots.get(root_name)
        if root is None:
            raise CapabilityBrokerError("BROKER_ROOT_UNAVAILABLE")
        try:
            path = self._resolve_beneath(root, relative_path, must_exist=True)
            if not path.is_file():
                raise CapabilityBrokerError("BROKER_FILE_REQUIRED")
            if path.stat().st_size > self._maximum_bytes:
                raise CapabilityBrokerError("BROKER_RESPONSE_TOO_LARGE")
            value = path.read_bytes()
        except CapabilityBrokerError as error:
            self._receipt("filesystem.read", "denied", resource, issue_codes=[error.issue_code])
            raise
        self._receipt("filesystem.read", "accepted", resource, byte_count=len(value))
        return value

    def write_bytes(self, root_name: str, relative_path: str, value: bytes) -> None:
        resource = f"{root_name}:{relative_path}"
        permission = "asset.write-staging" if root_name == "staging" else "mission.write-output"
        self._require(permission, operation="filesystem.write", resource=resource)
        if len(value) > self._maximum_bytes:
            raise CapabilityBrokerError("BROKER_REQUEST_TOO_LARGE")
        root = self._write_roots.get(root_name)
        if root is None:
            raise CapabilityBrokerError("BROKER_ROOT_UNAVAILABLE")
        try:
            path = self._resolve_beneath(root, relative_path, must_exist=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".broker-tmp")
            temporary.write_bytes(value)
            temporary.replace(path)
        except CapabilityBrokerError as error:
            self._receipt("filesystem.write", "denied", resource, issue_codes=[error.issue_code])
            raise
        self._receipt("filesystem.write", "accepted", resource, byte_count=len(value))

    @staticmethod
    def _validate_resolved_host(host: str, port: int, *, allow_private: bool) -> None:
        try:
            addresses = {
                item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            }
        except socket.gaierror as error:
            raise CapabilityBrokerError("BROKER_NETWORK_DNS_FAILED") from error
        if not addresses:
            raise CapabilityBrokerError("BROKER_NETWORK_DNS_FAILED")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not allow_private and any(
                (
                    ip.is_private,
                    ip.is_loopback,
                    ip.is_link_local,
                    ip.is_multicast,
                    ip.is_reserved,
                    ip.is_unspecified,
                )
            ):
                raise CapabilityBrokerError("BROKER_NETWORK_PRIVATE_ADDRESS_DENIED")

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        credential_reference: str | None = None,
        credential_header: str = "Authorization",
        credential_prefix: str = "Bearer ",
    ) -> BrokerHttpResponse:
        if "network.external" not in self._permissions:
            self._require("network.local-device", operation="network.request", resource=url)
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port not in {None, 443}
            or host not in self._hosts
        ):
            self._receipt(
                "network.request", "denied", url, issue_codes=["BROKER_NETWORK_TARGET_DENIED"]
            )
            raise CapabilityBrokerError("BROKER_NETWORK_TARGET_DENIED")
        verb = method.upper()
        if verb not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise CapabilityBrokerError("BROKER_NETWORK_METHOD_DENIED")
        payload = body or b""
        if len(payload) > self._maximum_bytes:
            raise CapabilityBrokerError("BROKER_REQUEST_TOO_LARGE")
        safe_headers: dict[str, str] = {}
        denied_headers = {"authorization", "cookie", "proxy-authorization", "host"}
        for name, value in (headers or {}).items():
            if name.lower() in denied_headers or "\r" in value or "\n" in value:
                raise CapabilityBrokerError("BROKER_NETWORK_HEADER_DENIED")
            safe_headers[name] = value
        if credential_reference is not None:
            self._require(
                "credential.reference", operation="credential.inject", resource=credential_reference
            )
            if self._credential_resolver is None:
                raise CapabilityBrokerError("BROKER_CREDENTIAL_RESOLVER_UNAVAILABLE")
            if credential_header.lower() not in {
                "authorization",
                "x-api-key",
                "api-key",
                "as-api-key",
            }:
                raise CapabilityBrokerError("BROKER_CREDENTIAL_HEADER_DENIED")
            safe_headers[credential_header] = credential_prefix + self._credential_resolver.resolve(
                credential_reference, plugin_id=self.plugin_id
            )
            self._receipt("credential.inject", "accepted", credential_reference)
        try:
            self._validate_resolved_host(
                host,
                443,
                allow_private="network.local-device" in self._permissions,
            )
            response = build_opener(_NoRedirect()).open(
                Request(url, data=payload or None, headers=safe_headers, method=verb),
                timeout=self._timeout,
            )
            with response:
                response_body = response.read(self._maximum_bytes + 1)
                if len(response_body) > self._maximum_bytes:
                    raise CapabilityBrokerError("BROKER_RESPONSE_TOO_LARGE")
                response_headers = {
                    name.lower(): value
                    for name, value in response.headers.items()
                    if name.lower() not in {"set-cookie", "authorization", "proxy-authenticate"}
                }
                result = BrokerHttpResponse(
                    status=int(response.status), headers=response_headers, body=response_body
                )
        except CapabilityBrokerError as error:
            self._receipt("network.request", "denied", url, issue_codes=[error.issue_code])
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            self._receipt("network.request", "failed", url, issue_codes=["BROKER_NETWORK_FAILED"])
            raise CapabilityBrokerError("BROKER_NETWORK_FAILED") from error
        self._receipt("network.request", "accepted", url, byte_count=len(result.body))
        return result

    def spawn(
        self, executable_id: str, arguments: list[str], *, stdin: bytes = b""
    ) -> BrokerProcessResult:
        resource = f"executable:{executable_id}"
        self._require("process.spawn", operation="process.spawn", resource=resource)
        executable = self._allowed_executables.get(executable_id)
        if executable is None:
            raise CapabilityBrokerError("BROKER_EXECUTABLE_DENIED")
        if len(arguments) > 64 or any(
            not value or "\x00" in value or len(value) > 1_024 for value in arguments
        ):
            raise CapabilityBrokerError("BROKER_ARGUMENTS_INVALID")
        if len(stdin) > self._maximum_bytes:
            raise CapabilityBrokerError("BROKER_REQUEST_TOO_LARGE")
        try:
            completed = subprocess.run(
                [str(executable), *arguments],
                input=stdin,
                capture_output=True,
                timeout=self._timeout,
                check=False,
                shell=False,
                env={"PATH": "", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")},
            )
            if len(completed.stdout) + len(completed.stderr) > self._maximum_bytes:
                raise CapabilityBrokerError("BROKER_RESPONSE_TOO_LARGE")
        except (OSError, subprocess.TimeoutExpired) as error:
            self._receipt(
                "process.spawn", "failed", resource, issue_codes=["BROKER_PROCESS_FAILED"]
            )
            raise CapabilityBrokerError("BROKER_PROCESS_FAILED") from error
        result = BrokerProcessResult(
            returncode=completed.returncode,
            stdout=completed.stdout.decode("utf-8", errors="replace"),
            stderr=completed.stderr.decode("utf-8", errors="replace"),
        )
        self._receipt(
            "process.spawn",
            "accepted" if completed.returncode == 0 else "failed",
            resource,
            byte_count=len(completed.stdout) + len(completed.stderr),
            issue_codes=[] if completed.returncode == 0 else ["BROKER_PROCESS_NONZERO"],
        )
        return result


class CapabilityBrokerHostServices:
    """Bounded JSON-RPC facade exposed to an isolated MCP child process."""

    def __init__(self, broker: ScopedCapabilityBroker) -> None:
        self._broker = broker

    @staticmethod
    def _bytes(value: object, *, field: str) -> bytes:
        if not isinstance(value, str):
            raise CapabilityBrokerError(f"BROKER_{field.upper()}_INVALID")
        try:
            return base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as error:
            raise CapabilityBrokerError(f"BROKER_{field.upper()}_INVALID") from error

    def __call__(self, method: str, params: dict[str, object]) -> object:
        if method == "dronedream/filesystem/read":
            value = self._broker.read_bytes(
                str(params.get("root", "")), str(params.get("path", ""))
            )
            return {"body_base64": base64.b64encode(value).decode("ascii")}
        if method == "dronedream/filesystem/write":
            self._broker.write_bytes(
                str(params.get("root", "")),
                str(params.get("path", "")),
                self._bytes(params.get("body_base64"), field="body_base64"),
            )
            return {"accepted": True}
        if method == "dronedream/network/request":
            headers = params.get("headers", {})
            if not isinstance(headers, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in headers.items()
            ):
                raise CapabilityBrokerError("BROKER_NETWORK_HEADERS_INVALID")
            body_value = params.get("body_base64", "")
            response = self._broker.request(
                str(params.get("http_method", "GET")),
                str(params.get("url", "")),
                headers=headers,
                body=self._bytes(body_value, field="body_base64") if body_value else None,
                credential_reference=(
                    str(params["credential_reference"])
                    if params.get("credential_reference")
                    else None
                ),
                credential_header=str(params.get("credential_header", "Authorization")),
                credential_prefix=str(params.get("credential_prefix", "Bearer ")),
            )
            return {
                "status": response.status,
                "headers": response.headers,
                "body_base64": base64.b64encode(response.body).decode("ascii"),
            }
        if method == "dronedream/process/spawn":
            arguments = params.get("arguments", [])
            if not isinstance(arguments, list) or not all(
                isinstance(value, str) for value in arguments
            ):
                raise CapabilityBrokerError("BROKER_ARGUMENTS_INVALID")
            stdin_value = params.get("stdin_base64", "")
            result = self._broker.spawn(
                str(params.get("executable_id", "")),
                arguments,
                stdin=self._bytes(stdin_value, field="stdin_base64") if stdin_value else b"",
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        raise CapabilityBrokerError("BROKER_METHOD_DENIED")
