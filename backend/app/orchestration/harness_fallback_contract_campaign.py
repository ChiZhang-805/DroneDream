"""Offline fallback-equivalence campaign for the live multi-tool Harness.

The legacy v1 outcome campaign predates the bounded budget-plan and
post-proposal revision turns.  This campaign exercises those current
production contracts with three matched ``llm_harness`` arms:

* no provider client, which takes the missing-key deterministic fallback;
* a local client that raises before transport;
* a local client that returns schema-invalid objects.

All connections are blocked and counted.  This is deterministic mock
integration evidence only; it does not measure model quality, physical
fidelity, or causal benefit.
"""

from __future__ import annotations

from typing import Any

from app import models, schemas
from app.orchestration.harness_outcome_campaign import (
    HARNESS_OUTCOME_CAMPAIGN_MAX_ITERATIONS,
    HARNESS_OUTCOME_CAMPAIGN_MAX_TOTAL_TRIALS,
    HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS,
    _drive_job,
    _InvalidResponseClient,
    _isolated_session_factory,
    _network_connect_guard,
    _ProviderErrorClient,
    _scenario_suite,
    _sha256,
)
from app.services import jobs as job_services

HARNESS_FALLBACK_CONTRACT_LEGACY_SCHEMA_VERSION = (
    "dronedream.harness-fallback-contract-campaign/v2"
)
HARNESS_FALLBACK_CONTRACT_SCHEMA_VERSION = (
    "dronedream.harness-fallback-contract-campaign/v3"
)
HARNESS_FALLBACK_CONTRACT_EVIDENCE_CLASS = (
    "synthetic_mock_multi_tool_fallback_campaign"
)
HARNESS_FALLBACK_CONTRACT_LABEL = "SYNTHETIC_MOCK"
HARNESS_FALLBACK_CONTRACT_CLAIM_BOUNDARY = (
    "Outcome-level deterministic integration check on MockSimulatorAdapter. "
    "It verifies that the current multi-tool Harness missing-key, provider-error, "
    "and invalid-response paths compile the same bounded deterministic portfolio "
    "plan and reach byte-equivalent normalized persisted outcomes under matched "
    "seeds and budgets. It does not establish LLM superiority, causal Harness "
    "benefit, PX4/Gazebo performance, physical fidelity, or real-flight safety."
)
HARNESS_FALLBACK_CONTRACT_ARMS = (
    "deterministic_no_provider_baseline",
    "provider_error_fallback",
    "invalid_response_fallback",
)
HARNESS_FALLBACK_CONTRACT_REFERENCE_ARM = HARNESS_FALLBACK_CONTRACT_ARMS[0]

_OUTCOME_COMPONENTS = (
    "candidates",
    "trials",
    "budget",
    "winner",
    "holdout_loss",
    "failure_count",
    "evidence_completeness",
)


def _job_request(seed_block: int) -> schemas.JobCreateRequest:
    return schemas.JobCreateRequest(
        display_name=f"synthetic-multi-tool-fallback-{seed_block}",
        simulator_backend="mock",
        optimizer_strategy="llm_harness",
        max_iterations=HARNESS_OUTCOME_CAMPAIGN_MAX_ITERATIONS,
        max_total_trials=HARNESS_OUTCOME_CAMPAIGN_MAX_TOTAL_TRIALS,
        acceptance_criteria=schemas.AcceptanceCriteria(
            target_rmse=0.01,
            min_pass_rate=1.0,
        ),
        scenario_suite=_scenario_suite(seed_block),
    )


