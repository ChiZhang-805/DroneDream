"""Real external simulator adapter (Phase 8).

Invokes an external CLI subprocess (for example a Python or shell driver that
talks to PX4/Gazebo) once per trial. The adapter writes a structured
``trial_input.json`` describing the trial, waits for the subprocess to write a
matching ``trial_result.json``, and translates the result into the standard
:class:`TrialResult`/:class:`TrialFailure` shapes.

Environment variables:

* ``REAL_SIMULATOR_COMMAND`` — required. Either a command containing the
  literal tokens ``{input}`` and ``{output}`` (which will be string-formatted),
  or a bare command to which ``--input <trial_input.json> --output
  <trial_result.json>`` is appended.
* ``REAL_SIMULATOR_WORKDIR`` — optional working directory for the subprocess.
* ``REAL_SIMULATOR_TIMEOUT_SECONDS`` — wall-clock timeout, default 300.
* ``REAL_SIMULATOR_ARTIFACT_ROOT`` — root directory for per-trial run dirs,
  default ``./artifacts``.
* ``REAL_SIMULATOR_KEEP_RUN_DIRS`` — keep run dirs around after the trial
  finishes (default ``true``). Set ``false`` to delete successful runs.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shlex
import shutil
import signal
import subprocess
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

from app.config import get_settings
from app.parameters import get_parameter
from app.simulator.artifact_schema import (
    infer_mime_type,
    validate_reference_track_payload,
    validate_telemetry_payload,
)
from app.simulator.base import (
    FAILURE_ADAPTER_UNAVAILABLE,
    FAILURE_CANCELLED,
    FAILURE_SIMULATION,
    FAILURE_TIMEOUT,
    ArtifactMetadata,
    SimulatorAdapter,
    TrialContext,
    TrialFailure,
    TrialMetricsPayload,
    TrialResult,
)

logger = logging.getLogger("drone_dream.simulator.real_cli")

_DEFAULT_TIMEOUT = 300
_DEFAULT_ARTIFACT_ROOT = "./artifacts"
_MAX_RESULT_BYTES = 10 * 1024 * 1024
_MAX_KNOWN_JSON_ARTIFACT_BYTES = 16 * 1024 * 1024
_MAX_RAW_METRIC_DEPTH = 20
_MAX_RAW_METRIC_NODES = 10_000
_MAX_SLOW_SIMULATION_TIMEOUT_MULTIPLIER = 10.0
_PROCESS_POLL_SECONDS = 0.2
_TERMINATE_GRACE_SECONDS = 2.0

_CHILD_ENV_EXACT_ALLOWLIST = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "CONDA_DEFAULT_ENV",
        "CONDA_PREFIX",
        "DISPLAY",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "GIT_EXEC_PATH",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LD_LIBRARY_PATH",
        "LOCALAPPDATA",
        "LOGNAME",
        "NUMBER_OF_PROCESSORS",
        "PATH",
        "PATHEXT",
        "PKG_CONFIG_PATH",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "PYTHONHOME",
        "PYTHONIOENCODING",
        "PYTHONNOUSERSITE",
        "PYTHONPATH",
        "PYTHONUTF8",
        "PYTHONUNBUFFERED",
        "QT_QPA_PLATFORM",
        "REQUESTS_CA_BUNDLE",
        "SHELL",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TERM",
        "TMP",
        "TMPDIR",
        "TZ",
        "USER",
        "USERPROFILE",
        "VIRTUAL_ENV",
        "WAYLAND_DISPLAY",
        "WINDIR",
        "WSL_DISTRO_NAME",
        "WSL_INTEROP",
        "WSLENV",
        "XAUTHORITY",
        "XDG_RUNTIME_DIR",
    }
)
_CHILD_ENV_PREFIX_ALLOWLIST = (
    "AMENT_",
    "CMAKE_",
    "COLCON_",
    "CUDA_",
    "GAZEBO_",
    "GZ_",
    "IGN_",
    "KMP_",
    "LC_",
    "MAVSDK_",
    "NVIDIA_",
    "OMP_",
    "PX4_",
    "QML_",
    "QT_",
    "ROCM_",
    "ROS_",
    "SDL_",
    "VULKAN_",
)
_CHILD_ENV_DRONEDREAM_ALLOWLIST = frozenset(
    {
        "DRONEDREAM_GAZEBO_EXECUTABLE",
        "DRONEDREAM_PX4_EXECUTABLE",
    }
)
_SENSITIVE_ENV_FRAGMENTS = ("CREDENTIAL", "KEY", "PASSWORD", "SECRET", "TOKEN")
_SENSITIVE_ENV_EXACT = frozenset(
    {
        "DATABASE_URL",
        "REDIS_URL",
        "SQLALCHEMY_DATABASE_URI",
    }
)
_SENSITIVE_ENV_PREFIXES = (
    "ANTHROPIC_",
    "AWS_",
    "AZURE_",
    "GCP_",
    "GOOGLE_",
    "OIDC_",
    "OAUTH_",
    "OPENAI_",
    "S3_",
)


class _SimulatorCancelled(Exception):
    """Internal sentinel raised after a cancelled attempt's process tree exits."""


