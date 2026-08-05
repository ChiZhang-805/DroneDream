"""Source-bound, resumable bridge contracts for P5 physical stability.

This module compiles the preregistered P5 manifest into six complete
``JobCreateRequest`` payloads and connects those payloads to the immutable
execution ledger through dependency-injected transports and checkpoint stores.
It contains no desktop, HTTP, PX4, Gazebo, credential, or filesystem adapter.
Production execution therefore remains impossible until a separately reviewed
adapter implements these protocols inside an explicitly approved RED window.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app import schemas
from app.benchmarking.contracts import GitCommit, Identifier, Sha256Hex, canonical_sha256
from app.benchmarking.physical_stability import (
    PhysicalStabilityManifestV1,
    PhysicalStabilityTrialPlanItemV1,
    PhysicalStabilityTrialPlanV1,
    compile_physical_stability_job_request,
)
from app.benchmarking.physical_stability_execution import (
    PhysicalStabilityExecutionLedgerV1,
    PhysicalStabilityLedgerTransitionV1,
    record_physical_stability_dispatch_attempt,
    record_physical_stability_job_observed,
    record_physical_stability_terminal_observation,
)

PHYSICAL_STABILITY_EXECUTION_BUNDLE_SCHEMA_ID: Final[
    Literal["dronedream.physical-stability-execution-bundle/v1"]
] = "dronedream.physical-stability-execution-bundle/v1"
PHYSICAL_STABILITY_TERMINAL_OBSERVATION_SCHEMA_ID: Final[
    Literal["dronedream.physical-stability-terminal-observation/v1"]
] = "dronedream.physical-stability-terminal-observation/v1"

TrialTerminalStatus = Literal["completed", "failed", "timeout", "cancelled", "indeterminate"]
JobTerminalStatus = Literal["completed", "failed", "timeout", "cancelled", "indeterminate"]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _job_request_schema_sha256() -> str:
    payload = json.dumps(
        schemas.JobCreateRequest.model_json_schema(mode="validation"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class PhysicalStabilityExecutionTrialBindingV1(_StrictFrozen):
    trial_ordinal: Annotated[int, Field(ge=1, le=60)]
    planned_trial_id: Identifier
    seed: Annotated[int, Field(ge=0, le=2_147_483_647)]
    input_contract_sha256: Sha256Hex
    scenario_effect_request_sha256: Sha256Hex
    expected_effect_ids: tuple[Identifier, ...]


class PhysicalStabilityExecutionJobV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-execution-job/v1"] = (
        "dronedream.physical-stability-execution-job/v1"
    )
    scenario_ordinal: Annotated[int, Field(ge=1, le=6)]
    scenario_id: Identifier
    planned_job_id: Identifier
    idempotency_key: Annotated[str, Field(pattern=r"^p5-[0-9a-f]{16}-[0-9]{2}-[0-9a-f]{16}$")]
    request_payload: dict[str, Any]
    request_sha256: Sha256Hex
    trials: tuple[PhysicalStabilityExecutionTrialBindingV1, ...]

    @model_validator(mode="after")
    def _validate_job(self) -> PhysicalStabilityExecutionJobV1:
        request = schemas.JobCreateRequest.model_validate(self.request_payload)
        if canonical_sha256(request) != self.request_sha256:
            raise ValueError("P5 Job request hash does not recompute")
        if request.simulator_backend != "real_cli" or request.optimizer_strategy != "none":
            raise ValueError("P5 Job request must be baseline-only real_cli")
        if request.provider_turn_cap != 0 or request.provider_request_cap != 0:
            raise ValueError("P5 Job request must be zero-provider")
        if request.openai is not None or request.llm is not None:
            raise ValueError("P5 Job request cannot contain provider credentials")
        if request.max_total_trials != 10 or request.trials_per_candidate != 10:
            raise ValueError("P5 Job request must reserve exactly ten physical trials")
        if len(request.scenario_suite.cases) != 1:
            raise ValueError("P5 Job request must contain exactly one scenario case")
        case = request.scenario_suite.cases[0]
        if case.id != self.scenario_id or tuple(case.seeds) != tuple(
            item.seed for item in self.trials
        ):
            raise ValueError("P5 Job request scenario/seeds do not match its trial bindings")
        if len(self.trials) != 10 or len({item.planned_trial_id for item in self.trials}) != 10:
            raise ValueError("P5 execution Job requires ten unique planned trials")
        if any(not item.expected_effect_ids for item in self.trials):
            raise ValueError("every P5 trial must bind at least one expected physical effect")
        return self


class PhysicalStabilityExecutionBundleV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-execution-bundle/v1"] = (
        PHYSICAL_STABILITY_EXECUTION_BUNDLE_SCHEMA_ID
    )
    repository_subject_commit: GitCommit
    manifest_sha256: Sha256Hex
    plan_sha256: Sha256Hex
    composite_execution_inventory_sha256: Sha256Hex
    job_create_request_schema_sha256: Sha256Hex
    provider_logical_turn_cap: Literal[0] = 0
    provider_network_request_cap: Literal[0] = 0
    execution_authorized: Literal[False] = False
    jobs: tuple[PhysicalStabilityExecutionJobV1, ...]

    @model_validator(mode="after")
    def _validate_bundle(self) -> PhysicalStabilityExecutionBundleV1:
        if self.job_create_request_schema_sha256 != _job_request_schema_sha256():
            raise ValueError("JobCreateRequest schema hash does not match this source")
        if len(self.jobs) != 6:
            raise ValueError("P5 execution bundle requires exactly six Jobs")
        if tuple(item.scenario_ordinal for item in self.jobs) != tuple(range(1, 7)):
            raise ValueError("P5 execution Jobs must remain in preregistered order")
        trials = tuple(trial for job in self.jobs for trial in job.trials)
        if len(trials) != 60:
            raise ValueError("P5 execution bundle requires exactly sixty trials")
        if tuple(item.trial_ordinal for item in trials) != tuple(range(1, 61)):
            raise ValueError("P5 execution trial ordinals must be contiguous")
        if len({item.planned_trial_id for item in trials}) != 60:
            raise ValueError("P5 execution trial IDs must be unique")
        return self


def _binding(item: PhysicalStabilityTrialPlanItemV1) -> PhysicalStabilityExecutionTrialBindingV1:
    return PhysicalStabilityExecutionTrialBindingV1(
        trial_ordinal=item.trial_ordinal,
        planned_trial_id=item.trial_id,
        seed=item.seed,
        input_contract_sha256=item.input_contract_sha256,
        scenario_effect_request_sha256=item.scenario_effect_request_sha256,
        expected_effect_ids=item.expected_effect_ids,
    )


def build_physical_stability_execution_bundle(
    manifest: PhysicalStabilityManifestV1,
    plan: PhysicalStabilityTrialPlanV1,
) -> PhysicalStabilityExecutionBundleV1:
    """Compile six exact API payloads without granting permission to execute."""

    manifest_sha = canonical_sha256(manifest)
    plan_sha = canonical_sha256(plan)
    inventory_sha = canonical_sha256(manifest.composite_execution_inventory)
    if plan.manifest_sha256 != manifest_sha:
        raise ValueError("P5 plan does not bind the supplied manifest")
    if plan.repository_subject_commit != manifest.repository_subject_commit:
        raise ValueError("P5 plan and manifest repository subjects differ")
    if plan.composite_execution_inventory_sha256 != inventory_sha:
        raise ValueError("P5 plan does not bind the supplied composite inventory")
    if manifest.execution_authorized or plan.execution_authorized:
        raise ValueError("P5 source contracts must remain unable to self-authorize")

    jobs: list[PhysicalStabilityExecutionJobV1] = []
    for ordinal, scenario in enumerate(manifest.scenarios, start=1):
        request = compile_physical_stability_job_request(manifest, scenario)
        request_sha = canonical_sha256(request)
        planned = tuple(item for item in plan.trials if item.scenario_id == scenario.scenario_id)
        planned_job_ids = {item.job_id for item in planned}
        if len(planned_job_ids) != 1:
            raise ValueError("P5 scenario trial plan does not bind exactly one planned Job")
        jobs.append(
            PhysicalStabilityExecutionJobV1(
                scenario_ordinal=ordinal,
                scenario_id=scenario.scenario_id,
                planned_job_id=next(iter(planned_job_ids)),
                idempotency_key=f"p5-{plan_sha[:16]}-{ordinal:02d}-{request_sha[:16]}",
                request_payload=request.model_dump(mode="json", exclude_none=False),
                request_sha256=request_sha,
                trials=tuple(_binding(item) for item in planned),
            )
        )
    return PhysicalStabilityExecutionBundleV1(
        repository_subject_commit=manifest.repository_subject_commit,
        manifest_sha256=manifest_sha,
        plan_sha256=plan_sha,
        composite_execution_inventory_sha256=inventory_sha,
        job_create_request_schema_sha256=_job_request_schema_sha256(),
        jobs=tuple(jobs),
    )


class PhysicalStabilityJobCreateObservationV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-job-create-observation/v1"] = (
        "dronedream.physical-stability-job-create-observation/v1"
    )
    scenario_id: Identifier
    observed_job_id: Identifier
    idempotency_key: str
    request_sha256: Sha256Hex


class PhysicalStabilityTrialObservationV1(_StrictFrozen):
    planned_trial_id: Identifier
    trial_ordinal: Annotated[int, Field(ge=1, le=60)]
    observed_trial_id: Identifier
    seed: Annotated[int, Field(ge=0, le=2_147_483_647)]
    scenario_type: str
    status: TrialTerminalStatus
    candidate_id: Identifier
    candidate_is_baseline: bool
    input_contract_sha256: Sha256Hex
    scenario_effect_request_sha256: Sha256Hex
    effect_readback_receipt_sha256: Sha256Hex | None = None
    parameter_readback_receipt_sha256: Sha256Hex | None = None
    telemetry_sha256: Sha256Hex | None = None
    metric_evidence_sha256: Sha256Hex | None = None
    artifact_inventory_sha256: Sha256Hex | None = None
    artifact_content_sha256: tuple[Sha256Hex, ...] = ()
    effect_ids_read_back: tuple[Identifier, ...] = ()
    safety_critical_failure: bool = False
    failure_code: Annotated[str, Field(min_length=1, max_length=128)] | None = None

    @model_validator(mode="after")
    def _validate_trial(self) -> PhysicalStabilityTrialObservationV1:
        required = (
            self.effect_readback_receipt_sha256,
            self.parameter_readback_receipt_sha256,
            self.telemetry_sha256,
            self.metric_evidence_sha256,
            self.artifact_inventory_sha256,
        )
        if self.status == "completed":
            if not self.candidate_is_baseline or self.failure_code is not None:
                raise ValueError("completed P5 trial must be the intact baseline candidate")
            if any(value is None for value in required) or not self.artifact_content_sha256:
                raise ValueError("completed P5 trial requires complete content-addressed evidence")
        elif self.failure_code is None:
            raise ValueError("non-completed P5 trial requires a structured failure code")
        return self


class PhysicalStabilityTerminalObservationV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-terminal-observation/v1"] = (
        PHYSICAL_STABILITY_TERMINAL_OBSERVATION_SCHEMA_ID
    )
    repository_subject_commit: GitCommit
    execution_bundle_sha256: Sha256Hex
    scenario_ordinal: Annotated[int, Field(ge=1, le=6)]
    scenario_id: Identifier
    observed_job_id: Identifier
    request_sha256: Sha256Hex
    job_status: JobTerminalStatus
    provider_events_observed: Literal[0] = 0
    trials: tuple[PhysicalStabilityTrialObservationV1, ...]

    @model_validator(mode="after")
    def _validate_observation(self) -> PhysicalStabilityTerminalObservationV1:
        if len(self.trials) != 10:
            raise ValueError("P5 terminal observation must retain all ten planned trials")
        if len({item.observed_trial_id for item in self.trials}) != 10:
            raise ValueError("P5 observed Trial IDs must be unique")
        if self.job_status == "completed" and any(
            item.status != "completed" for item in self.trials
        ):
            raise ValueError("completed P5 Job cannot hide non-completed trials")
        return self


@runtime_checkable
class PhysicalStabilityCheckpointStore(Protocol):
    def persist(
        self,
        ledger: PhysicalStabilityExecutionLedgerV1,
        transition: PhysicalStabilityLedgerTransitionV1,
    ) -> None: ...


@runtime_checkable
class PhysicalStabilityCreateTransport(Protocol):
    def create_job(
        self,
        request: schemas.JobCreateRequest,
        *,
        idempotency_key: str,
        request_sha256: str,
        scenario_id: str,
    ) -> PhysicalStabilityJobCreateObservationV1: ...


def _require_bundle_ledger_alignment(
    bundle: PhysicalStabilityExecutionBundleV1,
    ledger: PhysicalStabilityExecutionLedgerV1,
) -> None:
    if bundle.repository_subject_commit != ledger.repository_subject_commit:
        raise ValueError("P5 execution bundle and ledger subjects differ")
    if bundle.manifest_sha256 != ledger.manifest_sha256:
        raise ValueError("P5 execution bundle and ledger manifests differ")
    if bundle.plan_sha256 != ledger.plan_sha256:
        raise ValueError("P5 execution bundle and ledger plans differ")
    if bundle.composite_execution_inventory_sha256 != ledger.composite_execution_inventory_sha256:
        raise ValueError("P5 execution bundle and ledger inventories differ")


def dispatch_next_physical_stability_job(
    bundle: PhysicalStabilityExecutionBundleV1,
    ledger: PhysicalStabilityExecutionLedgerV1,
    *,
    transport: PhysicalStabilityCreateTransport,
    checkpoint_store: PhysicalStabilityCheckpointStore,
    attempted_at_utc: datetime,
    observed_at_utc: datetime,
) -> tuple[PhysicalStabilityExecutionLedgerV1, tuple[PhysicalStabilityLedgerTransitionV1, ...]]:
    """Persist the trial reservation before exactly one injected create call."""

    _require_bundle_ledger_alignment(bundle, ledger)
    ordinal = ledger.next_scenario_ordinal
    if ordinal is None:
        raise ValueError("P5 execution ledger has no remaining scenario")
    job = bundle.jobs[ordinal - 1]
    after_attempt, attempt_transition = record_physical_stability_dispatch_attempt(
        ledger,
        scenario_ordinal=ordinal,
        attempted_at_utc=attempted_at_utc,
    )
    checkpoint_store.persist(after_attempt, attempt_transition)
    request = schemas.JobCreateRequest.model_validate(job.request_payload)
    observation = transport.create_job(
        request,
        idempotency_key=job.idempotency_key,
        request_sha256=job.request_sha256,
        scenario_id=job.scenario_id,
    )
    if (
        observation.scenario_id != job.scenario_id
        or observation.idempotency_key != job.idempotency_key
        or observation.request_sha256 != job.request_sha256
    ):
        raise ValueError("P5 create observation does not bind the dispatched request")
    after_observed, observed_transition = record_physical_stability_job_observed(
        after_attempt,
        scenario_ordinal=ordinal,
        observed_job_id=observation.observed_job_id,
        observed_at_utc=observed_at_utc,
    )
    checkpoint_store.persist(after_observed, observed_transition)
    return after_observed, (attempt_transition, observed_transition)


def close_physical_stability_job(
    bundle: PhysicalStabilityExecutionBundleV1,
    ledger: PhysicalStabilityExecutionLedgerV1,
    observation: PhysicalStabilityTerminalObservationV1,
    *,
    checkpoint_store: PhysicalStabilityCheckpointStore,
    terminal_at_utc: datetime,
) -> tuple[PhysicalStabilityExecutionLedgerV1, PhysicalStabilityLedgerTransitionV1]:
    """Validate terminal API evidence and close one already observed Job."""

    _require_bundle_ledger_alignment(bundle, ledger)
    if observation.execution_bundle_sha256 != canonical_sha256(bundle):
        raise ValueError("P5 terminal observation does not bind the execution bundle")
    if observation.repository_subject_commit != bundle.repository_subject_commit:
        raise ValueError("P5 terminal observation source differs from the execution bundle")
    job = bundle.jobs[observation.scenario_ordinal - 1]
    request = schemas.JobCreateRequest.model_validate(job.request_payload)
    expected_scenario_type = request.scenario_suite.cases[0].scenario_type
    scenario = ledger.scenarios[observation.scenario_ordinal - 1]
    if scenario.status != "running" or scenario.observed_job_id != observation.observed_job_id:
        raise ValueError("P5 terminal observation does not bind the active Job")
    if (
        observation.scenario_id != job.scenario_id
        or observation.request_sha256 != job.request_sha256
    ):
        raise ValueError("P5 terminal observation does not bind the planned scenario request")
    observed_by_planned = {item.planned_trial_id: item for item in observation.trials}
    if set(observed_by_planned) != {item.planned_trial_id for item in job.trials}:
        raise ValueError("P5 terminal observation does not retain every planned Trial mapping")
    for binding in job.trials:
        trial = observed_by_planned[binding.planned_trial_id]
        if trial.trial_ordinal != binding.trial_ordinal or trial.seed != binding.seed:
            raise ValueError("P5 observed Trial ordinal/seed differs from the plan")
        if trial.input_contract_sha256 != binding.input_contract_sha256:
            raise ValueError("P5 observed Trial input contract differs from the plan")
        if trial.scenario_type != expected_scenario_type:
            raise ValueError("P5 observed Trial scenario type differs from the Job request")
        if trial.candidate_id != "p5-fixed-baseline" or not trial.candidate_is_baseline:
            raise ValueError("P5 observed Trial does not bind the fixed baseline candidate")
        if trial.scenario_effect_request_sha256 != binding.scenario_effect_request_sha256:
            raise ValueError("P5 observed Trial effect request differs from the plan")
        if trial.status == "completed" and not set(binding.expected_effect_ids).issubset(
            trial.effect_ids_read_back
        ):
            raise ValueError("P5 completed Trial is missing an expected effect readback")

    counts = {
        status: sum(item.status == status for item in observation.trials)
        for status in ("completed", "failed", "timeout", "cancelled", "indeterminate")
    }
    terminal_status: JobTerminalStatus = observation.job_status
    failure_code = None if terminal_status == "completed" else f"JOB_{terminal_status.upper()}"
    after, transition = record_physical_stability_terminal_observation(
        ledger,
        scenario_ordinal=observation.scenario_ordinal,
        terminal_status=terminal_status,
        completed_trial_count=counts["completed"],
        failed_trial_count=counts["failed"],
        timeout_trial_count=counts["timeout"],
        cancelled_trial_count=counts["cancelled"],
        indeterminate_trial_count=counts["indeterminate"],
        observation_receipt_sha256=canonical_sha256(observation),
        terminal_at_utc=terminal_at_utc,
        failure_code=failure_code,
    )
    checkpoint_store.persist(after, transition)
    return after, transition


def require_manual_reconciliation_after_unobserved_dispatch(
    ledger: PhysicalStabilityExecutionLedgerV1,
) -> None:
    """Forbid an automatic POST replay after a crash before Job observation."""

    if any(item.status == "dispatch_attempted" for item in ledger.scenarios):
        raise RuntimeError(
            "P5 dispatch was durably attempted but no Job was observed; manual read-only "
            "reconciliation is required and automatic create retry is forbidden"
        )


__all__ = [
    "PHYSICAL_STABILITY_EXECUTION_BUNDLE_SCHEMA_ID",
    "PHYSICAL_STABILITY_TERMINAL_OBSERVATION_SCHEMA_ID",
    "PhysicalStabilityCheckpointStore",
    "PhysicalStabilityCreateTransport",
    "PhysicalStabilityExecutionBundleV1",
    "PhysicalStabilityExecutionJobV1",
    "PhysicalStabilityExecutionTrialBindingV1",
    "PhysicalStabilityJobCreateObservationV1",
    "PhysicalStabilityTerminalObservationV1",
    "PhysicalStabilityTrialObservationV1",
    "build_physical_stability_execution_bundle",
    "close_physical_stability_job",
    "dispatch_next_physical_stability_job",
    "require_manual_reconciliation_after_unobserved_dispatch",
]
