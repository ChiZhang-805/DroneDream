"""Isolated MCP stdio process boundary for untrusted user tool plugins."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .hashing import sha256_json
from .plugin_contracts import PluginResourcePolicy


class PluginProcessError(RuntimeError):
    """A plugin process failed startup, protocol validation, or a tool call."""


class PluginHostServices(Protocol):
    def __call__(self, method: str, params: dict[str, Any]) -> object: ...


def _safe_environment(
    *, permissions: list[str], resource_policy: PluginResourcePolicy
) -> dict[str, str]:
    # Windows AppContainer process creation requires LOCALAPPDATA to resolve the
    # per-user isolation profile. The sandbox token and ACL still deny access to
    # unrelated files; this exposes only the directory name, never file content.
    allowed = (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "LOCALAPPDATA",
        "LANG",
        "LC_ALL",
    )
    environment = {key: value for key in allowed if (value := os.environ.get(key))}
    environment["DRONEDREAM_PLUGIN_SANDBOX"] = "1"
    environment["DRONEDREAM_PLUGIN_NETWORK_BROKER_ONLY"] = "1"
    environment["DRONEDREAM_ALLOWED_NETWORK_HOSTS"] = ",".join(
        resource_policy.allowed_network_hosts
    )
    # Network permissions authorize the reverse host broker, never a raw child socket.
    # AppContainer/network namespaces enforce this at the OS boundary; poisoned proxy
    # variables also fail closed for proxy-aware libraries on unsupported dev hosts.
    blocked_proxy = "http://127.0.0.1:9"
    environment.update(
        {
            "HTTP_PROXY": blocked_proxy,
            "HTTPS_PROXY": blocked_proxy,
            "ALL_PROXY": blocked_proxy,
            "NO_PROXY": "",
        }
    )
    return environment


def _isolated_command(
    *,
    plugin_root: Path,
    command: list[str],
    require_os_isolation: bool,
    isolator_path: Path | None,
    resource_policy: PluginResourcePolicy | None = None,
) -> list[str]:
    resource_policy = resource_policy or PluginResourcePolicy()
    resolved = resolve_plugin_command(plugin_root, command)
    if not require_os_isolation:
        return resolved
    if os.name == "nt":
        candidate = isolator_path
        if candidate is None:
            configured = os.environ.get("DRONEDREAM_PLUGIN_ISOLATOR", "")
            candidate = (
                Path(configured)
                if configured
                else Path(sys.executable).with_name("dronedream-plugin-isolator.exe")
            )
        candidate = candidate.resolve()
        if not candidate.is_file():
            raise PluginProcessError("PLUGIN_OS_ISOLATOR_UNAVAILABLE")
        profile = "DroneDream.Plugin." + sha256_json(str(plugin_root.resolve()))[:32]
        return [
            str(candidate),
            "--profile",
            profile,
            "--root",
            str(plugin_root.resolve()),
            "--memory-mb",
            str(resource_policy.memory_limit_mb),
            "--cpu-seconds",
            str(resource_policy.cpu_time_limit_seconds),
            "--process-limit",
            str(resource_policy.process_limit),
            "--",
            *resolved,
        ]
    raise PluginProcessError("PLUGIN_OS_ISOLATOR_UNAVAILABLE")


def _posix_resource_limiter(policy: PluginResourcePolicy) -> Callable[[], None] | None:
    if os.name == "nt":
        return None

    def apply_limits() -> None:
        import resource

        memory_bytes = policy.memory_limit_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (policy.cpu_time_limit_seconds, policy.cpu_time_limit_seconds),
        )
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (policy.process_limit, policy.process_limit))

    return apply_limits


class _WindowsJob:
    """Assign a child to a kill-on-close Windows Job with hard resource ceilings."""

    def __init__(self, process_id: int, policy: PluginResourcePolicy) -> None:
        self._handle: int | None = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.OpenProcess.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        process = kernel32.OpenProcess(0x0200 | 0x0400, False, process_id)
        if not job or not process:
            if job:
                kernel32.CloseHandle(job)
            if process:
                kernel32.CloseHandle(process)
            raise PluginProcessError("PLUGIN_RESOURCE_BROKER_START_FAILED")
        information = ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x2000 | 0x100 | 0x8 | 0x2
        information.BasicLimitInformation.PerProcessUserTimeLimit = (
            policy.cpu_time_limit_seconds * 10_000_000
        )
        information.BasicLimitInformation.ActiveProcessLimit = policy.process_limit
        information.ProcessMemoryLimit = policy.memory_limit_mb * 1024 * 1024
        ok = kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(information), ctypes.sizeof(information)
        ) and kernel32.AssignProcessToJobObject(job, process)
        kernel32.CloseHandle(process)
        if not ok:
            kernel32.CloseHandle(job)
            raise PluginProcessError("PLUGIN_RESOURCE_LIMIT_ASSIGN_FAILED")
        self._handle = int(job)

    def close(self) -> None:
        if self._handle is not None:
            import ctypes

            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self._handle)
            self._handle = None


def resolve_plugin_command(plugin_root: Path, command: list[str]) -> list[str]:
    if not command:
        raise PluginProcessError("PLUGIN_COMMAND_MISSING")
    executable = Path(command[0])
    if executable.is_absolute():
        raise PluginProcessError("PLUGIN_EXECUTABLE_MUST_BE_BUNDLED")
    resolved = (plugin_root / executable).resolve()
    root = plugin_root.resolve()
    if root not in resolved.parents or not resolved.is_file():
        raise PluginProcessError("PLUGIN_EXECUTABLE_INVALID")
    return [str(resolved), *command[1:]]


class McpStdioClient:
    """Small strict MCP client used only for tools/list and tools/call."""

    def __init__(
        self,
        *,
        plugin_root: Path,
        command: list[str],
        protocol_version: str,
        startup_timeout_seconds: float,
        call_timeout_seconds: float,
        configuration: dict[str, Any] | None = None,
        permissions: list[str] | None = None,
        resource_policy: PluginResourcePolicy | None = None,
        host_services: PluginHostServices | None = None,
        require_os_isolation: bool = False,
        isolator_path: Path | None = None,
    ) -> None:
        permissions = permissions or []
        resource_policy = resource_policy or PluginResourcePolicy()
        resolved_command = _isolated_command(
            plugin_root=plugin_root,
            command=command,
            require_os_isolation=require_os_isolation,
            isolator_path=isolator_path,
            resource_policy=resource_policy,
        )
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self._process = subprocess.Popen(
                resolved_command,
                cwd=plugin_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=_safe_environment(permissions=permissions, resource_policy=resource_policy),
                creationflags=creation_flags,
                preexec_fn=_posix_resource_limiter(resource_policy),
            )
        except OSError as error:
            raise PluginProcessError("PLUGIN_PROCESS_START_FAILED") from error
        try:
            self._job = (
                None
                if os.name == "nt" and require_os_isolation
                else _WindowsJob(self._process.pid, resource_policy)
            )
        except BaseException:
            self._process.kill()
            self._process.wait(timeout=2)
            raise
        self._pending: dict[str, queue.Queue[dict[str, Any] | BaseException | None]] = {}
        self._pending_lock = threading.Lock()
        self._notifications: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=2_000)
        self._stderr: list[str] = []
        self._write_lock = threading.Lock()
        self._closed = False
        self._maximum_message_bytes = resource_policy.maximum_message_bytes
        self._host_services = host_services
        assert self._process.stdout is not None and self._process.stderr is not None
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": protocol_version,
                    "capabilities": {},
                    "clientInfo": {"name": "DroneDream-AUTONOMY", "version": "0.1.0"},
                    "initializationOptions": {"configuration": configuration or {}},
                },
                timeout=startup_timeout_seconds,
            )
            self._notify("notifications/initialized", {})
        except BaseException:
            self.close()
            raise
        self._call_timeout_seconds = call_timeout_seconds

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                if not line.strip():
                    continue
                if len(line.encode("utf-8")) > self._maximum_message_bytes:
                    self._broadcast_error(PluginProcessError("PLUGIN_PROTOCOL_MESSAGE_TOO_LARGE"))
                    return
                value = json.loads(line)
                if isinstance(value, dict):
                    request_id = value.get("id")
                    with self._pending_lock:
                        target = self._pending.get(str(request_id))
                    if target is not None:
                        target.put(value)
                    elif value.get("method") and request_id is not None:
                        threading.Thread(
                            target=self._serve_host_request,
                            args=(value,),
                            daemon=True,
                        ).start()
                    elif value.get("method"):
                        try:
                            self._notifications.put_nowait(value)
                        except queue.Full:
                            self._broadcast_error(
                                PluginProcessError("PLUGIN_NOTIFICATION_OVERFLOW")
                            )
                            return
                else:
                    self._broadcast_error(PluginProcessError("PLUGIN_PROTOCOL_MESSAGE_INVALID"))
        except BaseException as error:
            self._broadcast_error(error)
        finally:
            self._broadcast_error(None)

    def _serve_host_request(self, value: dict[str, Any]) -> None:
        request_id = value.get("id")
        method = value.get("method")
        params = value.get("params", {})
        if (
            self._host_services is None
            or not isinstance(method, str)
            or not method.startswith("dronedream/")
            or not isinstance(params, dict)
        ):
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": "HOST_METHOD_NOT_ALLOWED"},
                }
            )
            return
        try:
            result = self._host_services(method, params)
            self._send({"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as error:
            issue = getattr(error, "issue_code", type(error).__name__)
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32001, "message": str(issue)[:160]},
                }
            )

    def _broadcast_error(self, error: BaseException | None) -> None:
        with self._pending_lock:
            targets = list(self._pending.values())
        for target in targets:
            try:
                target.put_nowait(error)
            except queue.Full:
                continue

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for line in self._process.stderr:
            self._stderr.append(line.rstrip()[:500])
            if len(self._stderr) > 20:
                self._stderr.pop(0)

    def _send(self, value: dict[str, Any]) -> None:
        if self._closed or self._process.poll() is not None:
            raise PluginProcessError("PLUGIN_PROCESS_NOT_RUNNING")
        assert self._process.stdin is not None
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._write_lock:
            try:
                self._process.stdin.write(payload)
                self._process.stdin.flush()
            except OSError as error:
                raise PluginProcessError("PLUGIN_PROTOCOL_WRITE_FAILED") from error

    def _request(self, method: str, params: dict[str, Any], *, timeout: float) -> Any:
        request_id = f"request-{uuid4().hex}"
        messages: queue.Queue[dict[str, Any] | BaseException | None] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = messages
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            try:
                message = messages.get(timeout=timeout)
            except queue.Empty as error:
                self.cancel(request_id)
                raise PluginProcessError(f"PLUGIN_TIMEOUT:{method}") from error
            if message is None:
                detail = " | ".join(self._stderr[-3:])
                raise PluginProcessError(f"PLUGIN_PROCESS_EXITED:{detail}"[:800])
            if isinstance(message, BaseException):
                raise PluginProcessError("PLUGIN_PROTOCOL_READ_FAILED") from message
            if message.get("jsonrpc") != "2.0":
                raise PluginProcessError("PLUGIN_PROTOCOL_VERSION_INVALID")
            if "error" in message:
                error_value = message["error"]
                raise PluginProcessError(f"PLUGIN_RPC_ERROR:{error_value}"[:800])
            if "result" not in message:
                raise PluginProcessError("PLUGIN_RPC_RESULT_MISSING")
            return message["result"]
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def cancel(self, request_id: str) -> None:
        self._notify("notifications/cancelled", {"requestId": request_id})

    def ping(self) -> bool:
        result = self._request("ping", {}, timeout=min(self._call_timeout_seconds, 5.0))
        return isinstance(result, dict)

    def drain_notifications(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        while True:
            try:
                values.append(self._notifications.get_nowait())
            except queue.Empty:
                return values

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {}, timeout=self._call_timeout_seconds)
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise PluginProcessError("PLUGIN_TOOL_CATALOG_INVALID")
        tools = result["tools"]
        if any(not isinstance(item, dict) for item in tools):
            raise PluginProcessError("PLUGIN_TOOL_CATALOG_INVALID")
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=self._call_timeout_seconds,
        )
        if not isinstance(result, dict):
            raise PluginProcessError("PLUGIN_TOOL_RESULT_INVALID")
        if result.get("isError"):
            raise PluginProcessError(f"PLUGIN_TOOL_REPORTED_ERROR:{result.get('content')}"[:800])
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "text":
                    continue
                text = item.get("text")
                if not isinstance(text, str):
                    continue
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        raise PluginProcessError("PLUGIN_TOOL_STRUCTURED_RESULT_MISSING")

    def list_resources(self) -> list[dict[str, Any]]:
        result = self._request("resources/list", {}, timeout=self._call_timeout_seconds)
        if not isinstance(result, dict) or not isinstance(result.get("resources"), list):
            raise PluginProcessError("PLUGIN_RESOURCE_CATALOG_INVALID")
        resources = result["resources"]
        if any(not isinstance(item, dict) for item in resources):
            raise PluginProcessError("PLUGIN_RESOURCE_CATALOG_INVALID")
        return resources

    def read_resource(self, uri: str) -> list[dict[str, Any]]:
        result = self._request("resources/read", {"uri": uri}, timeout=self._call_timeout_seconds)
        if not isinstance(result, dict) or not isinstance(result.get("contents"), list):
            raise PluginProcessError("PLUGIN_RESOURCE_CONTENT_INVALID")
        contents = result["contents"]
        if any(not isinstance(item, dict) for item in contents):
            raise PluginProcessError("PLUGIN_RESOURCE_CONTENT_INVALID")
        return contents

    def subscribe_resource(self, uri: str) -> None:
        self._request("resources/subscribe", {"uri": uri}, timeout=self._call_timeout_seconds)

    def unsubscribe_resource(self, uri: str) -> None:
        self._request("resources/unsubscribe", {"uri": uri}, timeout=self._call_timeout_seconds)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
        for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
            if stream is not None:
                stream.close()
        if self._job is not None:
            self._job.close()

    def __enter__(self) -> McpStdioClient:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


class McpSessionPool:
    """Persistent, concurrent-safe MCP sessions keyed by immutable runtime identity."""

    def __init__(
        self,
        *,
        heartbeat_interval_seconds: float = 15.0,
        on_unhealthy: Callable[[str, str], None] | None = None,
    ) -> None:
        if heartbeat_interval_seconds <= 0:
            raise ValueError("PLUGIN_HEARTBEAT_INTERVAL_INVALID")
        self._lock = threading.RLock()
        self._sessions: dict[tuple[str, str], McpStdioClient] = {}
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._on_unhealthy = on_unhealthy
        self._stop = threading.Event()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="dronedream-plugin-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._heartbeat_interval_seconds):
            with self._lock:
                sessions = list(self._sessions.items())
            for key, client in sessions:
                issue = ""
                try:
                    if not client.ping():
                        issue = "PLUGIN_HEARTBEAT_INVALID"
                except BaseException as error:
                    issue = f"PLUGIN_HEARTBEAT_FAILED:{type(error).__name__}"
                if not issue:
                    continue
                removed = False
                with self._lock:
                    if self._sessions.get(key) is client:
                        self._sessions.pop(key, None)
                        removed = True
                if not removed:
                    continue
                close = getattr(client, "close", None)
                if callable(close):
                    close()
                if self._on_unhealthy is not None:
                    self._on_unhealthy(key[0], issue)

    def get(
        self,
        *,
        plugin_id: str,
        package_sha256: str,
        plugin_root: Path,
        command: list[str],
        protocol_version: str,
        startup_timeout_seconds: float,
        call_timeout_seconds: float,
        configuration: dict[str, Any],
        permissions: list[str],
        resource_policy: PluginResourcePolicy,
        host_scope_id: str = "none",
        host_services: PluginHostServices | None = None,
        require_os_isolation: bool = False,
        isolator_path: Path | None = None,
        client_factory: Callable[..., McpStdioClient] = McpStdioClient,
    ) -> McpStdioClient:
        identity = sha256_json(
            {
                "package_sha256": package_sha256,
                "command": command,
                "protocol_version": protocol_version,
                "configuration": configuration,
                "permissions": permissions,
                "resource_policy": resource_policy.model_dump(mode="json"),
                "host_scope_id": host_scope_id,
                "require_os_isolation": require_os_isolation,
                "isolator_path": str(isolator_path) if isolator_path else None,
            }
        )
        key = (plugin_id, identity)
        with self._lock:
            client = self._sessions.get(key)
            if client is not None:
                return client
            client = client_factory(
                plugin_root=plugin_root,
                command=command,
                protocol_version=protocol_version,
                startup_timeout_seconds=startup_timeout_seconds,
                call_timeout_seconds=call_timeout_seconds,
                configuration=configuration,
                permissions=permissions,
                resource_policy=resource_policy,
                host_services=host_services,
                require_os_isolation=require_os_isolation,
                isolator_path=isolator_path,
            )
            self._sessions[key] = client
            return client

    def invalidate(self, plugin_id: str) -> None:
        with self._lock:
            keys = [key for key in self._sessions if key[0] == plugin_id]
            for key in keys:
                client = self._sessions.pop(key)
                close = getattr(client, "close", None)
                if callable(close):
                    close()

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            clients = list(self._sessions.values())
            self._sessions.clear()
        for client in clients:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        if (
            self._heartbeat_thread.is_alive()
            and threading.current_thread() is not self._heartbeat_thread
        ):
            self._heartbeat_thread.join(timeout=min(self._heartbeat_interval_seconds, 1.0))