def _tool_projection(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_rows = payload.get("tool_calls")
    if not isinstance(raw_rows, list):
        return []
    return [
        {
            "tool_id": row.get("tool_id"),
            "status": row.get("status"),
            "allocation": row.get("allocation"),
            "proposal_count": row.get("proposal_count"),
        }
        for row in raw_rows
        if isinstance(row, dict)
    ]


def _fallback_trace(job: models.Job) -> dict[str, Any]:
    rows: dict[int, dict[str, Any]] = {}
    for event in sorted(job.events, key=lambda item: (item.created_at, item.id)):
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        raw_generation = payload.get("generation")
        if isinstance(raw_generation, bool) or not isinstance(raw_generation, int):
            continue
        row = rows.setdefault(raw_generation, {"generation": raw_generation})
        if event.event_type == "harness_budget_plan_fallback":
            compiled = payload.get("compiled_plan")
            raw_calls = (
                compiled.get("calls") if isinstance(compiled, dict) else None
            )
            calls = raw_calls if isinstance(raw_calls, list) else []
            row["budget_plan_fallback"] = {
                "reason": payload.get("reason"),
                "source": payload.get("source"),
                "compiled_plan_sha256": payload.get("compiled_plan_sha256"),
                "projected_candidate_count": payload.get(
                    "projected_candidate_count"
                ),
                "projected_trial_upper_bound": payload.get(
                    "projected_trial_upper_bound"
                ),
                "tool_ids": [
                    call.get("tool_id") for call in calls if isinstance(call, dict)
                ],
            }
        elif event.event_type == "harness_plan_revision_fallback":
            row["plan_revision_fallback"] = {
                "reason": payload.get("reason"),
                "source": payload.get("source"),
            }
        elif event.event_type == "harness_multi_tool_execution_result":
            row["execution"] = {
                "status": payload.get("status"),
                "decision_source": payload.get("decision_source"),
                "revision_source": payload.get("revision_source"),
                "fallback_reason": payload.get("fallback_reason"),
                "revision_fallback_reason": payload.get(
                    "revision_fallback_reason"
                ),
                "provider_call_count": payload.get("provider_call_count"),
                "planned_candidates": payload.get("planned_candidates"),
                "dispatched_candidates": payload.get("dispatched_candidates"),
                "dispatched_trials": payload.get("dispatched_trials"),
                "tool_calls": _tool_projection(payload),
            }
    return {"generation_rows": [rows[index] for index in sorted(rows)]}


def _run_arm(seed_block: int, arm: str) -> dict[str, Any]:
    if arm not in HARNESS_FALLBACK_CONTRACT_ARMS:
        raise ValueError(f"unknown fallback campaign arm: {arm}")
    client: _ProviderErrorClient | _InvalidResponseClient | None
    if arm == "provider_error_fallback":
        client = _ProviderErrorClient()
    elif arm == "invalid_response_fallback":
        client = _InvalidResponseClient()
    else:
        client = None

    with (
        _network_connect_guard() as network_measurement,
        _isolated_session_factory() as factory,
    ):
        with factory() as db:
            user = models.User(
                email=f"multi-tool-fallback-{seed_block}@dronedream.invalid",
                display_name="Multi-tool fallback campaign",
            )
            db.add(user)
            db.flush()
            job = job_services._create_job_from_config(
                db,
                user=user,
                req=_job_request(seed_block),
            )
            job_id = job.id
            db.commit()
        outcome, _legacy_trace = _drive_job(
            factory,
            job_id=job_id,
            client=client,
        )
        with factory() as db:
            loaded_job = db.get(models.Job, job_id)
            if loaded_job is None:
                raise RuntimeError("fallback campaign Job disappeared")
            trace = _fallback_trace(loaded_job)

    network_calls = network_measurement.attempt_count
    if network_calls:
        raise ValueError(
            f"fallback campaign arm attempted {network_calls} network connection(s)"
        )
    provider_calls = client.calls if client is not None else 0
    return {
        "arm": arm,
        "provider_calls": provider_calls,
        "network_calls": network_calls,
        "network_connect_guard_enforced": True,
        "real_credentials_used": False,
        "fallback_trace": trace,
        "outcome_sha256": _sha256(outcome),
        "component_sha256": {
            component: _sha256(outcome[component])
            for component in _OUTCOME_COMPONENTS
        },
        "outcome": outcome,
    }


def _expected_reasons(arm_name: str) -> tuple[str, str, int]:
    if arm_name == "deterministic_no_provider_baseline":
        return "missing_api_key", "missing_api_key", 0
    if arm_name == "provider_error_fallback":
        return "client_error", "client_error", 2
    if arm_name == "invalid_response_fallback":
        return "invalid_plan", "invalid_schema", 2
    raise ValueError(f"unknown fallback campaign arm: {arm_name}")


def _verify_arm_trace(arm: dict[str, Any]) -> None:
    arm_name = arm.get("arm")
    if not isinstance(arm_name, str):
        raise ValueError("fallback campaign arm name is invalid")
    plan_reason, revision_reason, provider_calls_per_generation = _expected_reasons(
        arm_name
    )
    trace = arm.get("fallback_trace")
    rows = trace.get("generation_rows") if isinstance(trace, dict) else None
    if not isinstance(rows, list) or len(rows) != HARNESS_OUTCOME_CAMPAIGN_MAX_ITERATIONS:
        raise ValueError(f"{arm_name} fallback trace has the wrong generation count")
    observed_provider_calls = 0
    for expected_generation, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or row.get("generation") != expected_generation:
            raise ValueError(f"{arm_name} fallback generation order is invalid")
        plan = row.get("budget_plan_fallback")
        revision = row.get("plan_revision_fallback")
        execution = row.get("execution")
        if (
            not isinstance(plan, dict)
            or plan.get("reason") != plan_reason
            or plan.get("source") != "deterministic_fallback"
            or plan.get("tool_ids") != ["optimizer_portfolio"]
            or not isinstance(plan.get("compiled_plan_sha256"), str)
            or len(plan["compiled_plan_sha256"]) != 64
            or not isinstance(revision, dict)
            or revision
            != {
                "reason": revision_reason,
                "source": "deterministic_fallback",
            }
            or not isinstance(execution, dict)
            or execution.get("status") != "dispatched"
            or execution.get("decision_source") != "deterministic_fallback"
            or execution.get("revision_source") != "deterministic_fallback"
            or execution.get("fallback_reason") != plan_reason
            or execution.get("revision_fallback_reason") != revision_reason
            or execution.get("provider_call_count")
            != provider_calls_per_generation
            or execution.get("planned_candidates")
            != execution.get("dispatched_candidates")
            or execution.get("dispatched_candidates", 0) < 1
            or not isinstance(execution.get("tool_calls"), list)
            or len(execution["tool_calls"]) != 1
            or any(
                not isinstance(tool, dict)
                or tool.get("tool_id") != "optimizer_portfolio"
                or tool.get("status") != "completed"
                or tool.get("allocation") != execution.get("planned_candidates")
                or tool.get("proposal_count") != execution.get("dispatched_candidates")
                for tool in execution["tool_calls"]
            )
        ):
            raise ValueError(
                f"{arm_name} generation {expected_generation} did not exercise "
                "the declared current fallback contract"
            )
        observed_provider_calls += provider_calls_per_generation
    if arm.get("provider_calls") != observed_provider_calls:
        raise ValueError(f"{arm_name} provider-call count does not match its trace")


def build_harness_fallback_contract_campaign() -> dict[str, Any]:
    """Run all current fallback arms and return a self-hashed artifact."""

    block_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    for block_index, seed_block in enumerate(
        HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS,
        start=1,
    ):
        arms = [_run_arm(seed_block, arm) for arm in HARNESS_FALLBACK_CONTRACT_ARMS]
        by_name = {str(arm["arm"]): arm for arm in arms}
        reference = by_name[HARNESS_FALLBACK_CONTRACT_REFERENCE_ARM]
        for arm in arms:
            _verify_arm_trace(arm)
        for arm_name in HARNESS_FALLBACK_CONTRACT_ARMS[1:]:
            arm = by_name[arm_name]
            component_matches = {
                component: (
                    arm["outcome"][component] == reference["outcome"][component]
                )
                for component in _OUTCOME_COMPONENTS
            }
            exact_match = arm["outcome"] == reference["outcome"]
            if not exact_match or not all(component_matches.values()):
                raise ValueError(
                    f"{arm_name} diverged from deterministic fallback baseline "
                    f"in seed block {seed_block}"
                )
            comparison_rows.append(
                {
                    "block_id": block_index,
                    "seed_block": seed_block,
                    "reference_arm": HARNESS_FALLBACK_CONTRACT_REFERENCE_ARM,
                    "comparison_arm": arm_name,
                    "exact_outcome_match": exact_match,
                    **{
                        f"{component}_match": component_matches[component]
                        for component in _OUTCOME_COMPONENTS
                    },
                }
            )
        block_rows.append(
            {
                "block_id": block_index,
                "seed_block": seed_block,
                "arms": arms,
            }
        )

    unsigned: dict[str, Any] = {
        "schema_version": HARNESS_FALLBACK_CONTRACT_SCHEMA_VERSION,
        "evidence_class": HARNESS_FALLBACK_CONTRACT_EVIDENCE_CLASS,
        "claim_label": HARNESS_FALLBACK_CONTRACT_LABEL,
        "claim_boundary": HARNESS_FALLBACK_CONTRACT_CLAIM_BOUNDARY,
        "physical_fidelity": False,
        "simulator_backend": "mock",
        "live_model_calls": False,
        "network_calls": 0,
        "real_credentials_used": False,
        "llm_superiority_claim_permitted": False,
        "harness_causal_benefit_claim_permitted": False,
        "px4_or_flight_claim_permitted": False,
        "methodology": {
            "seed_blocks": list(HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS),
            "arms": list(HARNESS_FALLBACK_CONTRACT_ARMS),
            "reference_arm": HARNESS_FALLBACK_CONTRACT_REFERENCE_ARM,
            "max_iterations_per_arm": HARNESS_OUTCOME_CAMPAIGN_MAX_ITERATIONS,
            "max_total_trials_per_arm": HARNESS_OUTCOME_CAMPAIGN_MAX_TOTAL_TRIALS,
            "network_measurement": (
                "socket.connect, socket.connect_ex, and "
                "socket.create_connection are blocked and counted per arm"
            ),
            "nondeterministic_fields_excluded": [
                "database_primary_keys",
                "timestamps",
                "worker_ids",
                "filesystem_paths",
                "evidence_ids",
                "harness_decision_ids",
                "harness_revision_ids",
                "harness_call_ids",
                "wall_and_cpu_timings",
            ],
            "strict_components": list(_OUTCOME_COMPONENTS),
        },
        "summary": {
            "seed_block_count": len(HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS),
            "arm_run_count": len(HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS)
            * len(HARNESS_FALLBACK_CONTRACT_ARMS),
            "total_persisted_trials": sum(
                int(arm["outcome"]["budget"]["trial_count"])
                for block in block_rows
                for arm in block["arms"]
            ),
            "fallback_comparison_count": len(comparison_rows),
            "exact_outcome_match_count": sum(
                row["exact_outcome_match"] is True for row in comparison_rows
            ),
            "all_fallback_outcomes_match_deterministic_baseline": all(
                row["exact_outcome_match"] is True for row in comparison_rows
            ),
            "all_evidence_complete": all(
                arm["outcome"]["evidence_completeness"]["completeness_rate"] == 1.0
                for block in block_rows
                for arm in block["arms"]
            ),
        },
        "comparison_rows": comparison_rows,
        "block_rows": block_rows,
    }
    return {**unsigned, "artifact_sha256": _sha256(unsigned)}


def verify_harness_fallback_contract_campaign(payload: object) -> dict[str, Any]:
    """Verify v2/v3 artifact integrity, traces, claim bounds, and equivalence."""

    if not isinstance(payload, dict):
        raise ValueError("Harness fallback contract campaign must be an object")
    artifact = dict(payload)
    declared_hash = artifact.pop("artifact_sha256", None)
    if not isinstance(declared_hash, str) or declared_hash != _sha256(artifact):
        raise ValueError("Harness fallback contract artifact hash does not recompute")
    if (
        artifact.get("schema_version")
        not in {
            HARNESS_FALLBACK_CONTRACT_LEGACY_SCHEMA_VERSION,
            HARNESS_FALLBACK_CONTRACT_SCHEMA_VERSION,
        }
        or artifact.get("evidence_class") != HARNESS_FALLBACK_CONTRACT_EVIDENCE_CLASS
        or artifact.get("claim_label") != HARNESS_FALLBACK_CONTRACT_LABEL
        or artifact.get("claim_boundary") != HARNESS_FALLBACK_CONTRACT_CLAIM_BOUNDARY
        or artifact.get("physical_fidelity") is not False
        or artifact.get("simulator_backend") != "mock"
        or artifact.get("live_model_calls") is not False
        or artifact.get("network_calls") != 0
        or artifact.get("real_credentials_used") is not False
        or artifact.get("llm_superiority_claim_permitted") is not False
        or artifact.get("harness_causal_benefit_claim_permitted") is not False
        or artifact.get("px4_or_flight_claim_permitted") is not False
    ):
        raise ValueError("Harness fallback contract claim boundary is invalid")

    block_rows = artifact.get("block_rows")
    if not isinstance(block_rows, list) or len(block_rows) != len(
        HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS
    ):
        raise ValueError("Harness fallback contract block rows are invalid")
    recomputed_comparisons: list[dict[str, Any]] = []
    for expected_index, (seed_block, block) in enumerate(
        zip(HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS, block_rows, strict=True),
        start=1,
    ):
        if (
            not isinstance(block, dict)
            or block.get("block_id") != expected_index
            or block.get("seed_block") != seed_block
            or not isinstance(block.get("arms"), list)
        ):
            raise ValueError("Harness fallback contract block identity is invalid")
        raw_arms = block["arms"]
        by_name = {
            str(arm.get("arm")): arm for arm in raw_arms if isinstance(arm, dict)
        }
        if tuple(by_name) != HARNESS_FALLBACK_CONTRACT_ARMS:
            raise ValueError("Harness fallback contract arm order or set drifted")
        for arm in raw_arms:
            if not isinstance(arm, dict):
                raise ValueError("Harness fallback contract arm is invalid")
            _verify_arm_trace(arm)
            outcome = arm.get("outcome")
            component_hashes = arm.get("component_sha256")
            if (
                not isinstance(outcome, dict)
                or arm.get("outcome_sha256") != _sha256(outcome)
                or arm.get("network_calls") != 0
                or arm.get("network_connect_guard_enforced") is not True
                or arm.get("real_credentials_used") is not False
                or not isinstance(component_hashes, dict)
                or any(
                    component_hashes.get(component) != _sha256(outcome.get(component))
                    for component in _OUTCOME_COMPONENTS
                )
            ):
                raise ValueError("Harness fallback contract arm integrity is invalid")
        reference = by_name[HARNESS_FALLBACK_CONTRACT_REFERENCE_ARM]
        for arm_name in HARNESS_FALLBACK_CONTRACT_ARMS[1:]:
            arm = by_name[arm_name]
            matches = {
                component: (
                    arm["outcome"][component] == reference["outcome"][component]
                )
                for component in _OUTCOME_COMPONENTS
            }
            recomputed_comparisons.append(
                {
                    "block_id": expected_index,
                    "seed_block": seed_block,
                    "reference_arm": HARNESS_FALLBACK_CONTRACT_REFERENCE_ARM,
                    "comparison_arm": arm_name,
                    "exact_outcome_match": arm["outcome"] == reference["outcome"],
                    **{
                        f"{component}_match": matches[component]
                        for component in _OUTCOME_COMPONENTS
                    },
                }
            )
    if artifact.get("comparison_rows") != recomputed_comparisons or not all(
        row["exact_outcome_match"] is True
        and all(
            row[f"{component}_match"] is True
            for component in _OUTCOME_COMPONENTS
        )
        for row in recomputed_comparisons
    ):
        raise ValueError("Harness fallback contract outcomes are not equivalent")
    summary = artifact.get("summary")
    expected_summary = {
        "seed_block_count": len(HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS),
        "arm_run_count": len(HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS)
        * len(HARNESS_FALLBACK_CONTRACT_ARMS),
        "total_persisted_trials": sum(
            int(arm["outcome"]["budget"]["trial_count"])
            for block in block_rows
            for arm in block["arms"]
        ),
        "fallback_comparison_count": len(recomputed_comparisons),
        "exact_outcome_match_count": len(recomputed_comparisons),
        "all_fallback_outcomes_match_deterministic_baseline": True,
        "all_evidence_complete": all(
            arm["outcome"]["evidence_completeness"]["completeness_rate"] == 1.0
            for block in block_rows
            for arm in block["arms"]
        ),
    }
    if summary != expected_summary:
        raise ValueError("Harness fallback contract summary does not recompute")
    return payload


__all__ = [
    "HARNESS_FALLBACK_CONTRACT_ARMS",
    "HARNESS_FALLBACK_CONTRACT_CLAIM_BOUNDARY",
    "HARNESS_FALLBACK_CONTRACT_EVIDENCE_CLASS",
    "HARNESS_FALLBACK_CONTRACT_LABEL",
    "HARNESS_FALLBACK_CONTRACT_LEGACY_SCHEMA_VERSION",
    "HARNESS_FALLBACK_CONTRACT_REFERENCE_ARM",
    "HARNESS_FALLBACK_CONTRACT_SCHEMA_VERSION",
    "build_harness_fallback_contract_campaign",
    "verify_harness_fallback_contract_campaign",
]