@dataclass(frozen=True)
class _ProcessOutcome:
    returncode: int
    stdout: str
    stderr: str


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, original length {len(text)}]"


def _split_command(command: str) -> list[str]:
    tokens = shlex.split(command, posix=os.name != "nt")
    if os.name != "nt":
        return tokens
    return [
        token[1:-1]
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}
        else token
        for token in tokens
    ]


def _build_command(command_template: str, input_path: Path, output_path: Path) -> list[str]:
    tokens = _split_command(command_template)
    if not tokens:
        raise ValueError("REAL_SIMULATOR_COMMAND must contain an executable")
    has_input = any("{input}" in token for token in tokens)
    has_output = any("{output}" in token for token in tokens)
    rendered = [
        token.replace("{input}", str(input_path)).replace("{output}", str(output_path))
        for token in tokens
    ]
    if not has_input:
        rendered.extend(["--input", str(input_path)])
    if not has_output:
        rendered.extend(["--output", str(output_path)])
    return rendered


def _effective_timeout_seconds(baseline_seconds: float, simulation_speed_factor: object) -> float:
    """Convert a 1x simulation budget into a bounded wall-clock timeout.

    Faster-than-real-time simulation keeps the baseline budget so host load
    does not make the timeout unexpectedly stricter. Slower simulation receives
    the expected ``1 / factor`` allowance, capped because the factor is
    user-controlled job input while the baseline is operator configuration.
    """

    if not math.isfinite(baseline_seconds) or baseline_seconds <= 0:
        raise ValueError("timeout must be a finite number greater than zero")
    if isinstance(simulation_speed_factor, bool) or not isinstance(
        simulation_speed_factor, (int, float)
    ):
        raise ValueError("vehicle_profile.simulation_speed_factor must be numeric")
    speed_factor = float(simulation_speed_factor)
    if not math.isfinite(speed_factor) or not 0.1 <= speed_factor <= 100.0:
        raise ValueError("vehicle_profile.simulation_speed_factor must be finite and in [0.1, 100]")
    multiplier = min(
        max(1.0, 1.0 / speed_factor),
        _MAX_SLOW_SIMULATION_TIMEOUT_MULTIPLIER,
    )
    return baseline_seconds * multiplier


def _is_sensitive_environment_name(name: str) -> bool:
    normalized = name.upper()
    return (
        normalized in _SENSITIVE_ENV_EXACT
        or any(fragment in normalized for fragment in _SENSITIVE_ENV_FRAGMENTS)
        or normalized.startswith(_SENSITIVE_ENV_PREFIXES)
    )


