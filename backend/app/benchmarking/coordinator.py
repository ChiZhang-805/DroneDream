"""Fenced, idempotent accounting for benchmark campaigns spanning many Batches."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import models
from app.benchmarking import service
from app.benchmarking.contracts import (
    BenchmarkArmManifestV1,
    BenchmarkBatchBindingRecordV1,
    BenchmarkBatchBindingRequestV1,
    BenchmarkBudgetCapsV1,
    BenchmarkBudgetReservationRecordV1,
    BenchmarkBudgetReservationRequestV1,
    BenchmarkCampaignUsageV1,
    BenchmarkCoordinatorLeaseV1,
    BenchmarkResourceVectorV1,
    BenchmarkRunBindingRecordV1,
    BenchmarkRunBindingRequestV1,
    BenchmarkUsageDeltaV1,
    canonical_json_bytes,
    canonical_sha256,
)
from app.benchmarking.llm_arm_contracts import BENCHMARK_LLM_ARM_POLICIES_SHA256
from app.benchmarking.provider_execution_contract import (
    BENCHMARK_DIRECT_RESERVATION_REASON,
    BENCHMARK_PROVIDER_BASE_URLS,
    BenchmarkProviderExecutionConfigV1,
    direct_provider_run_capacity,
)
from app.orchestration.qualification import (
    SEALED_QUALIFICATION_POLICY_VERSION,
    QualificationContractError,
    compile_sealed_qualification_contract,
    sealed_qualification_contract_sha256,
)
from app.schemas import ScenarioSuiteConfig
from app.services import jobs as job_service


class BenchmarkCoordinatorError(RuntimeError):
    def __init__(self, code: str, message: str, *, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


_RESOURCE_FIELDS = {
    "jobs": ("jobs_used", "job_cap"),
    "trials": ("trials_used", "trial_cap"),
    "logical_turns": ("logical_turns_used", "logical_turn_cap"),
    "network_requests": ("network_requests_used", "network_request_cap"),
    "input_utf8_bytes": ("input_utf8_bytes_used", "input_utf8_byte_cap"),
    "output_utf8_bytes": ("output_utf8_bytes_used", "output_utf8_byte_cap"),
    "provider_tokens": ("provider_tokens_used", "provider_token_cap"),
    "provider_cost_microusd": (
        "provider_cost_microusd_used",
        "provider_cost_microusd_cap",
    ),
    "wall_time_seconds": ("wall_time_seconds_used", "wall_time_second_cap"),
    "disk_bytes": ("disk_bytes_used", "disk_byte_cap"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    if not 32 <= len(token) <= 256:
        raise BenchmarkCoordinatorError(
            "BENCHMARK_COORDINATOR_TOKEN_INVALID",
            "Benchmark coordinator lease token is malformed.",
            http_status=409,
        )
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _batch_binding_request_sha256(request: BenchmarkBatchBindingRequestV1) -> str:
    payload = request.model_dump(mode="json", exclude_none=False)
    payload["runs"] = sorted(payload["runs"], key=lambda item: item["run_key"])
    return canonical_sha256(payload)


def _direct_provider_capacity(
    arm: models.BenchmarkArm,
    run: BenchmarkRunBindingRequestV1,
    job: models.Job,
) -> BenchmarkUsageDeltaV1 | None:
    if arm.proposal_adapter_id != "llm_direct/v1":
        return None
    try:
        arm_manifest = BenchmarkArmManifestV1.model_validate(arm.manifest_json)
        provider_execution = arm_manifest.intervention.get("provider_execution")
        if not isinstance(provider_execution, dict):
            raise ValueError("provider_execution must be a JSON object")
        provider = BenchmarkProviderExecutionConfigV1.model_validate_json(
            canonical_json_bytes(provider_execution)
        )
    except ValueError as exc:
        raise BenchmarkCoordinatorError(
            "BENCHMARK_PROVIDER_CONTRACT_INVALID",
            "The direct-arm provider execution contract is invalid.",
            http_status=422,
        ) from exc
    if canonical_sha256(arm_manifest) != arm.manifest_sha256:
        raise BenchmarkCoordinatorError(
            "BENCHMARK_ARM_MANIFEST_DRIFT",
            "The direct-arm manifest hash no longer matches.",
            http_status=409,
        )
    if (
        not arm.execution_enabled
        or arm.arm_family != "llm_harness"
        or not arm_manifest.execution_enabled
        or arm_manifest.arm_family != "llm_harness"
        or arm_manifest.proposal_adapter_id != "llm_direct/v1"
        or arm_manifest.provider_contract_sha256
        != BENCHMARK_LLM_ARM_POLICIES_SHA256
    ):
        raise BenchmarkCoordinatorError(
            "BENCHMARK_DIRECT_CONTRACT_MISMATCH",
            "The arm is not the reviewed executable direct-provider contract.",
            http_status=422,
        )
    if (
        run.provider_randomness_policy != provider.randomness_policy
        or (provider.randomness_policy == "fixed_seed") != (run.provider_seed is not None)
    ):
        raise BenchmarkCoordinatorError(
            "BENCHMARK_PROVIDER_RANDOMNESS_MISMATCH",
            "Run randomness differs from the direct-arm provider contract.",
            http_status=422,
        )
    job_base_url = job.llm_base_url
    if job_base_url is None and job.llm_provider == "openai":
        job_base_url = BENCHMARK_PROVIDER_BASE_URLS["openai"]
    if (
        job.llm_access_mode != "byok"
        or job.llm_provider != provider.provider
        or job_base_url != provider.base_url
        or job.openai_model != provider.model_snapshot
        or job.provider_max_retries != 0
        or job.provider_turn_cap != provider.maximum_generations
        or job.provider_request_cap != provider.maximum_generations
        or job.max_iterations != provider.maximum_generations
    ):
        raise BenchmarkCoordinatorError(
            "BENCHMARK_PROVIDER_JOB_MISMATCH",
            "Job provider identity or hard caps differ from the direct-arm contract.",
            http_status=422,
        )
    return direct_provider_run_capacity(provider)


def _sealed_job_contract(
    job: models.Job,
) -> tuple[dict[str, Any], str, str]:
    raw_suite = job.scenario_suite_json
    if not isinstance(raw_suite, dict):
        raise BenchmarkCoordinatorError(
            "BENCHMARK_SCENARIO_CONTRACT_MISSING",
            "Every benchmark Job must persist an explicit scenario suite.",
            http_status=422,
        )
    try:
        suite = ScenarioSuiteConfig(**raw_suite)
        contract = compile_sealed_qualification_contract(suite)
    except (TypeError, ValueError, QualificationContractError) as exc:
        raise BenchmarkCoordinatorError(
            "BENCHMARK_QUALIFICATION_CONTRACT_INVALID",
            (
                "Every benchmark Job must preregister exactly four screening "
                "runs and twenty disjoint sealed qualification runs."
            ),
            http_status=422,
        ) from exc
    normalized_suite = suite.model_dump(mode="json")
    contract_payload = contract.model_dump(mode="json")
    scenario_suite_sha256 = canonical_sha256(normalized_suite)
    contract_sha256 = sealed_qualification_contract_sha256(contract)
    if job.holdout_policy_version not in {
        "legacy-visible-v0",
        SEALED_QUALIFICATION_POLICY_VERSION,
    }:
        raise BenchmarkCoordinatorError(
            "BENCHMARK_HOLDOUT_POLICY_CONFLICT",
            "Benchmark Job already carries an incompatible holdout policy.",
            http_status=409,
        )
    if (
        job.holdout_policy_version == SEALED_QUALIFICATION_POLICY_VERSION
        and job.holdout_contract_json != contract_payload
    ):
        raise BenchmarkCoordinatorError(
            "BENCHMARK_HOLDOUT_CONTRACT_CONFLICT",
            "Benchmark Job's existing sealed holdout contract has drifted.",
            http_status=409,
        )
    return contract_payload, scenario_suite_sha256, contract_sha256


def run_binding_sha256(
    run: BenchmarkRunBindingRequestV1,
    *,
    scenario_suite_sha256: str,
    qualification_contract_sha256: str,
) -> str:
    return canonical_sha256(
        {
            "schema_id": "dronedream.benchmark-run-execution-binding/v1",
            "run": run.model_dump(mode="json", exclude_none=False),
            "qualification_policy_version": SEALED_QUALIFICATION_POLICY_VERSION,
            "scenario_suite_sha256": scenario_suite_sha256,
            "qualification_contract_sha256": qualification_contract_sha256,
        }
    )


def _campaign(
    db: Session,
    campaign_id: str,
    *,
    user: models.User,
) -> models.BenchmarkCampaign:
    try:
        return service.get_campaign(db, campaign_id, user=user)
    except service.BenchmarkCampaignError as error:
        raise BenchmarkCoordinatorError(
            error.code,
            error.message,
            http_status=error.http_status,
        ) from error


def _coordinator_state(
    db: Session,
    campaign: models.BenchmarkCampaign,
) -> models.BenchmarkCampaignCoordinatorState:
    state = db.get(models.BenchmarkCampaignCoordinatorState, campaign.id)
    if state is None:
        raise BenchmarkCoordinatorError(
            "BENCHMARK_COORDINATOR_STATE_MISSING",
            "Campaign coordinator state is missing; run the current database migration.",
            http_status=500,
        )
    return state


def claim_lease(
    db: Session,
    campaign_id: str,
    *,
    user: models.User,
    owner_id: str,
    lease_seconds: int,
) -> BenchmarkCoordinatorLeaseV1:
    campaign = _campaign(db, campaign_id, user=user)
    if campaign.status in {"COMPLETED", "FAILED", "CANCELLED"}:
        raise BenchmarkCoordinatorError(
            "BENCHMARK_CAMPAIGN_TERMINAL",
            "A terminal benchmark campaign cannot acquire a coordinator lease.",
            http_status=409,
        )
    state = _coordinator_state(db, campaign)
    now = _now()
    expires_at = now + timedelta(seconds=lease_seconds)
    raw_token = secrets.token_urlsafe(32)
    token_hash = _token_hash(raw_token)
    statement = (
        update(models.BenchmarkCampaignCoordinatorState)
        .where(
            models.BenchmarkCampaignCoordinatorState.campaign_id == campaign.id,
            or_(
                models.BenchmarkCampaignCoordinatorState.lease_token_hash.is_(None),
                models.BenchmarkCampaignCoordinatorState.lease_expires_at.is_(None),
                models.BenchmarkCampaignCoordinatorState.lease_expires_at <= now,
            ),
        )
        .values(
            lease_owner=owner_id,
            lease_token_hash=token_hash,
            lease_generation=(
                models.BenchmarkCampaignCoordinatorState.lease_generation + 1
            ),
            lease_expires_at=expires_at,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    result = db.execute(statement)
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise BenchmarkCoordinatorError(
            "BENCHMARK_COORDINATOR_LEASE_HELD",
            "Another coordinator holds the unexpired campaign lease.",
            http_status=409,
        )
    db.flush()
    db.refresh(state)
    return BenchmarkCoordinatorLeaseV1(
        campaign_id=campaign.id,
        owner_id=owner_id,
        lease_token=raw_token,
        lease_generation=state.lease_generation,
        lease_expires_at=expires_at,
    )


def renew_lease(
    db: Session,
    campaign_id: str,
    *,
    user: models.User,
    lease_token: str,
    lease_generation: int,
    lease_seconds: int,
) -> BenchmarkCoordinatorLeaseV1:
    campaign = _campaign(db, campaign_id, user=user)
    state = _coordinator_state(db, campaign)
    now = _now()
    expires_at = now + timedelta(seconds=lease_seconds)
    token_hash = _token_hash(lease_token)
    statement = (
        update(models.BenchmarkCampaignCoordinatorState)
        .where(
            models.BenchmarkCampaignCoordinatorState.campaign_id == campaign.id,
            models.BenchmarkCampaignCoordinatorState.lease_token_hash == token_hash,
            models.BenchmarkCampaignCoordinatorState.lease_generation == lease_generation,
            models.BenchmarkCampaignCoordinatorState.lease_expires_at > now,
        )
        .values(lease_expires_at=expires_at, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    result = db.execute(statement)
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise BenchmarkCoordinatorError(
            "BENCHMARK_COORDINATOR_FENCE_REJECTED",
            "Coordinator lease is expired, stale, or does not match this campaign.",
            http_status=409,
        )
    db.flush()
    db.refresh(state)
    return BenchmarkCoordinatorLeaseV1(
        campaign_id=campaign.id,
        owner_id=state.lease_owner or "unknown",
        lease_token=lease_token,
        lease_generation=lease_generation,
        lease_expires_at=expires_at,
    )


def release_lease(
    db: Session,
    campaign_id: str,
    *,
    user: models.User,
    lease_token: str,
    lease_generation: int,
) -> BenchmarkCampaignUsageV1:
    campaign = _campaign(db, campaign_id, user=user)
    state = _coordinator_state(db, campaign)
    now = _now()
    statement = (
        update(models.BenchmarkCampaignCoordinatorState)
        .where(
            models.BenchmarkCampaignCoordinatorState.campaign_id == campaign.id,
            models.BenchmarkCampaignCoordinatorState.lease_token_hash
            == _token_hash(lease_token),
            models.BenchmarkCampaignCoordinatorState.lease_generation == lease_generation,
        )
        .values(
            lease_owner=None,
            lease_token_hash=None,
            lease_expires_at=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    result = db.execute(statement)
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise BenchmarkCoordinatorError(
            "BENCHMARK_COORDINATOR_FENCE_REJECTED",
            "Coordinator lease is stale or does not match this campaign.",
            http_status=409,
        )
    db.flush()
    db.refresh(state)
    return to_usage(campaign, state)


def reserve_budget(
    db: Session,
    campaign_id: str,
    request: BenchmarkBudgetReservationRequestV1,
    *,
    user: models.User,
    lease_token: str,
) -> BenchmarkBudgetReservationRecordV1:
    campaign = _campaign(db, campaign_id, user=user)
    campaign_id_value = campaign.id
    request_payload = request.model_dump(mode="json", exclude_none=False)
    request_sha256 = canonical_sha256(request_payload)
    existing = db.scalar(
        select(models.BenchmarkBudgetReservation).where(
            models.BenchmarkBudgetReservation.campaign_id == campaign_id_value,
            models.BenchmarkBudgetReservation.reservation_key == request.reservation_key,
        )
    )
    if existing is not None:
        if existing.reservation_sha256 == request_sha256:
            return to_reservation_record(existing)
        raise BenchmarkCoordinatorError(
            "BENCHMARK_RESERVATION_KEY_CONFLICT",
            "reservation_key is already bound to a different immutable usage delta.",
            http_status=409,
        )
    if campaign.status != "ACTIVE":
        raise BenchmarkCoordinatorError(
            "BENCHMARK_CAMPAIGN_NOT_ACTIVE",
            "Budget can only be consumed by an ACTIVE benchmark campaign.",
            http_status=409,
        )

    state = _coordinator_state(db, campaign)
    now = _now()
    token_hash = _token_hash(lease_token)
    usage = request.usage.model_dump()
    conditions: list[Any] = [
        models.BenchmarkCampaignCoordinatorState.campaign_id == campaign.id,
        models.BenchmarkCampaignCoordinatorState.lease_token_hash == token_hash,
        models.BenchmarkCampaignCoordinatorState.lease_generation
        == request.lease_generation,
        models.BenchmarkCampaignCoordinatorState.lease_expires_at > now,
    ]
    values: dict[str, Any] = {"updated_at": now}
    for resource, (used_field, cap_field) in _RESOURCE_FIELDS.items():
        delta = int(usage[resource])
        used_column = getattr(models.BenchmarkCampaignCoordinatorState, used_field)
        cap = int(getattr(campaign, cap_field))
        conditions.append(used_column + delta <= cap)
        values[used_field] = used_column + delta
    statement = (
        update(models.BenchmarkCampaignCoordinatorState)
        .where(and_(*conditions))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    result = db.execute(statement)
    if result.rowcount != 1:  # type: ignore[attr-defined]
        db.refresh(state)
        lease_is_current = (
            state.lease_token_hash == token_hash
            and state.lease_generation == request.lease_generation
            and state.lease_expires_at is not None
            and _as_utc(state.lease_expires_at) > now
        )
        if not lease_is_current:
            raise BenchmarkCoordinatorError(
                "BENCHMARK_COORDINATOR_FENCE_REJECTED",
                "Coordinator lease is expired, stale, or does not match this campaign.",
                http_status=409,
            )
        raise BenchmarkCoordinatorError(
            "BENCHMARK_CAMPAIGN_CAP_EXCEEDED",
            "The requested work would exceed one or more frozen campaign caps.",
            http_status=409,
        )

    reservation = models.BenchmarkBudgetReservation(
        campaign_id=campaign_id_value,
        reservation_key=request.reservation_key,
        lease_generation=request.lease_generation,
        reason=request.reason,
        reservation_sha256=request_sha256,
        **usage,
    )
    db.add(reservation)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        replay = db.scalar(
            select(models.BenchmarkBudgetReservation).where(
                models.BenchmarkBudgetReservation.campaign_id == campaign_id_value,
                models.BenchmarkBudgetReservation.reservation_key
                == request.reservation_key,
            )
        )
        if replay is not None and replay.reservation_sha256 == request_sha256:
            return to_reservation_record(replay)
        raise BenchmarkCoordinatorError(
            "BENCHMARK_RESERVATION_KEY_CONFLICT",
            "Concurrent reservation used the same key with a different payload.",
            http_status=409,
        ) from None
    return to_reservation_record(reservation)


def bind_batch(
    db: Session,
    campaign_id: str,
    request: BenchmarkBatchBindingRequestV1,
    *,
    user: models.User,
    lease_token: str,
) -> BenchmarkBatchBindingRecordV1:
    campaign = _campaign(db, campaign_id, user=user)
    request_sha256 = _batch_binding_request_sha256(request)
    existing = db.scalar(
        select(models.BenchmarkCampaignBatchBinding)
        .options(
            selectinload(models.BenchmarkCampaignBatchBinding.runs).selectinload(
                models.BenchmarkCampaignRunBinding.arm
            )
        )
        .where(
            models.BenchmarkCampaignBatchBinding.campaign_id == campaign.id,
            models.BenchmarkCampaignBatchBinding.binding_key == request.binding_key,
        )
    )
    if existing is not None:
        if existing.binding_sha256 == request_sha256:
            return to_batch_binding_record(existing)
        raise BenchmarkCoordinatorError(
            "BENCHMARK_BATCH_BINDING_KEY_CONFLICT",
            "binding_key is already bound to a different immutable Batch request.",
            http_status=409,
        )

    other_batch_binding = db.scalar(
        select(models.BenchmarkCampaignBatchBinding).where(
            models.BenchmarkCampaignBatchBinding.batch_id == request.batch_id
        )
    )
    if other_batch_binding is not None:
        raise BenchmarkCoordinatorError(
            "BENCHMARK_BATCH_ALREADY_BOUND",
            "A Batch can belong to only one immutable benchmark campaign binding.",
            http_status=409,
        )

    try:
        batch = job_service.get_batch(db, request.batch_id, user=user)
    except job_service.JobServiceError as error:
        raise BenchmarkCoordinatorError(
            error.code,
            error.message,
            http_status=error.http_status,
        ) from error
    # Lock every Job row before freezing execution semantics. PostgreSQL then
    # serializes a competing Batch start or binding attempt; SQLite keeps the
    # same validation path for local/test use.
    children = list(
        db.scalars(
            select(models.Job)
            .where(models.Job.batch_id == batch.id)
            .order_by(models.Job.created_at, models.Job.id)
            .with_for_update()
        )
    )
    child_by_id = {job.id: job for job in children}
    requested_job_ids = {run.job_id for run in request.runs}
    if requested_job_ids != set(child_by_id):
        raise BenchmarkCoordinatorError(
            "BENCHMARK_BATCH_JOB_SET_MISMATCH",
            "A benchmark Batch binding must cover every child Job exactly once.",
            http_status=422,
        )
    if batch.status != "QUEUED" or any(
        job.status != "QUEUED"
        or job.current_generation != 0
        or job.progress_completed_trials != 0
        or bool(job.candidates)
        or bool(job.trials)
        for job in children
    ):
        raise BenchmarkCoordinatorError(
            "BENCHMARK_BATCH_ALREADY_STARTED",
            "Only an untouched QUEUED Batch can be bound to a benchmark campaign.",
            http_status=409,
        )

    arm_by_semantic_id = {
        (arm.benchmark_arm_id, arm.arm_version): arm for arm in campaign.arms
    }
    for run in request.runs:
        arm = arm_by_semantic_id.get((run.benchmark_arm_id, run.arm_version))
        if arm is None:
            raise BenchmarkCoordinatorError(
                "BENCHMARK_RUN_ARM_NOT_IN_CAMPAIGN",
                "Every run must reference an arm and version frozen in this campaign.",
                http_status=422,
            )
        if not arm.execution_enabled:
            raise BenchmarkCoordinatorError(
                "BENCHMARK_RUN_ARM_EXECUTION_DISABLED",
                (
                    "A Job cannot be bound to a preregistered arm whose immutable "
                    "manifest keeps execution_enabled=false. Promote and version the "
                    "reviewed adapter before creating executable run bindings."
                ),
                http_status=422,
            )

    sealed_by_job: dict[str, tuple[dict[str, Any], str, str]] = {}
    scenario_by_seed_block: dict[str, str] = {}
    for run in request.runs:
        job = child_by_id[run.job_id]
        sealed = _sealed_job_contract(job)
        sealed_by_job[job.id] = sealed
        scenario_sha256 = sealed[1]
        existing_scenario_sha256 = scenario_by_seed_block.setdefault(
            run.simulator_seed_block,
            scenario_sha256,
        )
        if existing_scenario_sha256 != scenario_sha256:
            raise BenchmarkCoordinatorError(
                "BENCHMARK_PAIRED_SCENARIO_MISMATCH",
                (
                    "Every arm in one simulator_seed_block must use the exact "
                    "same scenario suite and sealed holdout contract."
                ),
                http_status=422,
            )

    # The Batch is still untouched and locked. Promote all of its Jobs in the
    # same transaction that creates the immutable run bindings, so no runner
    # can observe a half-bound visible-holdout Job.
    for job in children:
        contract_payload, _, _ = sealed_by_job[job.id]
        job.holdout_policy_version = SEALED_QUALIFICATION_POLICY_VERSION
        job.holdout_contract_json = contract_payload

    reservation = reserve_budget(
        db,
        campaign_id,
        BenchmarkBudgetReservationRequestV1(
            reservation_key=f"batch-bind/{request.binding_key}",
            lease_generation=request.lease_generation,
            reason="benchmark-batch-binding",
            usage=BenchmarkUsageDeltaV1(jobs=len(children)),
        ),
        user=user,
        lease_token=lease_token,
    )
    state = _coordinator_state(db, campaign)
    db.refresh(state)
    now = _now()
    token_hash = _token_hash(lease_token)
    batch_ordinal = state.next_batch_ordinal
    first_run_ordinal = state.next_run_ordinal
    allocate = (
        update(models.BenchmarkCampaignCoordinatorState)
        .where(
            models.BenchmarkCampaignCoordinatorState.campaign_id == campaign.id,
            models.BenchmarkCampaignCoordinatorState.lease_token_hash == token_hash,
            models.BenchmarkCampaignCoordinatorState.lease_generation
            == request.lease_generation,
            models.BenchmarkCampaignCoordinatorState.lease_expires_at > now,
            models.BenchmarkCampaignCoordinatorState.next_batch_ordinal
            == batch_ordinal,
            models.BenchmarkCampaignCoordinatorState.next_run_ordinal
            == first_run_ordinal,
        )
        .values(
            next_batch_ordinal=batch_ordinal + 1,
            next_run_ordinal=first_run_ordinal + len(children),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    allocation_result = db.execute(allocate)
    if allocation_result.rowcount != 1:  # type: ignore[attr-defined]
        raise BenchmarkCoordinatorError(
            "BENCHMARK_COORDINATOR_FENCE_REJECTED",
            "Coordinator lease or ordinal allocation changed during Batch binding.",
            http_status=409,
        )

    batch_binding = models.BenchmarkCampaignBatchBinding(
        campaign_id=campaign.id,
        batch_id=batch.id,
        binding_key=request.binding_key,
        binding_sha256=request_sha256,
        batch_ordinal=batch_ordinal,
        lease_generation=request.lease_generation,
        job_count=len(children),
        budget_reservation_id=reservation.id,
    )
    db.add(batch_binding)
    db.flush()
    sorted_runs = sorted(request.runs, key=lambda item: item.run_key)
    persisted_runs: list[
        tuple[
            models.BenchmarkCampaignRunBinding,
            models.BenchmarkArm,
            BenchmarkRunBindingRequestV1,
        ]
    ] = []
    for offset, run in enumerate(sorted_runs):
        arm = arm_by_semantic_id[(run.benchmark_arm_id, run.arm_version)]
        _, scenario_sha256, qualification_sha256 = sealed_by_job[run.job_id]
        persisted_run = models.BenchmarkCampaignRunBinding(
            campaign_id=campaign.id,
            batch_binding_id=batch_binding.id,
            benchmark_arm_id=arm.id,
            job_id=run.job_id,
            run_key=run.run_key,
            run_ordinal=first_run_ordinal + offset,
            batch_run_ordinal=offset + 1,
            algorithm_seed=run.algorithm_seed,
            simulator_seed_block=run.simulator_seed_block,
            provider_randomness_policy=run.provider_randomness_policy,
            provider_seed=run.provider_seed,
            qualification_policy_version=SEALED_QUALIFICATION_POLICY_VERSION,
            scenario_suite_sha256=scenario_sha256,
            qualification_contract_sha256=qualification_sha256,
            binding_sha256=run_binding_sha256(
                run,
                scenario_suite_sha256=scenario_sha256,
                qualification_contract_sha256=qualification_sha256,
            ),
        )
        db.add(persisted_run)
        persisted_runs.append((persisted_run, arm, run))
    db.flush()
    for persisted_run, arm, run in persisted_runs:
        provider_capacity = _direct_provider_capacity(
            arm,
            run,
            child_by_id[run.job_id],
        )
        if provider_capacity is None:
            continue
        reserve_budget(
            db,
            campaign_id,
            BenchmarkBudgetReservationRequestV1(
                reservation_key=f"provider-run/{persisted_run.id}",
                lease_generation=request.lease_generation,
                reason=BENCHMARK_DIRECT_RESERVATION_REASON,
                usage=provider_capacity,
            ),
            user=user,
            lease_token=lease_token,
        )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        replay = db.scalar(
            select(models.BenchmarkCampaignBatchBinding)
            .options(
                selectinload(models.BenchmarkCampaignBatchBinding.runs).selectinload(
                    models.BenchmarkCampaignRunBinding.arm
                )
            )
            .where(
                models.BenchmarkCampaignBatchBinding.campaign_id == campaign_id,
                models.BenchmarkCampaignBatchBinding.binding_key == request.binding_key,
            )
        )
        if replay is not None and replay.binding_sha256 == request_sha256:
            return to_batch_binding_record(replay)
        raise BenchmarkCoordinatorError(
            "BENCHMARK_BATCH_BINDING_CONFLICT",
            "Concurrent Batch binding collided with immutable campaign provenance.",
            http_status=409,
        ) from None
    db.refresh(batch_binding, attribute_names=["runs"])
    return to_batch_binding_record(batch_binding)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_usage(
    db: Session,
    campaign_id: str,
    *,
    user: models.User,
) -> BenchmarkCampaignUsageV1:
    campaign = _campaign(db, campaign_id, user=user)
    return to_usage(campaign, _coordinator_state(db, campaign))


def list_batch_bindings(
    db: Session,
    campaign_id: str,
    *,
    user: models.User,
) -> list[BenchmarkBatchBindingRecordV1]:
    campaign = _campaign(db, campaign_id, user=user)
    bindings = list(
        db.scalars(
            select(models.BenchmarkCampaignBatchBinding)
            .options(
                selectinload(models.BenchmarkCampaignBatchBinding.runs).selectinload(
                    models.BenchmarkCampaignRunBinding.arm
                )
            )
            .where(models.BenchmarkCampaignBatchBinding.campaign_id == campaign.id)
            .order_by(models.BenchmarkCampaignBatchBinding.batch_ordinal)
        )
    )
    return [to_batch_binding_record(binding) for binding in bindings]


def _resource_vector(
    campaign: models.BenchmarkCampaign,
    state: models.BenchmarkCampaignCoordinatorState,
) -> tuple[BenchmarkResourceVectorV1, BenchmarkResourceVectorV1]:
    used_payload: dict[str, int] = {}
    remaining_payload: dict[str, int] = {}
    for resource, (used_field, cap_field) in _RESOURCE_FIELDS.items():
        used_value = int(getattr(state, used_field))
        cap_value = int(getattr(campaign, cap_field))
        used_payload[resource] = used_value
        remaining_payload[resource] = max(0, cap_value - used_value)
    return (
        BenchmarkResourceVectorV1(**used_payload),
        BenchmarkResourceVectorV1(**remaining_payload),
    )


def to_usage(
    campaign: models.BenchmarkCampaign,
    state: models.BenchmarkCampaignCoordinatorState,
) -> BenchmarkCampaignUsageV1:
    used, remaining = _resource_vector(campaign, state)
    caps = BenchmarkBudgetCapsV1(
        jobs=campaign.job_cap,
        trials=campaign.trial_cap,
        logical_turns=campaign.logical_turn_cap,
        network_requests=campaign.network_request_cap,
        input_utf8_bytes=campaign.input_utf8_byte_cap,
        output_utf8_bytes=campaign.output_utf8_byte_cap,
        provider_tokens=campaign.provider_token_cap,
        provider_cost_microusd=campaign.provider_cost_microusd_cap,
        wall_time_seconds=campaign.wall_time_second_cap,
        disk_bytes=campaign.disk_byte_cap,
    )
    return BenchmarkCampaignUsageV1(
        campaign_id=campaign.id,
        status=campaign.status,  # type: ignore[arg-type]
        caps=caps,
        used=used,
        remaining=remaining,
        lease_owner=state.lease_owner,
        lease_generation=state.lease_generation,
        lease_expires_at=state.lease_expires_at,
    )


def to_reservation_record(
    reservation: models.BenchmarkBudgetReservation,
) -> BenchmarkBudgetReservationRecordV1:
    return BenchmarkBudgetReservationRecordV1(
        id=reservation.id,
        campaign_id=reservation.campaign_id,
        reservation_key=reservation.reservation_key,
        lease_generation=reservation.lease_generation,
        reason=reservation.reason,
        reservation_sha256=reservation.reservation_sha256,
        usage=BenchmarkUsageDeltaV1(
            jobs=reservation.jobs,
            trials=reservation.trials,
            logical_turns=reservation.logical_turns,
            network_requests=reservation.network_requests,
            input_utf8_bytes=reservation.input_utf8_bytes,
            output_utf8_bytes=reservation.output_utf8_bytes,
            provider_tokens=reservation.provider_tokens,
            provider_cost_microusd=reservation.provider_cost_microusd,
            wall_time_seconds=reservation.wall_time_seconds,
            disk_bytes=reservation.disk_bytes,
        ),
        created_at=reservation.created_at,
    )


def to_batch_binding_record(
    binding: models.BenchmarkCampaignBatchBinding,
) -> BenchmarkBatchBindingRecordV1:
    runs = sorted(binding.runs, key=lambda item: item.batch_run_ordinal)
    return BenchmarkBatchBindingRecordV1(
        id=binding.id,
        campaign_id=binding.campaign_id,
        binding_key=binding.binding_key,
        batch_id=binding.batch_id,
        batch_ordinal=binding.batch_ordinal,
        lease_generation=binding.lease_generation,
        job_count=binding.job_count,
        binding_sha256=binding.binding_sha256,
        budget_reservation_id=binding.budget_reservation_id,
        runs=[
            BenchmarkRunBindingRecordV1(
                id=run.id,
                run_key=run.run_key,
                job_id=run.job_id,
                benchmark_arm_id=run.arm.benchmark_arm_id,
                arm_version=run.arm.arm_version,
                run_ordinal=run.run_ordinal,
                batch_run_ordinal=run.batch_run_ordinal,
                algorithm_seed=run.algorithm_seed,
                simulator_seed_block=run.simulator_seed_block,
                provider_randomness_policy=run.provider_randomness_policy,  # type: ignore[arg-type]
                provider_seed=run.provider_seed,
                qualification_policy_version=run.qualification_policy_version,
                scenario_suite_sha256=run.scenario_suite_sha256,
                qualification_contract_sha256=run.qualification_contract_sha256,
                binding_sha256=run.binding_sha256,
                created_at=_as_utc(run.created_at),
            )
            for run in runs
        ],
        created_at=_as_utc(binding.created_at),
    )


__all__ = [
    "BenchmarkCoordinatorError",
    "bind_batch",
    "claim_lease",
    "get_usage",
    "list_batch_bindings",
    "release_lease",
    "renew_lease",
    "reserve_budget",
    "run_binding_sha256",
    "to_reservation_record",
    "to_batch_binding_record",
    "to_usage",
]
