"""Server-authoritative runtime seam for benchmark-bound Jobs.

The ordinary ``Job.optimizer_strategy`` remains a product compatibility field.
Once a Job is bound to a benchmark campaign, however, only the immutable run
binding and its versioned arm may choose the proposal adapter.  This module
also builds the one observation projection shared by every executable arm;
sealed qualification outcomes never enter that projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Literal, NoReturn

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.benchmarking.contracts import (
    BENCHMARK_OBSERVATION_CONTRACT_SHA256,
    BenchmarkArmManifestV1,
    BenchmarkCampaignManifestV1,
    BenchmarkHistoryItemV2,
    BenchmarkObservationV2,
    BenchmarkOptimizerOutcomeV1,
    BenchmarkProposalContextV1,
    BenchmarkRunBindingRequestV1,
    CompositeExecutionInventoryV1,
    canonical_sha256,
)
from app.benchmarking.coordinator import run_binding_sha256
from app.benchmarking.registry import require_registered_adapter
from app.orchestration.experimental_optimizer import (
    observations_for_job,
    search_space_for_job,
)
from app.orchestration.qualification import (
    QUALIFICATION_RULE_SHA256,
    compile_sealed_qualification_contract,
    sealed_qualification_contract_sha256,
)
from app.orchestration.qualification_dispatch import (
    screening_runs,
    sealed_contract_for_job,
)

BENCHMARK_HISTORY_POLICY_V1 = MappingProxyType(
    {
        "schema_id": "dronedream.benchmark-history-policy/v1",
        "learning_roles": ["objective", "constraint_only"],
        "pending_role": "pending_reservation",
        "quarantined_roles_excluded": True,
        "sealed_holdout_visible": False,
        "dispatch_order": "server-dispatch-ordinal",
    }
)
BENCHMARK_FAILURE_SEMANTICS_V1 = MappingProxyType(
    {
        "schema_id": "dronedream.benchmark-failure-semantics/v1",
        "completed_valid_evidence": "objective",
        "trusted_domain_failure": "constraint_only-no-fabricated-loss",
        "pending": "reservation-only",
        "infrastructure_failure": "quarantined-competing-terminal-event",
        "cancelled": "quarantined-attempted-work",
        "invalid_or_unknown_evidence": "quarantined-fail-closed",
        "sealed_holdout_visible": False,
    }
)
BENCHMARK_HISTORY_CONTRACT_SHA256 = canonical_sha256(dict(BENCHMARK_HISTORY_POLICY_V1))
BENCHMARK_FAILURE_SEMANTICS_SHA256 = canonical_sha256(dict(BENCHMARK_FAILURE_SEMANTICS_V1))


class BenchmarkJobRuntimeBlocked(RuntimeError):
    """A benchmark Job cannot execute without changing its frozen contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _blocked(code: str, message: str) -> NoReturn:
    raise BenchmarkJobRuntimeBlocked(code, message)


@dataclass(frozen=True, slots=True)
class BenchmarkJobRuntimeContext:
    binding: models.BenchmarkCampaignRunBinding
    arm: models.BenchmarkArm
    campaign: models.BenchmarkCampaign
    campaign_manifest: BenchmarkCampaignManifestV1
    arm_manifest: BenchmarkArmManifestV1
    inventory: CompositeExecutionInventoryV1


def benchmark_run_binding(
    db: Session,
    job: models.Job,
) -> models.BenchmarkCampaignRunBinding | None:
    return db.scalar(
        select(models.BenchmarkCampaignRunBinding).where(
            models.BenchmarkCampaignRunBinding.job_id == job.id
        )
    )


