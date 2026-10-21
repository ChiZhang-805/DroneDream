"""Content-addressed subprocess boundary for the HEBO reference adapter.

This module intentionally does not import HEBO into the product environment.
The production coordinator must supply an independently locked Python
environment and runner.  The adapter exposes only the frozen benchmark
observation, replays real feasible scalar losses, and validates the one
candidate response before it may enter the shared evaluator.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.adapters import BenchmarkAdapterError, search_space_from_observation
from app.benchmarking.contracts import (
    BenchmarkObservationV2,
    BenchmarkProposalV1,
    Sha256Hex,
    canonical_json_bytes,
    canonical_sha256,
)
from app.benchmarking.hebo_reference_contract import (
    HEBO_DISTRIBUTION_LOCK_SHA256,
    HEBO_POLICY_SHA256,
    HeboPreparedContractV1,
    prepare_hebo_contract,
)

HEBO_RUNNER_REQUEST_SCHEMA_ID: Final = "dronedream.benchmark-hebo-runner-request/v1"
HEBO_RUNNER_RESPONSE_SCHEMA_ID: Final = "dronedream.benchmark-hebo-runner-response/v1"
HEBO_RUNNER_PROTOCOL_VERSION: Final = "hebo-isolated-json-stdio/v1"
HEBO_RUNNER_MAX_REQUEST_BYTES: Final = 262_144
HEBO_RUNNER_MAX_RESPONSE_BYTES: Final = 65_536
HEBO_RUNNER_MAX_STDERR_BYTES: Final = 16_384


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
    )


class HeboParameterDomainV1(_StrictFrozen):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    baseline: float
    minimum: float
    maximum: float
    step: float | None
    scale: Literal["linear", "log"]
    value_type: Literal["float", "integer", "boolean", "enum"]
    choices: tuple[float, ...]
    enabled: bool
    locked: bool


class HeboFeasibleObservationV1(_StrictFrozen):
    candidate_ref: Annotated[str, Field(min_length=1, max_length=128)]
    dispatch_ordinal: Annotated[int, Field(ge=1, le=10_000)]
    parameters: dict[str, float] = Field(min_length=1, max_length=64)
    loss: float


class HeboRunnerRequestV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-hebo-runner-request/v1"] = (
        HEBO_RUNNER_REQUEST_SCHEMA_ID
    )
    protocol_version: Literal["hebo-isolated-json-stdio/v1"] = HEBO_RUNNER_PROTOCOL_VERSION
    adapter_id: Literal["hebo/v1"] = "hebo/v1"
    prepared_contract_sha256: Sha256Hex
    observation_sha256: Sha256Hex
    distribution_lock_sha256: Sha256Hex
    policy_sha256: Sha256Hex
    parameter_domain: tuple[HeboParameterDomainV1, ...]
    feasible_history: tuple[HeboFeasibleObservationV1, ...]
    excluded_outcome_sha256: Sha256Hex
    excluded_outcome_count: Annotated[int, Field(ge=0, le=10_000)]
    dimensions: Annotated[int, Field(ge=1, le=128)]
    algorithm_seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    next_trial_number: Annotated[int, Field(ge=0, le=10_000)]
    sobol_draws_consumed: Annotated[int, Field(ge=0, le=10_000)]
    request_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_binding(self) -> HeboRunnerRequestV1:
        if self.distribution_lock_sha256 != HEBO_DISTRIBUTION_LOCK_SHA256:
            raise ValueError("HEBO runner request distribution lock differs")
        if self.policy_sha256 != HEBO_POLICY_SHA256:
            raise ValueError("HEBO runner request policy differs")
        if self.sobol_draws_consumed != self.next_trial_number:
            raise ValueError("HEBO runner request must account for every Sobol draw")
        if len(self.feasible_history) + self.excluded_outcome_count != self.next_trial_number:
            raise ValueError("HEBO runner request history counts are incomplete")
        ordinals = [item.dispatch_ordinal for item in self.feasible_history]
        if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
            raise ValueError("HEBO feasible history must use unique ascending ordinals")
        payload = self.model_dump(mode="json", exclude={"request_sha256"})
        if canonical_sha256(payload) != self.request_sha256:
            raise ValueError("HEBO runner request hash does not match")
        return self


class HeboRunnerResponseV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-hebo-runner-response/v1"] = (
        HEBO_RUNNER_RESPONSE_SCHEMA_ID
    )
    protocol_version: Literal["hebo-isolated-json-stdio/v1"] = HEBO_RUNNER_PROTOCOL_VERSION
    adapter_id: Literal["hebo/v1"] = "hebo/v1"
    status: Literal["proposed"] = "proposed"
    request_sha256: Sha256Hex
    runner_environment_sha256: Sha256Hex
    distribution_lock_sha256: Sha256Hex
    policy_sha256: Sha256Hex
    observed_feasible_count: Annotated[int, Field(ge=0, le=10_000)]
    sobol_draws_consumed: Annotated[int, Field(ge=0, le=10_000)]
    parameters: dict[str, float] = Field(min_length=1, max_length=64)
    response_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_binding(self) -> HeboRunnerResponseV1:
        if self.distribution_lock_sha256 != HEBO_DISTRIBUTION_LOCK_SHA256:
            raise ValueError("HEBO runner response distribution lock differs")
        if self.policy_sha256 != HEBO_POLICY_SHA256:
            raise ValueError("HEBO runner response policy differs")
        payload = self.model_dump(mode="json", exclude={"response_sha256"})
        if canonical_sha256(payload) != self.response_sha256:
            raise ValueError("HEBO runner response hash does not match")
        return self


@runtime_checkable
class HeboRunnerTransport(Protocol):
    @property
    def runner_environment_sha256(self) -> str:
        """Hash of the separately locked interpreter and dependency environment."""

    def invoke(self, request: HeboRunnerRequestV1) -> HeboRunnerResponseV1:
        """Return one response over the bounded, isolated runner boundary."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _capture_pipe_bounded(
    *,
    stream: Any,
    limit: int,
    process: subprocess.Popen[bytes],
    output: bytearray,
    overflow: threading.Event,
) -> None:
    try:
        while chunk := stream.read(8192):
            remaining = limit - len(output)
            if remaining > 0:
                output.extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow.set()
                with suppress(OSError):
                    process.terminate()
                return
    finally:
        stream.close()