def _build_simulator_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Build the least-privilege environment inherited by a simulator CLI.

    The simulator command is operator-configured but may execute third-party
    PX4/Gazebo integration code. It must never inherit backend control-plane
    credentials merely because the worker process has them. Sensitive-name
    rejection takes precedence over all runtime allowlists.
    """

    child: dict[str, str] = {}
    for name, value in source.items():
        normalized = name.upper()
        if _is_sensitive_environment_name(normalized):
            continue
        if (
            normalized in _CHILD_ENV_EXACT_ALLOWLIST
            or normalized in _CHILD_ENV_DRONEDREAM_ALLOWLIST
            or normalized.startswith(_CHILD_ENV_PREFIX_ALLOWLIST)
            or normalized.startswith("DRONEDREAM_RUNTIME_")
        ):
            child[name] = value
    return child


def _safe_path_segment(value: str, *, field_name: str) -> str:
    """Reject identifiers that could escape the per-trial artifact hierarchy."""

    normalized = str(value).strip()
    if (
        not normalized
        or len(normalized) > 128
        or normalized in {".", ".."}
        or any(char in normalized for char in ("/", "\\", "\x00"))
        or any(ord(char) < 32 for char in normalized)
    ):
        raise ValueError(f"{field_name} is not a safe artifact path segment")
    return normalized


def _run_directory(artifact_root: Path, ctx: TrialContext) -> Path:
    root = artifact_root.expanduser().resolve()
    job_id = _safe_path_segment(ctx.job_id, field_name="job_id")
    trial_id = _safe_path_segment(ctx.trial_id, field_name="trial_id")
    if isinstance(ctx.attempt_count, bool) or ctx.attempt_count < 1:
        raise ValueError("attempt_count must be a positive integer")
    base = (root / "jobs" / job_id / "trials" / trial_id).resolve()
    if not base.is_relative_to(root):  # pragma: no cover - guarded by safe segments.
        raise ValueError("trial run directory escaped REAL_SIMULATOR_ARTIFACT_ROOT")
    if ctx.attempt_count == 1:
        return base
    return base / "attempts" / f"{ctx.attempt_count:04d}"


def _write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        with suppress(OSError):
            temporary.unlink()


def _read_log_tail(path: Path, *, limit: int = 2000) -> str:
    try:
        size = path.stat().st_size
        # UTF-8 uses at most four bytes per codepoint. Seek directly to a
        # bounded suffix so an accidentally verbose simulator cannot make the
        # worker load a multi-gigabyte log merely to build an excerpt.
        read_size = min(size, max(limit * 4, 4096))
        with path.open("rb") as stream:
            stream.seek(-read_size, os.SEEK_END)
            text = stream.read(read_size).decode("utf-8", errors="replace")
    except OSError:
        return ""
    if size <= read_size and len(text) <= limit:
        return text
    return f"... [tail of {size} bytes]\n{text[-limit:]}"


def _terminate_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """Terminate the simulator and descendants after timeout/cancellation."""

    if proc.poll() is not None:
        return
    if os.name == "nt":
        with suppress(OSError, subprocess.SubprocessError):
            subprocess.run(  # noqa: S603, S607 - fixed system utility/arguments.
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=10,
            )
    else:
        kill_process_group = getattr(os, "killpg", None)
        with suppress(OSError):
            if kill_process_group is not None:
                kill_process_group(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            with suppress(OSError):
                if kill_process_group is not None:
                    kill_process_group(proc.pid, getattr(signal, "SIGKILL", 9))
    if proc.poll() is None:
        with suppress(OSError):
            proc.kill()
    with suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=_TERMINATE_GRACE_SECONDS)


def _execute_command(
    argv: list[str],
    *,
    cwd: str | None,
    env: dict[str, str],
    timeout_seconds: float,
    cancellation_event: Event | None,
    stdout_path: Path,
    stderr_path: Path,
) -> _ProcessOutcome:
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        proc = subprocess.Popen(  # noqa: S603 - trusted operator command, no shell.
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=os.name != "nt",
            creationflags=creationflags,
        )
        deadline = time.monotonic() + timeout_seconds
        while True:
            if cancellation_event is not None and cancellation_event.is_set():
                _terminate_process_tree(proc)
                raise _SimulatorCancelled
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_tree(proc)
                raise subprocess.TimeoutExpired(argv, timeout_seconds)
            try:
                returncode = proc.wait(timeout=min(_PROCESS_POLL_SECONDS, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    return _ProcessOutcome(
        returncode=returncode,
        stdout=_read_log_tail(stdout_path),
        stderr=_read_log_tail(stderr_path),
    )


def _trial_input_payload(ctx: TrialContext, output_path: Path) -> dict[str, Any]:
    """Build the ``trial_input.json`` payload for the external simulator.

    The canonical grouping for track/configuration fields is ``job_config``.
    The same fields are additionally mirrored as top-level aliases so
    wrapper authors can read either shape without reaching into the nested
    object. See ``docs/PHASE8_REAL_SIM_AND_GPT_TUNING.md`` for the
    normative schema.
    """

    jc = ctx.job_config
    start_point = {"x": jc.start_point_x, "y": jc.start_point_y}
    wind = {
        "north": jc.wind_north,
        "east": jc.wind_east,
        "south": jc.wind_south,
        "west": jc.wind_west,
    }
    vehicle_profile = dict(jc.vehicle_profile or {})
    px4_version = str(vehicle_profile.get("px4_version") or "main")

    def is_catalog_parameter(name: object) -> bool:
        normalized = str(name)
        return get_parameter(normalized, px4_version=px4_version) is not None or (
            get_parameter(normalized, px4_version="main") is not None
        )

    px4_parameters = {
        str(name): value for name, value in ctx.parameters.items() if is_catalog_parameter(name)
    }
    job_config = {
        "track_type": jc.track_type,
        "start_point": start_point,
        "altitude_m": jc.altitude_m,
        "reference_track": list(jc.reference_track or []),
        "wind": wind,
        "sensor_noise_level": jc.sensor_noise_level,
        "objective_profile": jc.objective_profile,
        "vehicle_profile": vehicle_profile,
        "px4_version": px4_version,
        "parameter_catalog_version": jc.parameter_catalog_version,
        "px4_parameters": px4_parameters,
    }
    scenario_config = dict(ctx.scenario_config or {})
    advanced = scenario_config.get("advanced_scenario_config")
    if not isinstance(advanced, dict):
        advanced = {}
    return {
        "schema_version": "dronedream.trial_input.v2",
        "trial_id": ctx.trial_id,
        "job_id": ctx.job_id,
        "candidate_id": ctx.candidate_id,
        "seed": ctx.seed,
        "attempt_count": ctx.attempt_count,
        "execution_identity": {
            "trial_id": ctx.trial_id,
            "job_id": ctx.job_id,
            "candidate_id": ctx.candidate_id,
            "seed": ctx.seed,
            "attempt_count": ctx.attempt_count,
        },
        "scenario_type": ctx.scenario_type,
        "scenario_config": scenario_config,
        "advanced_scenario_config": advanced,
        # Canonical grouped object.
        "job_config": job_config,
        # Top-level convenience aliases (identical values).
        "track_type": jc.track_type,
        "start_point": start_point,
        "altitude_m": jc.altitude_m,
        "reference_track": list(jc.reference_track or []),
        "wind": wind,
        "sensor_noise_level": jc.sensor_noise_level,
        "objective_profile": jc.objective_profile,
        "vehicle_profile": vehicle_profile,
        "px4_version": px4_version,
        "parameter_catalog_version": jc.parameter_catalog_version,
        "px4_parameters": px4_parameters,
        "parameters": dict(ctx.parameters),
        "output_path": str(output_path),
    }


def _finite_number(
    metrics: dict[str, Any],
    name: str,
    *,
    default: float | None = None,
    nonnegative: bool = False,
) -> float:
    value = metrics.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"metrics.{name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"metrics.{name} must be finite")
    if nonnegative and normalized < 0:
        raise ValueError(f"metrics.{name} must be non-negative")
    return normalized


def _boolean_metric(metrics: dict[str, Any], name: str, *, default: bool) -> bool:
    value = metrics.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"metrics.{name} must be a boolean")
    return value


def _validate_raw_metric_json(value: dict[str, Any]) -> None:
    """Bound and validate the arbitrary metric extension before persistence.

    Python's JSON decoder accepts values such as ``1e999`` as positive
    infinity, even when ``parse_constant`` rejects the non-standard ``Infinity``
    token.  A worker must not pass those values into a database JSON column or
    score/report serializer.  Bounding depth and node count also keeps a small
    result file from becoming an expensive deeply nested persistence payload.
    """

    nodes_seen = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes_seen += 1
        if nodes_seen > _MAX_RAW_METRIC_NODES:
            raise ValueError(
                f"metrics.raw_metric_json exceeds the {_MAX_RAW_METRIC_NODES}-node contract limit"
            )
        if depth > _MAX_RAW_METRIC_DEPTH:
            raise ValueError(
                "metrics.raw_metric_json exceeds "
                f"the {_MAX_RAW_METRIC_DEPTH}-level nesting contract limit"
            )
        if item is None or isinstance(item, (bool, str, int)):
            continue
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("metrics.raw_metric_json numbers must be finite")
            continue
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("metrics.raw_metric_json object keys must be strings")
                stack.append((child, depth + 1))
            continue
        if isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
            continue
        raise ValueError("metrics.raw_metric_json contains a value that is not JSON-compatible")


def _parse_metrics(raw: dict[str, Any]) -> TrialMetricsPayload:
    metrics = raw.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("missing 'metrics' object in trial_result.json")
    required = {"rmse", "max_error", "overshoot_count", "completion_time", "score"}
    missing = required - set(metrics)
    if missing:
        raise ValueError(f"metrics missing required keys: {sorted(missing)}")
    raw_metric_json = metrics.get("raw_metric_json")
    if raw_metric_json is not None and not isinstance(raw_metric_json, dict):
        raise ValueError("raw_metric_json must be an object when present")
    if isinstance(raw_metric_json, dict):
        _validate_raw_metric_json(raw_metric_json)
    overshoot_count = metrics["overshoot_count"]
    if (
        isinstance(overshoot_count, bool)
        or not isinstance(overshoot_count, int)
        or overshoot_count < 0
    ):
        raise ValueError("metrics.overshoot_count must be a non-negative integer")
    return TrialMetricsPayload(
        rmse=_finite_number(metrics, "rmse", nonnegative=True),
        max_error=_finite_number(metrics, "max_error", nonnegative=True),
        overshoot_count=overshoot_count,
        completion_time=_finite_number(metrics, "completion_time", nonnegative=True),
        crash_flag=_boolean_metric(metrics, "crash_flag", default=False),
        timeout_flag=_boolean_metric(metrics, "timeout_flag", default=False),
        score=_finite_number(metrics, "score"),
        final_error=_finite_number(metrics, "final_error", default=0.0, nonnegative=True),
        pass_flag=_boolean_metric(metrics, "pass_flag", default=False),
        instability_flag=_boolean_metric(metrics, "instability_flag", default=False),
        raw_metric_json=dict(raw_metric_json) if raw_metric_json else {},
    )


def _parse_artifacts(raw: dict[str, Any]) -> list[ArtifactMetadata]:
    artifacts_raw = raw.get("artifacts") or []
    if not isinstance(artifacts_raw, list):
        raise ValueError("'artifacts' must be an array")
    artifacts: list[ArtifactMetadata] = []
    for item in artifacts_raw:
        if not isinstance(item, dict):
            raise ValueError("each artifact must be an object")
        artifact_type = item.get("artifact_type")
        display_name = item.get("display_name")
        storage_path = item.get("storage_path")
        if (
            not isinstance(artifact_type, str)
            or not artifact_type.strip()
            or len(artifact_type) > 128
            or any(not (char.isalnum() or char in {"-", "_", "."}) for char in artifact_type)
            or not isinstance(storage_path, str)
            or not storage_path.strip()
        ):
            raise ValueError("artifact requires 'artifact_type' and 'storage_path'")
        mime_type = item.get("mime_type")
        if not isinstance(mime_type, str):
            mime_type = infer_mime_type(artifact_type)
        file_size = item.get("file_size_bytes")
        if file_size is not None and (
            isinstance(file_size, bool) or not isinstance(file_size, int) or file_size < 0
        ):
            raise ValueError("artifact file_size_bytes must be a non-negative integer")
        artifacts.append(
            ArtifactMetadata(
                artifact_type=artifact_type,
                display_name=(
                    display_name.strip()[:255]
                    if isinstance(display_name, str) and display_name.strip()
                    else artifact_type
                ),
                storage_path=storage_path,
                mime_type=mime_type if isinstance(mime_type, str) else None,
                file_size_bytes=file_size,
            )
        )
    return artifacts


def _is_under_allowed_root(path: Path) -> bool:
    resolved = path.resolve()
    settings = get_settings()
    roots = list(settings.allowed_artifact_roots)
    env_root = os.environ.get("REAL_SIMULATOR_ARTIFACT_ROOT")
    if env_root:
        roots.append(Path(env_root).resolve())
    return any(resolved.is_relative_to(root.resolve()) for root in roots)


def _normalize_artifact_path(storage_path: str, run_dir: Path) -> Path:
    path = Path(storage_path)
    return (run_dir / path).resolve() if not path.is_absolute() else path.resolve()


def _validate_known_artifact_payload(artifact: ArtifactMetadata) -> None:
    if artifact.artifact_type not in {"telemetry_json", "reference_track_json"}:
        return
    if artifact.mime_type != "application/json":
        raise ValueError(f"{artifact.artifact_type} must declare mime_type=application/json")
    path = Path(artifact.storage_path)
    size = path.stat().st_size
    if size > _MAX_KNOWN_JSON_ARTIFACT_BYTES:
        raise ValueError(
            f"{artifact.artifact_type} exceeds "
            f"the {_MAX_KNOWN_JSON_ARTIFACT_BYTES} byte validation limit"
        )
    # Read at most one byte beyond the limit as a second fence against a file
    # being replaced or extended between stat() and read().
    with path.open("rb") as stream:
        encoded = stream.read(_MAX_KNOWN_JSON_ARTIFACT_BYTES + 1)
    if len(encoded) > _MAX_KNOWN_JSON_ARTIFACT_BYTES:
        raise ValueError(
            f"{artifact.artifact_type} exceeds "
            f"the {_MAX_KNOWN_JSON_ARTIFACT_BYTES} byte validation limit"
        )
    payload = json.loads(encoded.decode("utf-8"))
    errors = (
        validate_telemetry_payload(payload)
        if artifact.artifact_type == "telemetry_json"
        else validate_reference_track_payload(payload)
    )
    if errors:
        raise ValueError("; ".join(errors))


def _sanitize_artifacts_for_trial(
    artifacts: list[ArtifactMetadata], *, run_dir: Path, trial_id: str
) -> list[ArtifactMetadata]:
    sanitized: list[ArtifactMetadata] = []
    for artifact in artifacts:
        normalized_path = _normalize_artifact_path(artifact.storage_path, run_dir)
        if not _is_under_allowed_root(normalized_path):
            logger.warning(
                "real_cli trial=%s dropped artifact outside allowed roots type=%s path=%s",
                trial_id,
                artifact.artifact_type,
                artifact.storage_path,
            )
            continue
        if not normalized_path.exists() or not normalized_path.is_file():
            logger.warning(
                "real_cli trial=%s dropped missing/non-file artifact type=%s path=%s",
                trial_id,
                artifact.artifact_type,
                artifact.storage_path,
            )
            continue
        artifact.storage_path = str(normalized_path)
        with suppress(OSError):
            artifact.file_size_bytes = normalized_path.stat().st_size
        try:
            _validate_known_artifact_payload(artifact)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "real_cli trial=%s dropped invalid artifact type=%s path=%s: %s",
                trial_id,
                artifact.artifact_type,
                artifact.storage_path,
                exc,
            )
            continue
        sanitized.append(artifact)
    return sanitized


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant is forbidden: {value}")


def _load_result_payload(output_path: Path) -> object:
    size = output_path.stat().st_size
    if size > _MAX_RESULT_BYTES:
        raise ValueError(f"trial_result.json exceeds {_MAX_RESULT_BYTES} byte contract limit")
    try:
        return json.loads(
            output_path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_json_constant,
        )
    except RecursionError as exc:
        raise ValueError("trial_result.json nesting is too deep") from exc


def _validate_result_identity(raw: dict[str, Any], ctx: TrialContext) -> None:
    """Validate any identity fields emitted by a v1-compatible simulator.

    Identity is optional for legacy commands, but once any identity field is
    present it must match the claimed attempt. New v2 runners emit the complete
    ``execution_identity`` object.
    """

    schema_version = raw.get("schema_version")
    if schema_version is not None and schema_version not in {
        "dronedream.trial_result.v1",
        "dronedream.trial_result.v2",
    }:
        raise ValueError(f"unsupported trial result schema_version: {schema_version!r}")
    identity_raw = raw.get("execution_identity")
    if schema_version == "dronedream.trial_result.v2" and identity_raw is None:
        raise ValueError("trial_result.v2 requires execution_identity")
    if identity_raw is not None and not isinstance(identity_raw, dict):
        raise ValueError("execution_identity must be an object when present")
    identity = identity_raw if isinstance(identity_raw, dict) else raw
    expected: dict[str, str | int] = {
        "trial_id": ctx.trial_id,
        "job_id": ctx.job_id,
        "candidate_id": ctx.candidate_id,
        "seed": ctx.seed,
        "attempt_count": ctx.attempt_count,
    }
    present = [name for name in expected if name in identity]
    if identity_raw is not None and set(present) != set(expected):
        missing = sorted(set(expected) - set(present))
        raise ValueError(f"execution_identity missing keys: {missing}")
    for name in present:
        actual = identity[name]
        if isinstance(expected[name], int):
            if isinstance(actual, bool) or not isinstance(actual, int):
                raise ValueError(f"result identity {name} must be an integer")
        elif not isinstance(actual, str):
            raise ValueError(f"result identity {name} must be a string")
        if actual != expected[name]:
            raise ValueError(f"result identity mismatch for {name}: expected {expected[name]!r}")


class RealCliSimulatorAdapter(SimulatorAdapter):
    """Invoke an external CLI-based simulator via subprocess per trial."""

    backend_name = "real_cli"

    def run_trial(self, ctx: TrialContext) -> TrialResult:
        command_template = os.environ.get("REAL_SIMULATOR_COMMAND", "").strip()
        if not command_template:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_ADAPTER_UNAVAILABLE,
                    reason=(
                        "REAL_SIMULATOR_COMMAND is not configured. Set it to the "
                        "external simulator CLI before using backend=real_cli."
                    ),
                ),
                log_excerpt="[real_cli] REAL_SIMULATOR_COMMAND unset",
            )

        artifact_root = Path(os.environ.get("REAL_SIMULATOR_ARTIFACT_ROOT", _DEFAULT_ARTIFACT_ROOT))
        try:
            run_dir = _run_directory(artifact_root, ctx)
            run_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError) as exc:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_ADAPTER_UNAVAILABLE,
                    reason=f"Invalid or inaccessible simulator artifact directory: {exc}",
                ),
                log_excerpt=f"[real_cli] artifact directory error: {exc}",
            )

        input_path = run_dir / "trial_input.json"
        output_path = run_dir / "trial_result.json"
        stdout_path = run_dir / "adapter_stdout.log"
        stderr_path = run_dir / "adapter_stderr.log"

        try:
            payload = _trial_input_payload(ctx, output_path)
            # Never let a retry consume a previous process's successful output.
            output_path.unlink(missing_ok=True)
            _write_json_atomic(input_path, payload)
        except (OSError, TypeError, ValueError) as exc:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_ADAPTER_UNAVAILABLE,
                    reason=f"Could not prepare simulator input: {exc}",
                ),
                log_excerpt=f"[real_cli] input preparation failed: {exc}",
            )

        try:
            baseline_timeout = float(
                os.environ.get("REAL_SIMULATOR_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT))
            )
            vehicle_profile = ctx.job_config.vehicle_profile or {}
            simulation_speed_factor = vehicle_profile.get("simulation_speed_factor", 1.0)
            timeout = _effective_timeout_seconds(
                baseline_timeout,
                simulation_speed_factor,
            )
        except ValueError as exc:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_ADAPTER_UNAVAILABLE,
                    reason=f"Invalid REAL_SIMULATOR_TIMEOUT_SECONDS: {exc}",
                ),
                log_excerpt=f"[real_cli] invalid timeout: {exc}",
            )
        raw_workdir = os.environ.get("REAL_SIMULATOR_WORKDIR", "").strip()
        workdir: str | None = None
        if raw_workdir:
            workdir_path = Path(raw_workdir).expanduser().resolve()
            if not workdir_path.is_dir():
                return TrialResult(
                    success=False,
                    backend=self.backend_name,
                    failure=TrialFailure(
                        code=FAILURE_ADAPTER_UNAVAILABLE,
                        reason=f"REAL_SIMULATOR_WORKDIR is not a directory: {workdir_path}",
                    ),
                    log_excerpt="[real_cli] invalid simulator working directory",
                )
            workdir = str(workdir_path)

        try:
            argv = _build_command(command_template, input_path, output_path)
        except ValueError as exc:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(code=FAILURE_ADAPTER_UNAVAILABLE, reason=str(exc)),
                log_excerpt=f"[real_cli] invalid REAL_SIMULATOR_COMMAND: {exc}",
            )

        logger.info(
            "real_cli trial=%s attempt=%d launching executable=%s argc=%d cwd=%s "
            "timeout_base_1x=%.3fs speed_factor=%s timeout_effective=%.3fs",
            ctx.trial_id,
            ctx.attempt_count,
            argv[0],
            len(argv),
            workdir,
            baseline_timeout,
            simulation_speed_factor,
            timeout,
        )

        child_env = _build_simulator_environment(os.environ)
        child_env.update(
            {
                "DRONEDREAM_TRIAL_ID": ctx.trial_id,
                "DRONEDREAM_JOB_ID": ctx.job_id,
                "DRONEDREAM_CANDIDATE_ID": ctx.candidate_id,
                "DRONEDREAM_TRIAL_SEED": str(ctx.seed),
                "DRONEDREAM_TRIAL_ATTEMPT": str(ctx.attempt_count),
                "DRONEDREAM_TRIAL_INPUT": str(input_path),
                "DRONEDREAM_TRIAL_OUTPUT": str(output_path),
                "DRONEDREAM_SIMULATOR_TIMEOUT_BASE_SECONDS": str(baseline_timeout),
                "DRONEDREAM_SIMULATOR_TIMEOUT_EFFECTIVE_SECONDS": str(timeout),
            }
        )
        try:
            proc = _execute_command(
                argv,
                cwd=workdir,
                env=child_env,
                timeout_seconds=timeout,
                cancellation_event=ctx.cancellation_event,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        except _SimulatorCancelled:
            log = _truncate(
                "STDOUT:\n"
                + _read_log_tail(stdout_path)
                + "\nSTDERR:\n"
                + _read_log_tail(stderr_path)
            )
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_CANCELLED,
                    reason=(
                        f"Simulator execution was cancelled because trial {ctx.trial_id} "
                        "is no longer owned by this worker attempt."
                    ),
                ),
                log_excerpt=log,
            )
        except subprocess.TimeoutExpired:
            log = _truncate(
                "STDOUT:\n"
                + _read_log_tail(stdout_path)
                + "\nSTDERR:\n"
                + _read_log_tail(stderr_path)
            )
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_TIMEOUT,
                    reason=(
                        f"Real simulator exceeded timeout of {timeout:g}s for trial {ctx.trial_id}."
                    ),
                ),
                log_excerpt=log,
            )
        except OSError as exc:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_ADAPTER_UNAVAILABLE,
                    reason=f"Simulator process could not be started: {exc}",
                ),
                log_excerpt=f"[real_cli] process start failed: {exc}",
            )

        combined_log = _truncate(
            f"[real_cli exit={proc.returncode}]\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

        if not output_path.exists():
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_SIMULATION,
                    reason=(
                        "Simulator exited without producing trial_result.json "
                        f"(exit={proc.returncode})."
                    ),
                ),
                log_excerpt=combined_log,
            )

        try:
            raw = _load_result_payload(output_path)
        except (OSError, json.JSONDecodeError, UnicodeError, ValueError) as exc:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_SIMULATION,
                    reason=f"trial_result.json was malformed: {exc}",
                ),
                log_excerpt=combined_log,
            )

        if not isinstance(raw, dict):
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_SIMULATION,
                    reason="trial_result.json must be a JSON object.",
                ),
                log_excerpt=combined_log,
            )

        try:
            _validate_result_identity(raw, ctx)
        except ValueError as exc:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_SIMULATION,
                    reason=f"Simulator result identity was invalid: {exc}",
                ),
                log_excerpt=combined_log,
            )

        log_excerpt = raw.get("log_excerpt")
        log_text = _truncate(
            log_excerpt if isinstance(log_excerpt, str) and log_excerpt else combined_log
        )

        success_value = raw.get("success")
        if not isinstance(success_value, bool):
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_SIMULATION,
                    reason="trial_result.json field 'success' must be a boolean.",
                ),
                log_excerpt=combined_log,
            )

        if not success_value:
            failure_raw = raw.get("failure") if isinstance(raw.get("failure"), dict) else {}
            if not isinstance(failure_raw, dict):
                failure_raw = {}
            code_value = failure_raw.get("code")
            code: str = (
                code_value.strip()[:64]
                if isinstance(code_value, str) and code_value.strip()
                else FAILURE_SIMULATION
            )
            reason_value = failure_raw.get("reason")
            reason: str = (
                _truncate(reason_value.strip(), 1000)
                if isinstance(reason_value, str) and reason_value.strip()
                else "Simulator reported failure without a reason."
            )
            try:
                failure_artifacts = _sanitize_artifacts_for_trial(
                    _parse_artifacts(raw),
                    run_dir=run_dir,
                    trial_id=ctx.trial_id,
                )
            except ValueError:
                failure_artifacts = []
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(code=code, reason=reason),
                artifacts=failure_artifacts,
                log_excerpt=log_text,
            )

        if proc.returncode != 0:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_SIMULATION,
                    reason=(
                        "Simulator reported success but its process exited non-zero "
                        f"(exit={proc.returncode}); result was rejected."
                    ),
                ),
                log_excerpt=combined_log,
            )

        try:
            metrics = _parse_metrics(raw)
            artifacts = _sanitize_artifacts_for_trial(
                _parse_artifacts(raw),
                run_dir=run_dir,
                trial_id=ctx.trial_id,
            )
        except (ValueError, TypeError) as exc:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_SIMULATION,
                    reason=f"Malformed simulator output: {exc}",
                ),
                log_excerpt=combined_log,
            )

        logger.info(
            "real_cli trial=%s success score=%s rmse=%s",
            ctx.trial_id,
            metrics.score,
            metrics.rmse,
        )
        return TrialResult(
            success=True,
            backend=self.backend_name,
            metrics=metrics,
            artifacts=artifacts,
            log_excerpt=log_text,
        )

    def finalize_trial(self, ctx: TrialContext, result: TrialResult | None) -> None:
        """Remove successful transient run data only after artifacts are persisted."""

        success = result is not None and result.success
        if self._keep_run_dirs(success=success):
            return
        artifact_root = Path(os.environ.get("REAL_SIMULATOR_ARTIFACT_ROOT", _DEFAULT_ARTIFACT_ROOT))
        try:
            run_dir = _run_directory(artifact_root, ctx)
        except ValueError:
            logger.warning("refusing to clean unsafe real_cli run directory", exc_info=True)
            return
        self._maybe_cleanup(run_dir, keep=False)

    @staticmethod
    def _keep_run_dirs(*, success: bool) -> bool:
        raw = os.environ.get("REAL_SIMULATOR_KEEP_RUN_DIRS", "true").strip().lower()
        keep = raw not in {"0", "false", "no", "off"}
        # Always keep failure run dirs so operators can inspect.
        return keep or not success

    @staticmethod
    def _maybe_cleanup(run_dir: Path, *, keep: bool) -> None:
        if keep:
            return
        try:
            shutil.rmtree(run_dir)
        except OSError:  # pragma: no cover — best-effort cleanup
            logger.warning("failed to clean run_dir %s", run_dir)


__all__ = ["RealCliSimulatorAdapter"]