def _normalized_runtime_contracts(
    job: models.Job,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    baseline = job.baseline_parameter_json if isinstance(job.baseline_parameter_json, dict) else {}
    space = search_space_for_job(job, baseline_parameters=baseline)
    parameter_domain = [
        {
            "name": item.name,
            "baseline": item.baseline,
            "minimum": item.minimum,
            "maximum": item.maximum,
            "step": item.step,
            "scale": item.scale,
            "value_type": item.value_type,
            "choices": list(item.choices),
            "enabled": item.enabled,
            "locked": item.locked,
        }
        for item in space.domains
    ]
    objective_config = schemas.ObjectiveConfig.model_validate(job.objective_config_json or {})
    objectives = [
        {
            "name": item.metric,
            "direction": item.direction,
            "weight": item.weight,
            "normalization": item.normalization,
            "target": item.target,
        }
        for item in objective_config.objectives
    ]
    constraints = [
        {
            "name": item.metric,
            "operator": item.operator,
            "threshold": item.threshold,
            "hard": item.hard,
            "penalty": item.penalty,
        }
        for item in objective_config.constraints
    ]
    return parameter_domain, objectives, constraints


def _simulator_budget_contract(job: models.Job, *, screening_trial_count: int) -> dict[str, Any]:
    return {
        "schema_id": "dronedream.benchmark-simulator-budget/v1",
        "unit": "candidate-proposals",
        "maximum_generations": job.max_iterations,
        "maximum_total_trials": job.max_total_trials,
        "screening_trials_per_candidate": screening_trial_count,
        "qualification_trials_count_toward_cap": True,
    }


def runtime_fairness_hashes(job: models.Job) -> dict[str, str]:
    """Return the exact Job-side hashes a preregistration must freeze."""

    contract = sealed_contract_for_job(job)
    if contract is None:
        if not isinstance(job.scenario_suite_json, dict):
            _blocked(
                "benchmark_qualification_not_preregistered",
                "Benchmark Jobs require an explicit qualification scenario suite.",
            )
        try:
            suite = schemas.ScenarioSuiteConfig.model_validate(job.scenario_suite_json)
            contract = compile_sealed_qualification_contract(suite)
        except ValueError as exc:
            raise BenchmarkJobRuntimeBlocked(
                "benchmark_qualification_not_preregistered",
                "Benchmark qualification scenario suite is invalid.",
            ) from exc
    parameter_domain, objectives, constraints = _normalized_runtime_contracts(job)
    budget = _simulator_budget_contract(
        job,
        screening_trial_count=len(screening_runs(contract)),
    )
    return {
        "parameter_domain_sha256": canonical_sha256(parameter_domain),
        "objective_contract_sha256": canonical_sha256(objectives),
        "constraint_contract_sha256": canonical_sha256(constraints),
        "history_contract_sha256": BENCHMARK_HISTORY_CONTRACT_SHA256,
        "failure_semantics_sha256": BENCHMARK_FAILURE_SEMANTICS_SHA256,
        "simulator_budget_sha256": canonical_sha256(budget),
    }


def require_benchmark_job_runtime_context(
    db: Session,
    job: models.Job,
) -> BenchmarkJobRuntimeContext:
    binding = benchmark_run_binding(db, job)
    if binding is None:
        _blocked("benchmark_run_binding_missing", "Job lacks an immutable benchmark binding.")
    arm = db.get(models.BenchmarkArm, binding.benchmark_arm_id)
    campaign = db.get(models.BenchmarkCampaign, binding.campaign_id)
    batch_binding = db.get(models.BenchmarkCampaignBatchBinding, binding.batch_binding_id)
    if arm is None or campaign is None or batch_binding is None:
        _blocked("benchmark_binding_graph_incomplete", "Benchmark binding graph is incomplete.")
    if (
        campaign.status != "ACTIVE"
        or arm.campaign_id != campaign.id
        or batch_binding.campaign_id != campaign.id
        or binding.campaign_id != campaign.id
        or binding.job_id != job.id
    ):
        _blocked("benchmark_campaign_inactive", "Benchmark campaign is inactive or mismatched.")
    if job.user_id is None or job.user_id != campaign.user_id:
        _blocked("benchmark_owner_mismatch", "Job and campaign owners differ.")
    if not arm.execution_enabled:
        _blocked("benchmark_arm_execution_disabled", "Frozen benchmark arm is disabled.")

    try:
        arm_manifest = BenchmarkArmManifestV1.model_validate(arm.manifest_json)
        campaign_manifest = BenchmarkCampaignManifestV1.model_validate(campaign.manifest_json)
        inventory = CompositeExecutionInventoryV1.model_validate(campaign.composite_inventory_json)
        descriptor = require_registered_adapter(arm.proposal_adapter_id)
    except ValueError as exc:
        raise BenchmarkJobRuntimeBlocked(
            "benchmark_runtime_contract_invalid",
            "Benchmark runtime contract cannot be validated by the current server.",
        ) from exc
    if descriptor.availability != "implemented":
        _blocked("benchmark_adapter_not_implemented", "Frozen proposal adapter is not executable.")
    if descriptor.family != arm.arm_family:
        _blocked("benchmark_adapter_family_drift", "Adapter family differs from the frozen arm.")
    if canonical_sha256(arm_manifest) != arm.manifest_sha256:
        _blocked("benchmark_arm_manifest_drift", "Arm manifest hash no longer matches.")
    if canonical_sha256(campaign_manifest) != campaign.manifest_sha256:
        _blocked("benchmark_campaign_manifest_drift", "Campaign manifest hash no longer matches.")
    if canonical_sha256(inventory) != campaign.composite_inventory_sha256:
        _blocked("benchmark_inventory_drift", "Composite inventory hash no longer matches.")
    if campaign_manifest.composite_execution_inventory != inventory:
        _blocked("benchmark_inventory_manifest_mismatch", "Inventory copies disagree.")
    matching = [
        item
        for item in campaign_manifest.arms
        if item.benchmark_arm_id == arm.benchmark_arm_id and item.arm_version == arm.arm_version
    ]
    if len(matching) != 1 or matching[0] != arm_manifest:
        _blocked("benchmark_arm_campaign_mismatch", "Arm differs from campaign manifest.")
    if (
        arm_manifest.proposal_adapter_id != arm.proposal_adapter_id
        or arm_manifest.arm_family != arm.arm_family
        or not arm_manifest.execution_enabled
    ):
        _blocked("benchmark_arm_runtime_drift", "Persisted arm fields disagree.")

    contract = sealed_contract_for_job(job)
    if contract is None or not isinstance(job.scenario_suite_json, dict):
        _blocked("benchmark_qualification_not_sealed", "Qualification contract is not sealed.")
    suite_sha256 = canonical_sha256(
        schemas.ScenarioSuiteConfig.model_validate(job.scenario_suite_json).model_dump(mode="json")
    )
    qualification_sha256 = sealed_qualification_contract_sha256(contract)
    fairness = campaign_manifest.fairness
    if fairness.observation_contract_sha256 != BENCHMARK_OBSERVATION_CONTRACT_SHA256:
        _blocked(
            "benchmark_observation_contract_drift",
            "Campaign observation contract differs from the executable server contract.",
        )
    if fairness.evaluator_contract_id != arm_manifest.evaluator_contract_id:
        _blocked(
            "benchmark_evaluator_contract_drift",
            "Campaign and arm evaluator contracts disagree.",
        )
    if fairness.qualification_rule_sha256 != QUALIFICATION_RULE_SHA256:
        _blocked(
            "benchmark_qualification_rule_drift",
            "Campaign qualification rule differs from the executable server rule.",
        )
    if fairness.scenario_manifest_sha256 != suite_sha256:
        _blocked(
            "benchmark_scenario_manifest_drift",
            "Campaign scenario manifest differs from the bound Job suite.",
        )
    if (
        binding.scenario_suite_sha256 != suite_sha256
        or binding.qualification_contract_sha256 != qualification_sha256
    ):
        _blocked("benchmark_qualification_binding_drift", "Run qualification hashes drifted.")
    request = BenchmarkRunBindingRequestV1(
        run_key=binding.run_key,
        job_id=binding.job_id,
        benchmark_arm_id=arm.benchmark_arm_id,
        arm_version=arm.arm_version,
        algorithm_seed=binding.algorithm_seed,
        simulator_seed_block=binding.simulator_seed_block,
        provider_randomness_policy=binding.provider_randomness_policy,  # type: ignore[arg-type]
        provider_seed=binding.provider_seed,
    )
    expected_binding_sha256 = run_binding_sha256(
        request,
        scenario_suite_sha256=suite_sha256,
        qualification_contract_sha256=qualification_sha256,
    )
    if expected_binding_sha256 != binding.binding_sha256:
        _blocked("benchmark_run_binding_drift", "Run binding hash no longer matches.")

    expected_hashes = runtime_fairness_hashes(job)
    actual_fairness = fairness.model_dump(mode="json")
    drifted = [
        name for name, expected in expected_hashes.items() if actual_fairness[name] != expected
    ]
    if drifted:
        _blocked(
            "benchmark_fairness_contract_drift",
            "Job runtime differs from preregistered fairness hashes: " + ", ".join(drifted),
        )
    return BenchmarkJobRuntimeContext(
        binding=binding,
        arm=arm,
        campaign=campaign,
        campaign_manifest=campaign_manifest,
        arm_manifest=arm_manifest,
        inventory=inventory,
    )


def _proposal_context(
    candidate: models.CandidateParameterSet,
    *,
    expected_adapter_id: str,
) -> BenchmarkProposalContextV1 | None:
    if candidate.is_baseline:
        return None
    metadata = candidate.optimizer_metadata_json
    payload = metadata.get("benchmark_proposal_context") if isinstance(metadata, dict) else None
    try:
        context = BenchmarkProposalContextV1.model_validate(payload)
    except ValueError as exc:
        raise BenchmarkJobRuntimeBlocked(
            "benchmark_candidate_provenance_missing",
            "A benchmark candidate lacks valid proposal provenance.",
        ) from exc
    if context.proposal_adapter_id != expected_adapter_id:
        _blocked(
            "benchmark_candidate_arm_mismatch",
            "Historical candidate was produced by a different benchmark arm.",
        )
    return context


def _history_for_job(
    job: models.Job,
    *,
    expected_adapter_id: str,
) -> list[BenchmarkHistoryItemV2]:
    space = search_space_for_job(
        job,
        baseline_parameters=(
            job.baseline_parameter_json if isinstance(job.baseline_parameter_json, dict) else {}
        ),
    )
    trusted = observations_for_job(job, search_space=space, candidates=job.candidates)
    by_id = {candidate.id: candidate for candidate in job.candidates}
    history: list[BenchmarkHistoryItemV2] = []
    for item in trusted:
        candidate = by_id.get(item.candidate_id)
        if candidate is None or candidate.dispatch_ordinal is None:
            _blocked(
                "benchmark_history_dispatch_ordinal_missing",
                "Trusted benchmark history lacks server dispatch order.",
            )
        context = _proposal_context(candidate, expected_adapter_id=expected_adapter_id)
        role = item.role
        status: Literal[
            "pending",
            "passed",
            "failed",
            "unsafe",
            "timeout",
            "indeterminate",
            "cancelled",
        ] = (
            "pending"
            if role == "pending_reservation"
            else "unsafe"
            if role == "constraint_only"
            else "passed"
            if item.feasible
            else "failed"
        )
        history.append(
            BenchmarkHistoryItemV2(
                candidate_ref=candidate.id,
                generation_index=item.generation_index,
                dispatch_ordinal=candidate.dispatch_ordinal,
                parameters=item.parameters,
                screening_status=status,
                proposal_context=context,
                outcome=BenchmarkOptimizerOutcomeV1(
                    role=role,
                    loss=item.loss,
                    objectives=item.objectives,
                    objective_directions=item.objective_directions,  # type: ignore[arg-type]
                    constraint_violations=item.constraints,
                    feasible=item.feasible,
                    failure_rate=item.failure_rate,
                    fidelity=item.fidelity,
                    requested_fidelity=item.requested_fidelity,
                    completed=item.completed,
                ),
            )
        )
    history.sort(key=lambda item: item.dispatch_ordinal)
    return history


def build_benchmark_job_observation(
    db: Session,
    job: models.Job,
) -> tuple[BenchmarkJobRuntimeContext, BenchmarkObservationV2]:
    context = require_benchmark_job_runtime_context(db, job)
    contract = sealed_contract_for_job(job)
    if contract is None:
        raise ValueError("benchmark job is missing its sealed runtime contract")
    parameter_domain, objectives, constraints = _normalized_runtime_contracts(job)
    history = _history_for_job(
        job,
        expected_adapter_id=context.arm.proposal_adapter_id,
    )
    screening_count = len(screening_runs(contract))
    generation_remaining = max(0, job.max_iterations - job.current_generation)
    trial_capacity = max(0, job.max_total_trials - job.progress_total_trials) // max(
        1, screening_count
    )
    state = context.campaign.coordinator_state
    global_wall_seconds = max(
        0,
        context.campaign.wall_time_second_cap
        - (state.wall_time_seconds_used if state is not None else 0),
    )
    if job.started_at is not None:
        started = job.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed_ms = max(
            0,
            int(
                (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()
                * 1000
            ),
        )
    else:
        elapsed_ms = 0
    wall_time_remaining_ms = max(0, global_wall_seconds * 1000 - elapsed_ms)
    return context, BenchmarkObservationV2(
        campaign_id=context.campaign.id,
        run_id=context.binding.id,
        benchmark_arm_id=context.arm.benchmark_arm_id,
        generation_index=job.current_generation + 1,
        next_dispatch_ordinal=job.next_candidate_dispatch_ordinal,
        algorithm_seed=context.binding.algorithm_seed,
        simulator_seed_block_id=context.binding.simulator_seed_block,
        parameter_domain=parameter_domain,
        objectives=objectives,
        constraints=constraints,
        history=history,
        failure_semantics=dict(BENCHMARK_FAILURE_SEMANTICS_V1),
        simulator_budget_remaining=min(generation_remaining, trial_capacity),
        wall_time_remaining_ms=wall_time_remaining_ms,
    )


__all__ = [
    "BENCHMARK_FAILURE_SEMANTICS_SHA256",
    "BENCHMARK_HISTORY_CONTRACT_SHA256",
    "BenchmarkJobRuntimeBlocked",
    "BenchmarkJobRuntimeContext",
    "benchmark_run_binding",
    "build_benchmark_job_observation",
    "require_benchmark_job_runtime_context",
    "runtime_fairness_hashes",
]