def _write_stdin_bounded(
    *,
    stream: Any,
    request_bytes: bytes,
    failed: threading.Event,
) -> None:
    try:
        stream.write(request_bytes)
        stream.flush()
    except BrokenPipeError:
        return
    except OSError:
        failed.set()
    finally:
        stream.close()


def _run_isolated_bounded(
    *,
    argv: list[str],
    request_bytes: bytes,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: float,
) -> tuple[int, bytes, bytes, bool, bool, bool]:
    # Every argv element is assembled from the validated interpreter and
    # repository-owned runner path below; no request value reaches argv.
    process = subprocess.Popen(  # noqa: S603
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=environment,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if process.stdin is None or process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise RuntimeError("isolated HEBO subprocess pipes were not created")
    stdout = bytearray()
    stderr = bytearray()
    stdout_overflow = threading.Event()
    stderr_overflow = threading.Event()
    stdin_failed = threading.Event()
    writer = threading.Thread(
        target=_write_stdin_bounded,
        kwargs={
            "stream": process.stdin,
            "request_bytes": request_bytes,
            "failed": stdin_failed,
        },
        daemon=True,
    )
    readers = (
        threading.Thread(
            target=_capture_pipe_bounded,
            kwargs={
                "stream": process.stdout,
                "limit": HEBO_RUNNER_MAX_RESPONSE_BYTES,
                "process": process,
                "output": stdout,
                "overflow": stdout_overflow,
            },
            daemon=True,
        ),
        threading.Thread(
            target=_capture_pipe_bounded,
            kwargs={
                "stream": process.stderr,
                "limit": HEBO_RUNNER_MAX_STDERR_BYTES,
                "process": process,
                "output": stderr,
                "overflow": stderr_overflow,
            },
            daemon=True,
        ),
    )
    writer.start()
    for reader in readers:
        reader.start()
    try:
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            with suppress(OSError):
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with suppress(OSError):
                    process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired as kill_exc:
                    raise BenchmarkAdapterError(
                        "HEBO isolated runner did not terminate after timeout"
                    ) from kill_exc
            raise BenchmarkAdapterError("HEBO isolated runner timed out") from exc
    finally:
        writer.join(timeout=5)
        for reader in readers:
            reader.join(timeout=5)
        if writer.is_alive():
            with suppress(OSError):
                process.kill()
            raise BenchmarkAdapterError("HEBO isolated runner input pipe did not close")
        if any(reader.is_alive() for reader in readers):
            with suppress(OSError):
                process.kill()
            raise BenchmarkAdapterError("HEBO isolated runner output pipe did not close")
    return (
        returncode,
        bytes(stdout),
        bytes(stderr),
        stdout_overflow.is_set(),
        stderr_overflow.is_set(),
        stdin_failed.is_set(),
    )


@dataclass(frozen=True, slots=True)
class JsonSubprocessHeboRunnerV1:
    """Invoke a pre-provisioned HEBO worker without a shell or inherited secrets."""

    python_executable: Path
    runner_script: Path
    expected_python_sha256: str
    expected_runner_script_sha256: str
    runner_environment_sha256: str
    timeout_seconds: float = 30.0

    def _validate_identity(self) -> None:
        for label, path, expected in (
            ("python", self.python_executable, self.expected_python_sha256),
            ("runner", self.runner_script, self.expected_runner_script_sha256),
        ):
            if not path.is_absolute() or not path.is_file():
                raise BenchmarkAdapterError(f"HEBO isolated {label} path is unavailable")
            if path.is_symlink() or path.resolve(strict=True) != path:
                raise BenchmarkAdapterError(f"HEBO isolated {label} path is not canonical")
            if _file_sha256(path) != expected:
                raise BenchmarkAdapterError(f"HEBO isolated {label} hash drifted")
        for label, value in (
            ("python", self.expected_python_sha256),
            ("runner", self.expected_runner_script_sha256),
            ("environment", self.runner_environment_sha256),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise BenchmarkAdapterError(f"HEBO isolated {label} hash is invalid")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 300:
            raise BenchmarkAdapterError("HEBO isolated runner timeout is outside policy")

    def invoke(self, request: HeboRunnerRequestV1) -> HeboRunnerResponseV1:
        self._validate_identity()
        request_bytes = canonical_json_bytes(request) + b"\n"
        if len(request_bytes) > HEBO_RUNNER_MAX_REQUEST_BYTES:
            raise BenchmarkAdapterError("HEBO isolated runner request exceeds byte cap")

        environment = {
            key: value
            for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH")
            if (value := os.environ.get(key))
        }
        environment.update(
            {
                "PYTHONHASHSEED": str(request.algorithm_seed),
                "PYTHONNOUSERSITE": "1",
                "DRONEDREAM_HEBO_RUNNER_ENV_SHA256": self.runner_environment_sha256,
            }
        )
        try:
            (
                returncode,
                stdout,
                stderr,
                stdout_overflow,
                stderr_overflow,
                stdin_failed,
            ) = _run_isolated_bounded(
                argv=[
                    str(self.python_executable),
                    "-I",
                    str(self.runner_script),
                    "--stdio-json-v1",
                ],
                request_bytes=request_bytes,
                cwd=self.runner_script.parent,
                environment=environment,
                timeout_seconds=self.timeout_seconds,
            )
        except OSError as exc:
            raise BenchmarkAdapterError("HEBO isolated runner could not start") from exc

        if stdout_overflow or stderr_overflow:
            raise BenchmarkAdapterError("HEBO isolated runner output exceeds byte cap")
        if stdin_failed:
            raise BenchmarkAdapterError("HEBO isolated runner input pipe failed")
        if returncode != 0:
            stderr_sha256 = hashlib.sha256(stderr).hexdigest()
            raise BenchmarkAdapterError(
                f"HEBO isolated runner failed (exit={returncode}, stderr_sha256={stderr_sha256})"
            )
        if stderr:
            raise BenchmarkAdapterError("HEBO isolated runner emitted unexpected stderr")
        if not stdout:
            raise BenchmarkAdapterError("HEBO isolated runner response is empty or exceeds cap")
        try:
            payload = json.loads(stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BenchmarkAdapterError("HEBO isolated runner returned invalid JSON") from exc
        try:
            return HeboRunnerResponseV1.model_validate(payload)
        except ValueError as exc:
            raise BenchmarkAdapterError(
                "HEBO isolated runner response failed schema validation"
            ) from exc


def build_hebo_runner_request(
    observation: BenchmarkObservationV2,
    prepared: HeboPreparedContractV1 | None = None,
) -> HeboRunnerRequestV1:
    prepared_contract = prepared or prepare_hebo_contract(observation)
    if prepared_contract.observation_sha256 != canonical_sha256(observation):
        raise BenchmarkAdapterError("HEBO prepared contract belongs to another observation")
    space = search_space_from_observation(observation)
    domains: list[HeboParameterDomainV1] = []
    for domain in space.domains:
        if domain.scale not in {"linear", "log"}:
            raise BenchmarkAdapterError("HEBO parameter scale is unsupported")
        if domain.value_type not in {"float", "integer", "boolean", "enum"}:
            raise BenchmarkAdapterError("HEBO parameter value type is unsupported")
        domains.append(
            HeboParameterDomainV1(
                name=domain.name,
                baseline=float(domain.baseline),
                minimum=float(domain.minimum),
                maximum=float(domain.maximum),
                step=None if domain.step is None else float(domain.step),
                scale=cast(Literal["linear", "log"], domain.scale),
                value_type=cast(
                    Literal["float", "integer", "boolean", "enum"],
                    domain.value_type,
                ),
                choices=tuple(float(choice) for choice in domain.choices),
                enabled=domain.enabled,
                locked=domain.locked,
            )
        )
    feasible_history: list[HeboFeasibleObservationV1] = []
    for item in observation.history:
        if item.outcome.role != "objective" or not item.outcome.feasible:
            continue
        if item.outcome.loss is None:
            raise BenchmarkAdapterError("HEBO feasible objective outcome has no scalar loss")
        feasible_history.append(
            HeboFeasibleObservationV1(
                candidate_ref=item.candidate_ref,
                dispatch_ordinal=item.dispatch_ordinal,
                parameters=dict(item.parameters),
                loss=float(item.outcome.loss),
            )
        )
    payload: dict[str, Any] = {
        "schema_id": HEBO_RUNNER_REQUEST_SCHEMA_ID,
        "protocol_version": HEBO_RUNNER_PROTOCOL_VERSION,
        "adapter_id": "hebo/v1",
        "prepared_contract_sha256": prepared_contract.binding_sha256,
        "observation_sha256": prepared_contract.observation_sha256,
        "distribution_lock_sha256": prepared_contract.distribution_lock_sha256,
        "policy_sha256": prepared_contract.policy_sha256,
        "parameter_domain": tuple(item.model_dump(mode="python") for item in domains),
        "feasible_history": tuple(item.model_dump(mode="python") for item in feasible_history),
        "excluded_outcome_sha256": prepared_contract.excluded_outcome_sha256,
        "excluded_outcome_count": (
            prepared_contract.infeasible_objective_outcomes
            + prepared_contract.nonobjective_outcomes
        ),
        "dimensions": prepared_contract.dimensions,
        "algorithm_seed": prepared_contract.algorithm_seed,
        "next_trial_number": prepared_contract.next_trial_number,
        "sobol_draws_consumed": prepared_contract.sobol_draws_consumed,
    }
    return HeboRunnerRequestV1.model_validate(
        {**payload, "request_sha256": canonical_sha256(payload)}
    )


@dataclass(frozen=True, slots=True)
class HeboIsolatedAdapterV1:
    """Validate one HEBO proposal from a separately managed environment."""

    runner: HeboRunnerTransport
    adapter_id: Literal["hebo/v1"] = "hebo/v1"

    def propose(self, observation: BenchmarkObservationV2) -> BenchmarkProposalV1:
        request = build_hebo_runner_request(observation)
        response = self.runner.invoke(request)
        if response.request_sha256 != request.request_sha256:
            raise BenchmarkAdapterError("HEBO response belongs to another request")
        if response.runner_environment_sha256 != self.runner.runner_environment_sha256:
            raise BenchmarkAdapterError("HEBO response environment identity differs")
        if response.observed_feasible_count != len(request.feasible_history):
            raise BenchmarkAdapterError("HEBO response observed a different feasible history")
        if response.sobol_draws_consumed != request.sobol_draws_consumed:
            raise BenchmarkAdapterError("HEBO response Sobol replay count differs")

        space = search_space_from_observation(observation)
        expected_names = {domain.name for domain in space.domains}
        if set(response.parameters) != expected_names:
            raise BenchmarkAdapterError("HEBO response parameter set differs from the domain")
        projected = space.project(response.parameters)
        if projected != response.parameters:
            raise BenchmarkAdapterError("HEBO response parameters are outside the frozen domain")
        response_key = canonical_sha256(projected)
        if any(canonical_sha256(item.parameters) == response_key for item in observation.history):
            raise BenchmarkAdapterError("HEBO response repeated a dispatched candidate")

        candidate_ref = f"hebo-{response.response_sha256[:24]}"
        return BenchmarkProposalV1(
            candidate_ref=candidate_ref,
            parameters=projected,
            reason_code="standard-reference-hebo-isolated",
            proposal_receipt={
                "adapter_id": self.adapter_id,
                "adapter_contract_id": "dronedream.benchmark-proposal-adapter/v1",
                "method_classification": "standard_reference",
                "observation_sha256": request.observation_sha256,
                "prepared_contract_sha256": request.prepared_contract_sha256,
                "runner_request_sha256": request.request_sha256,
                "runner_response_sha256": response.response_sha256,
                "runner_environment_sha256": response.runner_environment_sha256,
                "distribution_lock_sha256": response.distribution_lock_sha256,
                "policy_sha256": response.policy_sha256,
                "observed_feasible_count": response.observed_feasible_count,
                "excluded_outcome_count": request.excluded_outcome_count,
                "excluded_outcome_sha256": request.excluded_outcome_sha256,
                "sobol_draws_consumed": response.sobol_draws_consumed,
                "provider_access": False,
                "holdout_visibility": "sealed",
            },
        )


__all__ = [
    "HEBO_RUNNER_MAX_REQUEST_BYTES",
    "HEBO_RUNNER_MAX_RESPONSE_BYTES",
    "HEBO_RUNNER_MAX_STDERR_BYTES",
    "HEBO_RUNNER_PROTOCOL_VERSION",
    "HEBO_RUNNER_REQUEST_SCHEMA_ID",
    "HEBO_RUNNER_RESPONSE_SCHEMA_ID",
    "HeboFeasibleObservationV1",
    "HeboIsolatedAdapterV1",
    "HeboParameterDomainV1",
    "HeboRunnerRequestV1",
    "HeboRunnerResponseV1",
    "HeboRunnerTransport",
    "JsonSubprocessHeboRunnerV1",
    "build_hebo_runner_request",
]
