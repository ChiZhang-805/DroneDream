"""Server-derived terminal evidence for the P5 physical-stability matrix.

The desktop runner may request this projection, but it cannot supply any of
the identities, verdicts, readbacks, or hashes below.  They are recomputed from
the authenticated Job, immutable accepted-attempt receipts, and byte-verified
Trial artifacts.  The projection intentionally contains no storage paths,
credentials, raw prompts, or provider request identifiers.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import object_session

from app import models
from app.benchmarking.contracts import Identifier, Sha256Hex, canonical_sha256
from app.benchmarking.physical_stability_assessment import PhysicalStabilityMetricsV1
from app.orchestration.attempt_evidence import (
    TrialAcceptedAttemptEvidenceV1,
    accepted_trial_attempt_evidence,
)
from app.simulator.px4_parameters import EVIDENCE_SCHEMA_VERSION as PARAMETER_EVIDENCE_SCHEMA
from app.simulator.scenario_effects import (
    MAX_EFFECT_CONTRACT_BYTES,
    validate_scenario_effect_evidence,
    validate_scenario_effect_request,
)
from app.storage.evidence import (
    SEALED_ARTIFACT_EVIDENCE,
    candidate_trial_artifact_evidence,
)
from app.storage.factory import get_artifact_storage

_REQUIRED_COMPLETED_ARTIFACT_TYPES = frozenset(
    {
        "telemetry_json",
        "scenario_effect_request_json",
        "scenario_effect_evidence_json",
        "px4_parameters_input_json",
        "px4_parameter_evidence_json",
    }
)
_TERMINAL_JOB_STATUS = {
    "COMPLETED": "completed",
    "FAILED": "failed",
    "CANCELLED": "cancelled",
}
_MAX_PARAMETER_EVIDENCE_BYTES = 2 * 1024 * 1024
TrialSnapshotStatus: TypeAlias = Literal[
    "completed", "failed", "timeout", "cancelled", "indeterminate"
]


class PhysicalStabilityJobEvidenceError(ValueError):
    """Raised when server state cannot support a trustworthy P5 projection."""


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PhysicalStabilityAcceptedTrialSnapshotV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-accepted-trial/v1"] = (
        "dronedream.physical-stability-accepted-trial/v1"
    )
    observed_trial_id: Identifier
    seed: Annotated[int, Field(ge=0, le=2_147_483_647)]
    scenario_type: str = Field(min_length=1, max_length=64)
    terminal_status: Literal["completed", "failed", "timeout", "cancelled", "indeterminate"]
    candidate_id: Identifier
    candidate_is_baseline: Literal[True] = True
    accepted_attempt_id: Identifier | None = None
    accepted_attempt_count: Annotated[int, Field(ge=1)] | None = None
    claim_evidence_id: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    outcome_evidence_id: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    scenario_effect_request_sha256: Sha256Hex | None = None
    effect_readback_receipt_sha256: Sha256Hex | None = None
    parameter_readback_receipt_sha256: Sha256Hex | None = None
    telemetry_sha256: Sha256Hex | None = None
    metric_evidence_sha256: Sha256Hex | None = None
    artifact_inventory_sha256: Sha256Hex | None = None
    artifact_content_sha256: tuple[Sha256Hex, ...] = ()
    effect_ids_read_back: tuple[Identifier, ...] = ()
    metrics: PhysicalStabilityMetricsV1 | None = None
    safety_critical_failure: bool = False
    failure_code: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _validate_terminal(self) -> PhysicalStabilityAcceptedTrialSnapshotV1:
        receipt_fields = (
            self.accepted_attempt_id,
            self.accepted_attempt_count,
            self.claim_evidence_id,
            self.outcome_evidence_id,
        )
        content_fields = (
            self.scenario_effect_request_sha256,
            self.effect_readback_receipt_sha256,
            self.parameter_readback_receipt_sha256,
            self.telemetry_sha256,
            self.metric_evidence_sha256,
            self.artifact_inventory_sha256,
        )
        if self.terminal_status == "completed":
            if (
                any(value is None for value in (*receipt_fields, *content_fields))
                or not self.artifact_content_sha256
                or not self.effect_ids_read_back
                or self.metrics is None
                or self.failure_code is not None
            ):
                raise ValueError("completed P5 Trial snapshot requires complete accepted evidence")
        elif self.failure_code is None or self.metrics is not None:
            raise ValueError("non-completed P5 Trial snapshot requires only a failure code")
        return self


class PhysicalStabilityJobEvidenceSnapshotV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-job-evidence/v1"] = (
        "dronedream.physical-stability-job-evidence/v1"
    )
    observed_job_id: Identifier
    observed_baseline_candidate_id: Identifier
    job_status: Literal["completed", "failed", "cancelled"]
    simulator_backend: Literal["real_cli"] = "real_cli"
    optimizer_strategy: Literal["none"] = "none"
    provider_turns_attempted: Literal[0] = 0
    provider_turns_succeeded: Literal[0] = 0
    provider_requests_attempted: Literal[0] = 0
    provider_requests_succeeded: Literal[0] = 0
    trials: tuple[PhysicalStabilityAcceptedTrialSnapshotV1, ...]

    @model_validator(mode="after")
    def _validate_job(self) -> PhysicalStabilityJobEvidenceSnapshotV1:
        if len(self.trials) != 10 or len({item.observed_trial_id for item in self.trials}) != 10:
            raise ValueError("P5 Job evidence requires ten unique Trial rows")
        if len({item.seed for item in self.trials}) != 10:
            raise ValueError("P5 Job evidence requires ten unique preregistered seeds")
        if any(item.candidate_id != self.observed_baseline_candidate_id for item in self.trials):
            raise ValueError("P5 Job evidence contains a non-baseline Candidate")
        if self.job_status == "completed" and any(
            item.terminal_status != "completed" for item in self.trials
        ):
            raise ValueError("completed P5 Job contains incomplete accepted Trial evidence")
        return self


def _sha256_hex(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise PhysicalStabilityJobEvidenceError(f"{field} is not a SHA-256 evidence ID")
    return value[7:]


def _read_json_object(payload: bytes, *, label: str, max_bytes: int) -> dict[str, Any]:
    if not payload or len(payload) > max_bytes:
        raise PhysicalStabilityJobEvidenceError(f"{label} is missing or exceeds its byte cap")
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PhysicalStabilityJobEvidenceError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PhysicalStabilityJobEvidenceError(f"{label} must be a JSON object")
    return value


def _numeric_mapping_matches(left: object, right: object) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict) or set(left) != set(right):
        return False
    for name, expected in left.items():
        observed = right[name]
        if (
            isinstance(expected, bool)
            or isinstance(observed, bool)
            or not isinstance(expected, int | float)
            or not isinstance(observed, int | float)
            or not math.isfinite(float(expected))
            or not math.isfinite(float(observed))
            or not math.isclose(float(expected), float(observed), rel_tol=0.0, abs_tol=1e-9)
        ):
            return False
    return True


def _terminal_trial_status(
    trial: object,
    *,
    accepted: TrialAcceptedAttemptEvidenceV1 | None,
) -> tuple[TrialSnapshotStatus, str | None]:
    raw_status = getattr(trial, "status", None)
    failure_code = getattr(trial, "failure_code", None)
    if accepted is None:
        return "indeterminate", "MISSING_ACCEPTED_ATTEMPT_EVIDENCE"
    if raw_status == "COMPLETED":
        return "completed", None
    if raw_status == "CANCELLED":
        return "cancelled", failure_code or "TRIAL_CANCELLED"
    if raw_status == "FAILED":
        code = failure_code or "TRIAL_FAILED"
        return ("timeout" if "TIMEOUT" in code.upper() else "failed"), code
    return "indeterminate", "NONTERMINAL_TRIAL_IN_TERMINAL_JOB"


def _query_artifact_rows(job: models.Job, artifact_ids: set[str]) -> dict[str, models.Artifact]:
    session = object_session(job)
    if session is None:
        raise PhysicalStabilityJobEvidenceError("P5 Job evidence requires an attached ORM Job")
    rows = list(
        session.scalars(select(models.Artifact).where(models.Artifact.id.in_(artifact_ids))).all()
    )
    if len(rows) != len(artifact_ids) or {item.id for item in rows} != artifact_ids:
        raise PhysicalStabilityJobEvidenceError("P5 artifact evidence references missing rows")
    return {item.id: item for item in rows}


def _artifact_type_map(artifact_evidence: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    items = artifact_evidence.get("artifacts")
    if not isinstance(items, list):
        raise PhysicalStabilityJobEvidenceError("P5 Trial artifact projection is malformed")
    by_type: dict[str, Mapping[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise PhysicalStabilityJobEvidenceError("P5 Trial artifact item is malformed")
        artifact_type = item.get("artifact_type")
        if not isinstance(artifact_type, str) or artifact_type in by_type:
            raise PhysicalStabilityJobEvidenceError(
                "P5 Trial artifact types are missing or duplicated"
            )
        by_type[artifact_type] = item
    return by_type


def _artifact_payload(
    artifact_type: str,
    *,
    by_type: Mapping[str, Mapping[str, Any]],
    artifact_rows: Mapping[str, models.Artifact],
    payload_overrides: Mapping[str, bytes],
    storage: object | None,
    trial_id: str,
    max_bytes: int,
) -> bytes:
    item = by_type[artifact_type]
    artifact_id = str(item["artifact_id"])
    row = artifact_rows.get(artifact_id)
    if row is None or row.owner_type != "trial" or row.owner_id != trial_id:
        raise PhysicalStabilityJobEvidenceError("P5 artifact ownership diverged")
    if artifact_id in payload_overrides:
        raw = payload_overrides[artifact_id]
    else:
        read_bytes = getattr(storage, "read_bytes", None)
        if not callable(read_bytes):
            raise PhysicalStabilityJobEvidenceError("P5 artifact storage is unavailable")
        raw = read_bytes(row.storage_path)
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        raise PhysicalStabilityJobEvidenceError(
            f"{artifact_type} exceeds the P5 evidence byte cap"
        )
    expected_sha = item.get("content_sha256")
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise PhysicalStabilityJobEvidenceError(
            "P5 artifact bytes diverged after verification"
        )
    return raw


def compile_physical_stability_job_evidence(
    job: models.Job,
    *,
    artifact_evidence_override: Mapping[str, Mapping[str, Any]] | None = None,
    artifact_rows_override: Mapping[str, models.Artifact] | None = None,
    artifact_payloads_override: Mapping[str, bytes] | None = None,
    accepted_attempt_override: Mapping[str, TrialAcceptedAttemptEvidenceV1 | None] | None = None,
) -> PhysicalStabilityJobEvidenceSnapshotV1:
    """Compile one terminal, zero-provider, real_cli Job evidence snapshot."""

    job_status = _TERMINAL_JOB_STATUS.get(job.status)
    if job_status is None:
        raise PhysicalStabilityJobEvidenceError("P5 Job is not terminal")
    if job.simulator_backend_requested != "real_cli" or job.optimizer_strategy != "none":
        raise PhysicalStabilityJobEvidenceError("P5 Job is not baseline-only real_cli")
    provider_counts = (
        job.provider_turns_attempted,
        job.provider_turns_succeeded,
        job.provider_requests_attempted,
        job.provider_requests_succeeded,
    )
    if any(value != 0 for value in provider_counts):
        raise PhysicalStabilityJobEvidenceError("P5 Job contains provider activity")
    if not isinstance(job.baseline_candidate_id, str) or not job.baseline_candidate_id:
        raise PhysicalStabilityJobEvidenceError("P5 Job has no server baseline Candidate")
    baseline = next(
        (
            item
            for item in job.candidates
            if item.id == job.baseline_candidate_id and item.is_baseline
        ),
        None,
    )
    if baseline is None:
        raise PhysicalStabilityJobEvidenceError("P5 Job baseline identity is inconsistent")
    trials = sorted(job.trials, key=lambda item: (item.seed, item.id))
    if len(trials) != 10 or any(item.candidate_id != baseline.id for item in trials):
        raise PhysicalStabilityJobEvidenceError("P5 Job must retain ten baseline Trials")

    artifact_evidence = (
        dict(artifact_evidence_override)
        if artifact_evidence_override is not None
        else candidate_trial_artifact_evidence(baseline, trials, verify_bytes=True)
    )
    if artifact_evidence is None or set(artifact_evidence) != {item.id for item in trials}:
        raise PhysicalStabilityJobEvidenceError("P5 Trial artifact evidence is incomplete")
    artifact_ids = {
        str(item["artifact_id"])
        for evidence in artifact_evidence.values()
        for item in evidence.get("artifacts", [])
        if isinstance(item, Mapping) and isinstance(item.get("artifact_id"), str)
    }
    artifact_rows = (
        dict(artifact_rows_override)
        if artifact_rows_override is not None
        else _query_artifact_rows(job, artifact_ids)
    )
    if set(artifact_rows) != artifact_ids:
        raise PhysicalStabilityJobEvidenceError("P5 artifact row set differs from its receipts")
    payload_overrides = MappingProxyType(dict(artifact_payloads_override or {}))
    storage = None if artifact_payloads_override is not None else get_artifact_storage()

    snapshots: list[PhysicalStabilityAcceptedTrialSnapshotV1] = []
    for trial in trials:
        evidence = artifact_evidence[trial.id]
        accepted = (
            accepted_attempt_override.get(trial.id)
            if accepted_attempt_override is not None
            else accepted_trial_attempt_evidence(trial, artifact_evidence=evidence)
        )
        if accepted is not None and (
            accepted.trial_id != trial.id
            or accepted.terminal_status != trial.status
            or accepted.artifact_evidence_sha256
            != "sha256:" + canonical_sha256(dict(evidence))
        ):
            raise PhysicalStabilityJobEvidenceError(
                "P5 accepted attempt does not bind the current Trial artifact projection"
            )
        terminal_status, failure_code = _terminal_trial_status(trial, accepted=accepted)
        if terminal_status != "completed":
            snapshots.append(
                PhysicalStabilityAcceptedTrialSnapshotV1(
                    observed_trial_id=trial.id,
                    seed=trial.seed,
                    scenario_type=trial.scenario_type,
                    terminal_status=terminal_status,
                    candidate_id=trial.candidate_id,
                    failure_code=failure_code,
                )
            )
            continue
        if accepted is None:  # Narrowing guard; completed status requires accepted evidence.
            raise PhysicalStabilityJobEvidenceError(
                "completed P5 Trial lost its accepted attempt evidence"
            )

        by_type = _artifact_type_map(evidence)
        if not _REQUIRED_COMPLETED_ARTIFACT_TYPES.issubset(by_type):
            missing = sorted(_REQUIRED_COMPLETED_ARTIFACT_TYPES - set(by_type))
            raise PhysicalStabilityJobEvidenceError(
                "completed P5 Trial is missing required artifacts: " + ", ".join(missing)
            )
        if any(
            item.get("content_evidence") != SEALED_ARTIFACT_EVIDENCE
            for item in by_type.values()
        ):
            raise PhysicalStabilityJobEvidenceError(
                "completed P5 Trial contains non-byte-verifiable artifacts"
            )

        request = validate_scenario_effect_request(
            _read_json_object(
                _artifact_payload(
                    "scenario_effect_request_json",
                    by_type=by_type,
                    artifact_rows=artifact_rows,
                    payload_overrides=payload_overrides,
                    storage=storage,
                    trial_id=trial.id,
                    max_bytes=MAX_EFFECT_CONTRACT_BYTES,
                ),
                label="scenario-effect request",
                max_bytes=MAX_EFFECT_CONTRACT_BYTES,
            )
        )
        effect = validate_scenario_effect_evidence(
            request,
            _read_json_object(
                _artifact_payload(
                    "scenario_effect_evidence_json",
                    by_type=by_type,
                    artifact_rows=artifact_rows,
                    payload_overrides=payload_overrides,
                    storage=storage,
                    trial_id=trial.id,
                    max_bytes=MAX_EFFECT_CONTRACT_BYTES,
                ),
                label="scenario-effect evidence",
                max_bytes=MAX_EFFECT_CONTRACT_BYTES,
            ),
        )
        if (
            effect["verification_status"] != "verified_applied"
            or effect["requested_effects"] != effect["applied_effects"]
        ):
            raise PhysicalStabilityJobEvidenceError("P5 scenario effects were not fully read back")
        px4_input = _read_json_object(
            _artifact_payload(
                "px4_parameters_input_json",
                by_type=by_type,
                artifact_rows=artifact_rows,
                payload_overrides=payload_overrides,
                storage=storage,
                trial_id=trial.id,
                max_bytes=_MAX_PARAMETER_EVIDENCE_BYTES,
            ),
            label="PX4 parameter input",
            max_bytes=_MAX_PARAMETER_EVIDENCE_BYTES,
        )
        parameter = _read_json_object(
            _artifact_payload(
                "px4_parameter_evidence_json",
                by_type=by_type,
                artifact_rows=artifact_rows,
                payload_overrides=payload_overrides,
                storage=storage,
                trial_id=trial.id,
                max_bytes=_MAX_PARAMETER_EVIDENCE_BYTES,
            ),
            label="PX4 parameter evidence",
            max_bytes=_MAX_PARAMETER_EVIDENCE_BYTES,
        )
        if (
            parameter.get("schema_version") != PARAMETER_EVIDENCE_SCHEMA
            or parameter.get("kind") != "applied"
            or parameter.get("status") != "ok"
            or parameter.get("context")
            != {"trial_id": trial.id, "job_id": job.id, "candidate_id": baseline.id}
            or not isinstance(parameter.get("verification"), dict)
            or parameter["verification"].get("verified") is not True
            or parameter["verification"].get("mismatches") != {}
            or not _numeric_mapping_matches(px4_input, parameter.get("values"))
        ):
            raise PhysicalStabilityJobEvidenceError("P5 PX4 parameter readback is not verified")
        metric = trial.metric
        if metric is None:
            raise PhysicalStabilityJobEvidenceError("completed P5 Trial metrics are incomplete")
        rmse = metric.rmse
        max_error = metric.max_error
        completion_time = metric.completion_time
        pass_flag = metric.pass_flag
        if rmse is None or max_error is None or completion_time is None or pass_flag is None:
            raise PhysicalStabilityJobEvidenceError("completed P5 Trial metrics are incomplete")
        metric_snapshot = PhysicalStabilityMetricsV1(
            rmse=float(rmse),
            max_error=float(max_error),
            completion_time_seconds=float(completion_time),
            pass_flag=bool(pass_flag),
            crash_flag=bool(metric.crash_flag),
            timeout_flag=bool(metric.timeout_flag),
            instability_flag=bool(metric.instability_flag),
        )
        content_hashes = tuple(
            sorted(str(item["content_sha256"]) for item in by_type.values())
        )
        snapshots.append(
            PhysicalStabilityAcceptedTrialSnapshotV1(
                observed_trial_id=trial.id,
                seed=trial.seed,
                scenario_type=trial.scenario_type,
                terminal_status="completed",
                candidate_id=trial.candidate_id,
                accepted_attempt_id=accepted.attempt_id,
                accepted_attempt_count=accepted.attempt_count,
                claim_evidence_id=accepted.claim_evidence_id,
                outcome_evidence_id=accepted.outcome_evidence_id,
                scenario_effect_request_sha256=request["request_sha256"],
                effect_readback_receipt_sha256=str(
                    by_type["scenario_effect_evidence_json"]["content_sha256"]
                ),
                parameter_readback_receipt_sha256=str(
                    by_type["px4_parameter_evidence_json"]["content_sha256"]
                ),
                telemetry_sha256=str(by_type["telemetry_json"]["content_sha256"]),
                metric_evidence_sha256=_sha256_hex(
                    accepted.metric_sha256, field="accepted metric evidence"
                ),
                artifact_inventory_sha256=canonical_sha256(dict(evidence)),
                artifact_content_sha256=content_hashes,
                effect_ids_read_back=tuple(effect["applied_effects"]),
                metrics=metric_snapshot,
                safety_critical_failure=(
                    metric_snapshot.crash_flag
                    or metric_snapshot.timeout_flag
                    or metric_snapshot.instability_flag
                ),
            )
        )

    return PhysicalStabilityJobEvidenceSnapshotV1(
        observed_job_id=job.id,
        observed_baseline_candidate_id=baseline.id,
        job_status=job_status,  # type: ignore[arg-type]
        trials=tuple(snapshots),
    )


__all__ = [
    "PhysicalStabilityAcceptedTrialSnapshotV1",
    "PhysicalStabilityJobEvidenceError",
    "PhysicalStabilityJobEvidenceSnapshotV1",
    "compile_physical_stability_job_evidence",
]
