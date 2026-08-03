"""Frozen, offline outcome ablations for AURORA decision components.

The campaign exercises the production Job/Candidate/Trial orchestration and
``MockSimulatorAdapter`` under one preregistered protocol.  A local scripted
router is used instead of a language model so the decision policy is exactly
reproducible and no credential or network transport exists.

The four arms differ only at declared boundaries:

* ``full_aurora`` receives the current decision memory and verified
  observed-outcome reflection;
* ``no_decision_memory`` receives an empty decision-memory sequence;
* ``no_observed_outcome_reflection`` keeps decision receipts but removes the
  observational outcome fields;
* ``fixed_deterministic_portfolio`` bypasses the Harness and runs the shipped
  deterministic optimizer portfolio.

This is synthetic protocol evidence, not PX4/Gazebo, real-flight, language
model, or general causal-performance evidence.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable
from types import ModuleType
from typing import Any, Literal, cast
from unittest.mock import patch

from app import models, schemas
from app.orchestration import aggregation
from app.orchestration.harness_context import (
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_PROMPT_TEMPLATE_VERSION,
    HARNESS_TOOL_REGISTRY_VERSION,
    HarnessEvidenceSnapshot,
    HarnessExecutionMemory,
)
from app.orchestration.harness_outcome_campaign import (
    _drive_job,
    _isolated_session_factory,
    _network_connect_guard,
    _normalized_json,
    _sha256,
)
from app.services import jobs as job_services

HARNESS_COMPONENT_ABLATION_SCHEMA_VERSION = "dronedream.harness-component-outcome-ablation/v1"
HARNESS_COMPONENT_ABLATION_MANIFEST_SCHEMA_VERSION = (
    "dronedream.harness-component-outcome-ablation-manifest/v1"
)
HARNESS_COMPONENT_ABLATION_EVIDENCE_CLASS = "synthetic_mock_component_ablation"
HARNESS_COMPONENT_ABLATION_LABEL = "SYNTHETIC_MOCK"
HARNESS_COMPONENT_ABLATION_CLAIM_BOUNDARY = (
    "Matched, deterministic component intervention on MockSimulatorAdapter "
    "using a preregistered local scripted router. Results describe only this "
    "frozen synthetic protocol. They do not establish general AURORA or LLM "
    "superiority, PX4/Gazebo performance, physical fidelity, transfer to real "
    "aircraft, or real-flight safety."
)
HARNESS_COMPONENT_ABLATION_SEED_BLOCKS = (6100, 7200, 8300, 9400, 10500)
HARNESS_COMPONENT_ABLATION_ARMS = (
    "full_aurora",
    "no_decision_memory",
    "no_observed_outcome_reflection",
    "fixed_deterministic_portfolio",
)
HARNESS_COMPONENT_ABLATION_MAX_ITERATIONS = 2
HARNESS_COMPONENT_ABLATION_MAX_TOTAL_TRIALS = 40
HARNESS_COMPONENT_ABLATION_TARGET_RELATIVE_IMPROVEMENT = 0.05
HARNESS_COMPONENT_ABLATION_LEGACY_MANIFEST_SHA256 = (
    "28092e9a5114bd4a02c297246cde8467014e22553d93c028a19b08db678a5072"
)

HarnessComponentArm = Literal[
    "full_aurora",
    "no_decision_memory",
    "no_observed_outcome_reflection",
    "fixed_deterministic_portfolio",
]

_RESULT_METRICS = (
    "holdout_loss",
    "optimizer_feasible_rate",
    "trials_to_target",
    "total_trials",
    "terminal_failure_trials",
    "recovered_trials",
    "evidence_completeness_rate",
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _manifest_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def build_harness_component_ablation_manifest() -> dict[str, Any]:
    """Return the immutable preregistration used by every campaign arm."""

    unsigned: dict[str, Any] = {
        "schema_version": HARNESS_COMPONENT_ABLATION_MANIFEST_SCHEMA_VERSION,
        "evidence_class": HARNESS_COMPONENT_ABLATION_EVIDENCE_CLASS,
        "claim_label": HARNESS_COMPONENT_ABLATION_LABEL,
        "claim_boundary": HARNESS_COMPONENT_ABLATION_CLAIM_BOUNDARY,
        "arms": list(HARNESS_COMPONENT_ABLATION_ARMS),
        "seed_blocks": list(HARNESS_COMPONENT_ABLATION_SEED_BLOCKS),
        "initial_design": {
            "kind": "shared_service_default_baseline",
            "candidate_count": 1,
            "same_for_every_arm": True,
            "parameter_space": "legacy_six_parameter_domain",
            "baseline_parameters": schemas.BaselineParameters().model_dump(mode="json"),
        },
        "scenario_matrix": {
            "common_random_numbers": True,
            "training": [
                {"case": "nominal-training", "seed_offset": 1},
                {"case": "wind-training", "seed_offset": 2},
                {"case": "noise-training", "seed_offset": 3},
            ],
            "holdout": [
                {"case": "combined-holdout", "seed_offset": 99},
            ],
        },
        "objective_contract": {
            "objectives": [
                {"metric": "rmse", "direction": "minimize"},
            ],
            "constraints": [
                {
                    "metric": "max_error",
                    "operator": "lte",
                    "threshold": 3.0,
                    "hard": True,
                },
            ],
            "robust_aggregation": "mean",
        },
        "budget": {
            "max_iterations": HARNESS_COMPONENT_ABLATION_MAX_ITERATIONS,
            "max_total_trials": HARNESS_COMPONENT_ABLATION_MAX_TOTAL_TRIALS,
            "terminal_accounting": (
                "every persisted terminal Trial remains in total, failure, "
                "recovery, and evidence-completeness denominators"
            ),
        },
        "time_to_target": {
            "metric": "training scalar_loss",
            "target": (
                "first generation containing a full-fidelity feasible optimizer "
                "candidate at least 5% better than the shared baseline"
            ),
            "relative_improvement": (HARNESS_COMPONENT_ABLATION_TARGET_RELATIVE_IMPROVEMENT),
            "accounting": (
                "all Trial rows through the complete target generation; "
                "otherwise right-censored at the arm total"
            ),
        },
        "scripted_router_policy": {
            "generation_1": (
                "choose constrained_mobo when eligible; otherwise choose optimizer_portfolio"
            ),
            "later_generation_with_verified_reflection": (
                "choose turbo when eligible and the prior cohort has complete "
                "evidence, at least one feasible candidate, and zero domain "
                "failure Trials; otherwise choose optimizer_portfolio"
            ),
            "later_generation_without_verified_reflection": ("choose optimizer_portfolio"),
            "no_free_text_feedback": True,
        },
        "interventions": {
            "full_aurora": "no context intervention",
            "no_decision_memory": ("replace the provider-visible decision_memory tuple with empty"),
            "no_observed_outcome_reflection": (
                "preserve decision receipts but replace verified reflection "
                "with unavailable and remove observed_outcome"
            ),
            "fixed_deterministic_portfolio": (
                "bypass model routing and use optimizer_portfolio directly"
            ),
        },
        "runtime_contract": {
            "simulator_backend": "mock",
            "physical_fidelity": False,
            "live_model_calls": False,
            "real_credentials_used": False,
            "network_connect_guard": [
                "socket.connect",
                "socket.connect_ex",
                "socket.create_connection",
            ],
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
            "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
        },
        "metrics": list(_RESULT_METRICS),
        "interpretation_rule": {
            "inconclusive": (
                "an ablated component was unavailable, or the isolating "
                "contrast retained versus removed that component but the "
                "preregistered policy never made it decision-relevant and "
                "therefore produced identical tool sequences and outcomes"
            ),
            "observed_protocol_difference": (
                "the intervention was activated and at least one preregistered "
                "result metric differs from full_aurora"
            ),
            "no_observed_protocol_difference": (
                "the intervention was activated but all preregistered result "
                "metrics equal full_aurora"
            ),
        },
    }
    return {
        **unsigned,
        "manifest_sha256": _manifest_sha256(unsigned),
    }


def verify_harness_component_ablation_manifest(payload: object) -> dict[str, Any]:
    """Verify manifest integrity and immutable protocol constants."""

    if not isinstance(payload, dict):
        raise ValueError("Harness component-ablation manifest must be an object")
    manifest = dict(payload)
    declared_hash = manifest.pop("manifest_sha256", None)
    if not isinstance(declared_hash, str) or len(declared_hash) != 64:
        raise ValueError("Harness component-ablation manifest hash is invalid")
    if declared_hash != _manifest_sha256(manifest):
        raise ValueError("Harness component-ablation manifest hash does not recompute")
    runtime = payload.get("runtime_contract")
    legacy = (
        isinstance(runtime, dict)
        and runtime.get("evidence_schema_version") == "2.7"
        and runtime.get("prompt_template_version") == "1.6"
        and declared_hash == HARNESS_COMPONENT_ABLATION_LEGACY_MANIFEST_SHA256
    )
    current = build_harness_component_ablation_manifest()
    if payload != current and not legacy:
        raise ValueError("Harness component-ablation manifest drifted")
    return payload


def _scenario_suite(seed_block: int) -> schemas.ScenarioSuiteConfig:
    return schemas.ScenarioSuiteConfig(
        common_random_numbers=True,
        cases=[
            schemas.ScenarioCaseConfig(
                id="nominal-training",
                scenario_type="nominal",
                seeds=[seed_block + 1],
            ),
            schemas.ScenarioCaseConfig(
                id="wind-training",
                scenario_type="wind_perturbed",
                seeds=[seed_block + 2],
            ),
            schemas.ScenarioCaseConfig(
                id="noise-training",
                scenario_type="noise_perturbed",
                seeds=[seed_block + 3],
            ),
            schemas.ScenarioCaseConfig(
                id="combined-holdout",
                scenario_type="combined_perturbed",
                seeds=[seed_block + 99],
                holdout=True,
            ),
        ],
    )


def _job_request(
    seed_block: int,
    *,
    arm: HarnessComponentArm,
    max_iterations: int = HARNESS_COMPONENT_ABLATION_MAX_ITERATIONS,
    max_total_trials: int = HARNESS_COMPONENT_ABLATION_MAX_TOTAL_TRIALS,
) -> schemas.JobCreateRequest:
    strategy = "optimizer_portfolio" if arm == "fixed_deterministic_portfolio" else "llm_harness"
    return schemas.JobCreateRequest(
        display_name=f"synthetic-component-ablation-{seed_block}",
        simulator_backend="mock",
        optimizer_strategy=strategy,  # type: ignore[arg-type]
        max_iterations=max_iterations,
        max_total_trials=max_total_trials,
        objective_config=schemas.ObjectiveConfig(
            objectives=[
                schemas.ObjectiveSpec(metric="rmse", direction="minimize"),
            ],
            constraints=[
                schemas.ConstraintSpec(
                    metric="max_error",
                    operator="lte",
                    threshold=3.0,
                    hard=True,
                ),
            ],
            robust_aggregation="mean",
        ),
        acceptance_criteria=schemas.AcceptanceCriteria(
            # Intentionally unreachable: every arm receives the same bounded
            # opportunity to consume both preregistered generations.
            target_rmse=0.01,
            min_pass_rate=1.0,
        ),
        scenario_suite=_scenario_suite(seed_block),
    )


class _ScriptedRouterClient:
    """Exact local routing policy over the production provider payload."""

    def __init__(self) -> None:
        self.calls = 0
        self.trace: list[dict[str, Any]] = []

    def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
        del model, system
        self.calls += 1
        payload = json.loads(user)
        if not isinstance(payload, dict):
            raise ValueError("scripted router received a non-object payload")
        raw_evidence = payload.get("evidence")
        raw_manifest = payload.get("tool_manifest")
        if not isinstance(raw_evidence, dict) or not isinstance(raw_manifest, dict):
            raise ValueError("scripted router received incomplete evidence")
        raw_tools = raw_manifest.get("tools")
        if not isinstance(raw_tools, list):
            raise ValueError("scripted router received an invalid tool manifest")
        allowed_tools = [
            row.get("tool_id")
            for row in raw_tools
            if isinstance(row, dict) and isinstance(row.get("tool_id"), str)
        ]
        budget = raw_evidence.get("budget")
        current_generation = budget.get("current_generation") if isinstance(budget, dict) else None
        if isinstance(current_generation, bool) or not isinstance(
            current_generation,
            int,
        ):
            raise ValueError("scripted router received an invalid generation")
        raw_memory = raw_evidence.get("decision_memory", [])
        if not isinstance(raw_memory, list):
            raise ValueError("scripted router received invalid decision memory")
        verified = [
            row
            for row in raw_memory
            if isinstance(row, dict)
            and row.get("reflection_status") == "verified_complete"
            and isinstance(row.get("observed_outcome"), dict)
        ]
        selected = "optimizer_portfolio"
        reason = "portfolio fallback because verified reflection is unavailable"
        if current_generation == 0 and "constrained_mobo" in allowed_tools:
            selected = "constrained_mobo"
            reason = "preregistered first-generation constraint-aware exploration"
        elif verified and "turbo" in allowed_tools:
            latest = verified[-1]["observed_outcome"]
            if not isinstance(latest, dict):
                raise ValueError("verified reflection lost its observed outcome")
            if (
                latest.get("completed_candidate_rate") == 1.0
                and isinstance(latest.get("feasible_candidate_count"), int)
                and int(latest["feasible_candidate_count"]) > 0
                and latest.get("domain_failure_trial_count") == 0
            ):
                selected = "turbo"
                reason = "preregistered exploitation after complete feasible reflection"
        if selected not in allowed_tools:
            raise ValueError("scripted policy selected an ineligible tool")
        self.trace.append(
            {
                "generation": current_generation + 1,
                "allowed_tools": allowed_tools,
                "decision_memory_count": len(raw_memory),
                "verified_reflection_count": len(verified),
                "selected_tool": selected,
            }
        )
        return {
            "decision": {
                "tool_id": selected,
                "rationale": reason,
            }
        }


class _ContextIntervention:
    """Apply and measure one provider-visible evidence intervention."""

    def __init__(self, arm: HarnessComponentArm) -> None:
        self.arm = arm
        self.prompt_count = 0
        self.changed_prompt_count = 0
        self.removed_memory_count = 0
        self.removed_reflection_count = 0

    def apply(
        self,
        snapshot: HarnessEvidenceSnapshot,
        has_scored_evidence: bool,
    ) -> tuple[HarnessEvidenceSnapshot, bool]:
        self.prompt_count += 1
        memory = snapshot.decision_memory
        if self.arm == "no_decision_memory":
            self.removed_memory_count += len(memory)
            if memory:
                self.changed_prompt_count += 1
            snapshot = snapshot.model_copy(update={"decision_memory": ()})
        elif self.arm == "no_observed_outcome_reflection":
            transformed: list[HarnessExecutionMemory] = []
            changed = 0
            for item in memory:
                if item.reflection_status == "verified_complete":
                    changed += 1
                    transformed.append(
                        item.model_copy(
                            update={
                                "reflection_status": "unavailable",
                                "observed_outcome": None,
                            }
                        )
                    )
                else:
                    transformed.append(item)
            self.removed_reflection_count += changed
            if changed:
                self.changed_prompt_count += 1
            snapshot = snapshot.model_copy(update={"decision_memory": tuple(transformed)})
        return snapshot, has_scored_evidence

    def summary(self) -> dict[str, Any]:
        component = {
            "full_aurora": "none",
            "no_decision_memory": "decision_memory",
            "no_observed_outcome_reflection": "observed_outcome_reflection",
            "fixed_deterministic_portfolio": "harness_router",
        }[self.arm]
        return {
            "component": component,
            "prompt_count": self.prompt_count,
            "changed_prompt_count": self.changed_prompt_count,
            "removed_memory_count": self.removed_memory_count,
            "removed_reflection_count": self.removed_reflection_count,
            "provider_visible_intervention_activated": (self.changed_prompt_count > 0),
        }


def _build_context_wrapper(
    intervention: _ContextIntervention,
    decision_harness_module: ModuleType,
) -> Callable[..., tuple[HarnessEvidenceSnapshot, bool]]:
    original = cast(
        Callable[..., tuple[HarnessEvidenceSnapshot, bool]],
        decision_harness_module.__dict__["build_harness_evidence"],
    )

    def wrapped(
        job: models.Job,
        *,
        execution_events: object = (),
        verified_started_decision_ids: object = (),
        generation_plan_history: object = (),
    ) -> tuple[HarnessEvidenceSnapshot, bool]:
        snapshot, has_scored_evidence = original(
            job,
            execution_events=cast(Any, execution_events),
            verified_started_decision_ids=cast(
                Any,
                verified_started_decision_ids,
            ),
            generation_plan_history=cast(Any, generation_plan_history),
        )
        return intervention.apply(snapshot, has_scored_evidence)

    return wrapped


def _candidate_is_full_fidelity(candidate: dict[str, Any]) -> bool:
    metadata = candidate.get("optimizer_metadata")
    if not isinstance(metadata, dict):
        return True
    requested = metadata.get("requested_fidelity", metadata.get("fidelity", 1.0))
    effective = metadata.get(
        "effective_fidelity",
        metadata.get("fidelity", 1.0),
    )
    return (
        isinstance(requested, int | float)
        and not isinstance(requested, bool)
        and isinstance(effective, int | float)
        and not isinstance(effective, bool)
        and float(requested) >= 1.0 - 1e-12
        and float(effective) >= 1.0 - 1e-12
    )


def _result_metrics(outcome: dict[str, Any]) -> dict[str, Any]:
    candidates = [item for item in outcome["candidates"] if isinstance(item, dict)]
    optimizer_candidates = [item for item in candidates if item.get("source_type") == "optimizer"]
    feasible_optimizer_candidates = [
        item
        for item in optimizer_candidates
        if isinstance(item.get("aggregate"), dict) and item["aggregate"].get("feasible") is True
    ]
    baseline = next(
        (
            item
            for item in candidates
            if item.get("is_baseline") is True and isinstance(item.get("aggregate"), dict)
        ),
        None,
    )
    baseline_loss = baseline["aggregate"].get("scalar_loss") if isinstance(baseline, dict) else None
    target_loss = (
        float(baseline_loss) * (1.0 - HARNESS_COMPONENT_ABLATION_TARGET_RELATIVE_IMPROVEMENT)
        if isinstance(baseline_loss, int | float) and not isinstance(baseline_loss, bool)
        else None
    )
    target_generation: int | None = None
    if target_loss is not None:
        eligible = [
            int(item["generation_index"])
            for item in feasible_optimizer_candidates
            if _candidate_is_full_fidelity(item)
            and isinstance(item.get("aggregate"), dict)
            and isinstance(item["aggregate"].get("scalar_loss"), int | float)
            and not isinstance(item["aggregate"].get("scalar_loss"), bool)
            and float(item["aggregate"]["scalar_loss"]) <= target_loss
        ]
        target_generation = min(eligible, default=None)
    total_trials = int(outcome["budget"]["trial_count"])
    trials_to_target = (
        sum(
            int(item.get("trial_count") or 0)
            for item in candidates
            if int(item.get("generation_index") or 0) <= target_generation
        )
        if target_generation is not None
        else None
    )
    trial_rows = [item for item in outcome["trials"] if isinstance(item, dict)]
    terminal_failures = sum(item.get("status") in {"FAILED", "CANCELLED"} for item in trial_rows)
    recovered_trials = sum(
        item.get("status") == "COMPLETED"
        and isinstance(item.get("attempt_count"), int)
        and int(item["attempt_count"]) > 1
        for item in trial_rows
    )
    completeness = outcome["evidence_completeness"]["completeness_rate"]
    metrics = {
        "holdout_loss": outcome["holdout_loss"],
        "optimizer_candidate_count": len(optimizer_candidates),
        "feasible_optimizer_candidate_count": len(feasible_optimizer_candidates),
        "optimizer_feasible_rate": (
            len(feasible_optimizer_candidates) / len(optimizer_candidates)
            if optimizer_candidates
            else 0.0
        ),
        "baseline_training_loss": baseline_loss,
        "target_training_loss": target_loss,
        "target_reached": target_generation is not None,
        "target_generation": target_generation,
        "trials_to_target": trials_to_target,
        "right_censor_trials": (None if target_generation is not None else total_trials),
        "total_trials": total_trials,
        "completed_trials": int(outcome["budget"]["completed_trials"]),
        "terminal_failure_trials": terminal_failures,
        "recovered_trials": recovered_trials,
        "failure_rate": (terminal_failures / total_trials if total_trials else 0.0),
        "recovery_rate": (
            recovered_trials / (terminal_failures + recovered_trials)
            if terminal_failures + recovered_trials
            else None
        ),
        "evidence_completeness_rate": completeness,
    }
    return cast(dict[str, Any], _normalized_json(metrics))


def _decision_trace(outcome_trace: dict[str, Any]) -> list[dict[str, Any]]:
    executions = outcome_trace.get("execution_events")
    if not isinstance(executions, list):
        return []
    return [
        {
            "generation": index,
            "tool_id": row.get("tool_id"),
            "decision_source": row.get("decision_source"),
            "status": row.get("status"),
            "dispatched_candidates": row.get("dispatched_candidates"),
        }
        for index, row in enumerate(executions, start=1)
        if isinstance(row, dict)
    ]


def _decision_trace_from_outcome(
    outcome: dict[str, Any],
    *,
    arm: str,
) -> list[dict[str, Any]]:
    """Recompute the routed tool and dispatched count from persisted Candidates."""

    by_generation: dict[int, list[dict[str, Any]]] = {}
    for item in outcome.get("candidates", []):
        if not isinstance(item, dict) or item.get("source_type") != "optimizer":
            continue
        generation = item.get("generation_index")
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise ValueError("Harness component-ablation Candidate generation is invalid")
        by_generation.setdefault(generation, []).append(item)
    if sorted(by_generation) != list(range(1, len(by_generation) + 1)):
        raise ValueError("Harness component-ablation optimizer generations are not contiguous")
    trace: list[dict[str, Any]] = []
    for generation in sorted(by_generation):
        candidates = by_generation[generation]
        strategies = {
            metadata.get("strategy")
            for candidate in candidates
            if isinstance(
                metadata := candidate.get("optimizer_metadata"),
                dict,
            )
            and isinstance(metadata.get("strategy"), str)
        }
        if len(strategies) != 1:
            raise ValueError("Harness component-ablation generation strategy is ambiguous")
        trace.append(
            {
                "generation": generation,
                "tool_id": next(iter(strategies)),
                "decision_source": (
                    "fixed_policy" if arm == "fixed_deterministic_portfolio" else "model"
                ),
                "status": "dispatched",
                "dispatched_candidates": len(candidates),
            }
        )
    return trace


def _run_arm(
    seed_block: int,
    arm: HarnessComponentArm,
    *,
    max_iterations: int = HARNESS_COMPONENT_ABLATION_MAX_ITERATIONS,
    max_total_trials: int = HARNESS_COMPONENT_ABLATION_MAX_TOTAL_TRIALS,
) -> dict[str, Any]:
    if arm not in HARNESS_COMPONENT_ABLATION_ARMS:
        raise ValueError(f"unknown component-ablation arm: {arm}")
    client = None if arm == "fixed_deterministic_portfolio" else _ScriptedRouterClient()
    intervention = _ContextIntervention(arm)
    # Several repository tests deliberately evict and re-import every
    # ``app.*`` module to exercise isolated databases. Resolve the live module
    # at execution time so the intervention patches the exact function used
    # by JobManager rather than a stale collection-time module object.
    live_decision_harness = importlib.import_module("app.orchestration.decision_harness")
    wrapper = _build_context_wrapper(
        intervention,
        live_decision_harness,
    )
    previous_client = aggregation._llm_client_override
    with (
        _network_connect_guard() as network_measurement,
        _isolated_session_factory() as factory,
        patch.object(
            live_decision_harness,
            "build_harness_evidence",
            wrapper,
        ),
    ):
        with factory() as db:
            user = models.User(
                email=f"component-ablation-{seed_block}-{arm}@dronedream.invalid",
                display_name="Synthetic component ablation",
            )
            db.add(user)
            db.flush()
            job = job_services._create_job_from_config(
                db,
                user=user,
                req=_job_request(
                    seed_block,
                    arm=arm,
                    max_iterations=max_iterations,
                    max_total_trials=max_total_trials,
                ),
            )
            job_id = job.id
            db.commit()
        try:
            outcome, harness_trace = _drive_job(
                factory,
                job_id=job_id,
                client=cast(Any, client),
                max_steps=max_total_trials + 20,
            )
        finally:
            aggregation.set_llm_client_override(previous_client)
    if network_measurement.attempt_count:
        raise ValueError(
            "component-ablation arm attempted "
            f"{network_measurement.attempt_count} network connection(s)"
        )
    decision_trace = _decision_trace(harness_trace)
    if arm == "fixed_deterministic_portfolio":
        activation = {
            "component": "harness_router",
            "prompt_count": 0,
            "changed_prompt_count": 0,
            "removed_memory_count": 0,
            "removed_reflection_count": 0,
            "provider_visible_intervention_activated": True,
        }
        decision_trace = [
            {
                "generation": generation,
                "tool_id": "optimizer_portfolio",
                "decision_source": "fixed_policy",
                "status": "dispatched",
                "dispatched_candidates": sum(
                    item.get("generation_index") == generation
                    for item in outcome["candidates"]
                    if isinstance(item, dict) and item.get("source_type") == "optimizer"
                ),
            }
            for generation in sorted(
                {
                    int(item["generation_index"])
                    for item in outcome["candidates"]
                    if isinstance(item, dict) and item.get("source_type") == "optimizer"
                }
            )
        ]
    else:
        activation = intervention.summary()
    result_metrics = _result_metrics(outcome)
    tool_sequence = [row["tool_id"] for row in decision_trace]
    return {
        "arm": arm,
        "provider_calls": client.calls if client is not None else 0,
        "network_calls": network_measurement.attempt_count,
        "network_connect_guard_enforced": True,
        "real_credentials_used": False,
        "component_activation": activation,
        "scripted_router_trace": client.trace if client is not None else [],
        "decision_trace": decision_trace,
        "tool_sequence": tool_sequence,
        "result_metrics": result_metrics,
        "result_metrics_sha256": _sha256(result_metrics),
        "outcome_sha256": _sha256(outcome),
        "outcome": outcome,
    }


def _comparison_status(
    *,
    reference: dict[str, Any],
    comparison: dict[str, Any],
) -> str:
    activation = comparison["component_activation"]
    tool_changed = comparison["tool_sequence"] != reference["tool_sequence"]
    provider_input_changed = bool(activation["provider_visible_intervention_activated"])
    if not provider_input_changed and not tool_changed:
        return "inconclusive_intervention_not_activated"
    if all(
        comparison["result_metrics"].get(metric) == reference["result_metrics"].get(metric)
        for metric in _RESULT_METRICS
    ):
        return "no_observed_protocol_difference"
    return "observed_protocol_difference"


def _comparison_row(
    *,
    block_id: int,
    seed_block: int,
    reference: dict[str, Any],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    reference_metrics = reference["result_metrics"]
    comparison_metrics = comparison["result_metrics"]
    metric_matches = {
        metric: comparison_metrics.get(metric) == reference_metrics.get(metric)
        for metric in _RESULT_METRICS
    }
    return {
        "block_id": block_id,
        "seed_block": seed_block,
        "reference_arm": "full_aurora",
        "comparison_arm": comparison["arm"],
        "provider_visible_intervention_activated": comparison["component_activation"][
            "provider_visible_intervention_activated"
        ],
        "tool_sequence_changed": (comparison["tool_sequence"] != reference["tool_sequence"]),
        "reference_tool_sequence": reference["tool_sequence"],
        "comparison_tool_sequence": comparison["tool_sequence"],
        "result_status": _comparison_status(
            reference=reference,
            comparison=comparison,
        ),
        "all_preregistered_metrics_match": all(metric_matches.values()),
        "metric_matches": metric_matches,
        "holdout_loss_delta_from_full": (
            None
            if comparison_metrics["holdout_loss"] is None
            or reference_metrics["holdout_loss"] is None
            else float(comparison_metrics["holdout_loss"])
            - float(reference_metrics["holdout_loss"])
        ),
        "total_trials_delta_from_full": (
            int(comparison_metrics["total_trials"]) - int(reference_metrics["total_trials"])
        ),
    }


def _decision_receipt_memory_isolation_row(
    *,
    block_id: int,
    seed_block: int,
    no_reflection: dict[str, Any],
    no_memory: dict[str, Any],
) -> dict[str, Any]:
    """Isolate receipt-only memory after reflection has been removed in both arms."""

    tool_sequence_match = no_reflection["tool_sequence"] == no_memory["tool_sequence"]
    result_metrics_match = no_reflection["result_metrics"] == no_memory["result_metrics"]
    removed = no_memory["component_activation"]["removed_memory_count"] > 0
    status = (
        "inconclusive_component_not_decision_relevant_under_policy"
        if removed and tool_sequence_match and result_metrics_match
        else (
            "observed_protocol_difference" if removed else "inconclusive_intervention_not_activated"
        )
    )
    return {
        "block_id": block_id,
        "seed_block": seed_block,
        "component": "decision_receipt_memory_without_reflection",
        "reference_arm": "no_observed_outcome_reflection",
        "comparison_arm": "no_decision_memory",
        "provider_visible_intervention_activated": removed,
        "tool_sequence_match": tool_sequence_match,
        "result_metrics_match": result_metrics_match,
        "result_status": status,
        "interpretation": (
            "Both arms exclude observed outcomes. The comparison retains "
            "decision receipts only in the reference arm. Identical routed "
            "tools and outcomes leave the incremental contribution of "
            "receipt-only memory unresolved under this scripted policy."
        ),
    }


def build_harness_component_ablation_artifact() -> dict[str, Any]:
    """Run all frozen arms and return a self-verifying result artifact."""

    manifest = build_harness_component_ablation_manifest()
    block_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    component_isolation_rows: list[dict[str, Any]] = []
    for block_id, seed_block in enumerate(
        HARNESS_COMPONENT_ABLATION_SEED_BLOCKS,
        start=1,
    ):
        arms = [
            _run_arm(seed_block, cast(HarnessComponentArm, arm))
            for arm in HARNESS_COMPONENT_ABLATION_ARMS
        ]
        by_name = {str(arm["arm"]): arm for arm in arms}
        reference = by_name["full_aurora"]
        for arm_name in HARNESS_COMPONENT_ABLATION_ARMS[1:]:
            comparison_rows.append(
                _comparison_row(
                    block_id=block_id,
                    seed_block=seed_block,
                    reference=reference,
                    comparison=by_name[arm_name],
                )
            )
        component_isolation_rows.append(
            _decision_receipt_memory_isolation_row(
                block_id=block_id,
                seed_block=seed_block,
                no_reflection=by_name["no_observed_outcome_reflection"],
                no_memory=by_name["no_decision_memory"],
            )
        )
        block_rows.append(
            {
                "block_id": block_id,
                "seed_block": seed_block,
                "training_seeds": [
                    seed_block + 1,
                    seed_block + 2,
                    seed_block + 3,
                ],
                "holdout_seeds": [seed_block + 99],
                "arms": arms,
            }
        )
    status_counts = {
        status: sum(row["result_status"] == status for row in comparison_rows)
        for status in (
            "observed_protocol_difference",
            "no_observed_protocol_difference",
            "inconclusive_intervention_not_activated",
        )
    }
    unsigned: dict[str, Any] = {
        "schema_version": HARNESS_COMPONENT_ABLATION_SCHEMA_VERSION,
        "evidence_class": HARNESS_COMPONENT_ABLATION_EVIDENCE_CLASS,
        "claim_label": HARNESS_COMPONENT_ABLATION_LABEL,
        "claim_boundary": HARNESS_COMPONENT_ABLATION_CLAIM_BOUNDARY,
        "physical_fidelity": False,
        "simulator_backend": "mock",
        "live_model_calls": False,
        "network_calls": sum(
            int(arm["network_calls"]) for block in block_rows for arm in block["arms"]
        ),
        "real_credentials_used": False,
        "general_causal_claim_permitted": False,
        "llm_superiority_claim_permitted": False,
        "px4_or_flight_claim_permitted": False,
        "manifest_sha256": manifest["manifest_sha256"],
        "summary": {
            "seed_block_count": len(HARNESS_COMPONENT_ABLATION_SEED_BLOCKS),
            "arm_count": len(HARNESS_COMPONENT_ABLATION_ARMS),
            "arm_run_count": (
                len(HARNESS_COMPONENT_ABLATION_SEED_BLOCKS) * len(HARNESS_COMPONENT_ABLATION_ARMS)
            ),
            "total_persisted_trials": sum(
                int(arm["result_metrics"]["total_trials"])
                for block in block_rows
                for arm in block["arms"]
            ),
            "comparison_count": len(comparison_rows),
            "component_isolation_count": len(component_isolation_rows),
            "inconclusive_component_isolation_count": sum(
                row["result_status"].startswith("inconclusive_") for row in component_isolation_rows
            ),
            "interpretation_status_counts": status_counts,
            "all_network_calls_blocked": all(
                arm["network_calls"] == 0 and arm["network_connect_guard_enforced"] is True
                for block in block_rows
                for arm in block["arms"]
            ),
            "all_evidence_complete": all(
                arm["result_metrics"]["evidence_completeness_rate"] == 1.0
                for block in block_rows
                for arm in block["arms"]
            ),
        },
        "comparison_rows": comparison_rows,
        "component_isolation_rows": component_isolation_rows,
        "block_rows": block_rows,
    }
    return {
        **unsigned,
        "artifact_sha256": _sha256(unsigned),
    }


def _verify_arm(
    arm: object,
    *,
    expected_name: str,
    expected_prompt_count: int = HARNESS_COMPONENT_ABLATION_MAX_ITERATIONS,
) -> dict[str, Any]:
    if expected_prompt_count < 1:
        raise ValueError("Harness component-ablation prompt count is invalid")
    if not isinstance(arm, dict) or arm.get("arm") != expected_name:
        raise ValueError("Harness component-ablation arm order or identity drifted")
    outcome = arm.get("outcome")
    metrics = arm.get("result_metrics")
    if (
        not isinstance(outcome, dict)
        or not isinstance(metrics, dict)
        or arm.get("outcome_sha256") != _sha256(outcome)
        or arm.get("result_metrics_sha256") != _sha256(metrics)
        or metrics != _result_metrics(outcome)
        or arm.get("network_calls") != 0
        or arm.get("network_connect_guard_enforced") is not True
        or arm.get("real_credentials_used") is not False
    ):
        raise ValueError("Harness component-ablation arm integrity is invalid")
    expected_trace = _decision_trace_from_outcome(
        outcome,
        arm=expected_name,
    )
    expected_tools = [row["tool_id"] for row in expected_trace]
    if arm.get("decision_trace") != expected_trace or arm.get("tool_sequence") != expected_tools:
        raise ValueError("Harness component-ablation decision trace does not recompute")
    router_trace = arm.get("scripted_router_trace")
    provider_calls = arm.get("provider_calls")
    activation = arm.get("component_activation")
    if not isinstance(router_trace, list) or not isinstance(activation, dict):
        raise ValueError("Harness component-ablation intervention evidence is invalid")
    removed_context_count = sum(range(expected_prompt_count))
    changed_prompt_count = expected_prompt_count - 1
    expected_activations = {
        "full_aurora": {
            "component": "none",
            "prompt_count": expected_prompt_count,
            "changed_prompt_count": 0,
            "removed_memory_count": 0,
            "removed_reflection_count": 0,
            "provider_visible_intervention_activated": False,
        },
        "no_decision_memory": {
            "component": "decision_memory",
            "prompt_count": expected_prompt_count,
            "changed_prompt_count": changed_prompt_count,
            "removed_memory_count": removed_context_count,
            "removed_reflection_count": 0,
            "provider_visible_intervention_activated": True,
        },
        "no_observed_outcome_reflection": {
            "component": "observed_outcome_reflection",
            "prompt_count": expected_prompt_count,
            "changed_prompt_count": changed_prompt_count,
            "removed_memory_count": 0,
            "removed_reflection_count": removed_context_count,
            "provider_visible_intervention_activated": True,
        },
        "fixed_deterministic_portfolio": {
            "component": "harness_router",
            "prompt_count": 0,
            "changed_prompt_count": 0,
            "removed_memory_count": 0,
            "removed_reflection_count": 0,
            "provider_visible_intervention_activated": True,
        },
    }
    if activation != expected_activations[expected_name]:
        raise ValueError("Harness component-ablation intervention evidence does not recompute")
    if expected_name == "fixed_deterministic_portfolio":
        if provider_calls != 0 or router_trace:
            raise ValueError("Harness component-ablation fixed arm invoked a router")
        return arm
    if provider_calls != len(expected_trace) or len(router_trace) != len(expected_trace):
        raise ValueError("Harness component-ablation router call count does not recompute")
    for expected, routed in zip(expected_trace, router_trace, strict=True):
        if (
            not isinstance(routed, dict)
            or routed.get("generation") != expected["generation"]
            or routed.get("selected_tool") != expected["tool_id"]
            or not isinstance(routed.get("allowed_tools"), list)
            or expected["tool_id"] not in routed["allowed_tools"]
        ):
            raise ValueError("Harness component-ablation router trace does not recompute")
    expected_memory_counts = {
        "full_aurora": [(index, index) for index in range(expected_prompt_count)],
        "no_decision_memory": [(0, 0)] * expected_prompt_count,
        "no_observed_outcome_reflection": [
            (index, 0) for index in range(expected_prompt_count)
        ],
    }[expected_name]
    actual_memory_counts = [
        (
            routed.get("decision_memory_count"),
            routed.get("verified_reflection_count"),
        )
        for routed in router_trace
    ]
    if actual_memory_counts != expected_memory_counts:
        raise ValueError("Harness component-ablation router memory trace does not recompute")
    return arm


def verify_harness_component_ablation_artifact(
    payload: object,
    *,
    manifest: object | None = None,
) -> dict[str, Any]:
    """Independently recompute result hashes, metrics, comparisons, and summary."""

    if not isinstance(payload, dict):
        raise ValueError("Harness component-ablation artifact must be an object")
    artifact = dict(payload)
    declared_hash = artifact.pop("artifact_sha256", None)
    if not isinstance(declared_hash, str) or len(declared_hash) != 64:
        raise ValueError("Harness component-ablation artifact hash is invalid")
    if declared_hash != _sha256(artifact):
        raise ValueError("Harness component-ablation artifact hash does not recompute")
    if (
        artifact.get("schema_version") != HARNESS_COMPONENT_ABLATION_SCHEMA_VERSION
        or artifact.get("evidence_class") != HARNESS_COMPONENT_ABLATION_EVIDENCE_CLASS
        or artifact.get("claim_label") != HARNESS_COMPONENT_ABLATION_LABEL
        or artifact.get("claim_boundary") != HARNESS_COMPONENT_ABLATION_CLAIM_BOUNDARY
        or artifact.get("physical_fidelity") is not False
        or artifact.get("simulator_backend") != "mock"
        or artifact.get("live_model_calls") is not False
        or artifact.get("network_calls") != 0
        or artifact.get("real_credentials_used") is not False
        or artifact.get("general_causal_claim_permitted") is not False
        or artifact.get("llm_superiority_claim_permitted") is not False
        or artifact.get("px4_or_flight_claim_permitted") is not False
    ):
        raise ValueError("Harness component-ablation claim boundary is invalid")
    manifest_payload = (
        build_harness_component_ablation_manifest()
        if manifest is None
        else verify_harness_component_ablation_manifest(manifest)
    )
    if artifact.get("manifest_sha256") != manifest_payload["manifest_sha256"]:
        raise ValueError("Harness component-ablation manifest binding is invalid")
    blocks = artifact.get("block_rows")
    if not isinstance(blocks, list) or len(blocks) != len(HARNESS_COMPONENT_ABLATION_SEED_BLOCKS):
        raise ValueError("Harness component-ablation block rows are invalid")
    recomputed_comparisons: list[dict[str, Any]] = []
    recomputed_isolations: list[dict[str, Any]] = []
    for block_id, (block, seed_block) in enumerate(
        zip(
            blocks,
            HARNESS_COMPONENT_ABLATION_SEED_BLOCKS,
            strict=True,
        ),
        start=1,
    ):
        if (
            not isinstance(block, dict)
            or block.get("block_id") != block_id
            or block.get("seed_block") != seed_block
            or block.get("training_seeds") != [seed_block + 1, seed_block + 2, seed_block + 3]
            or block.get("holdout_seeds") != [seed_block + 99]
        ):
            raise ValueError("Harness component-ablation seed block drifted")
        raw_arms = block.get("arms")
        if not isinstance(raw_arms, list) or len(raw_arms) != len(HARNESS_COMPONENT_ABLATION_ARMS):
            raise ValueError("Harness component-ablation arms are invalid")
        arms = [
            _verify_arm(arm, expected_name=name)
            for arm, name in zip(
                raw_arms,
                HARNESS_COMPONENT_ABLATION_ARMS,
                strict=True,
            )
        ]
        by_name = {str(arm["arm"]): arm for arm in arms}
        reference = by_name["full_aurora"]
        for arm_name in HARNESS_COMPONENT_ABLATION_ARMS[1:]:
            recomputed_comparisons.append(
                _comparison_row(
                    block_id=block_id,
                    seed_block=seed_block,
                    reference=reference,
                    comparison=by_name[arm_name],
                )
            )
        recomputed_isolations.append(
            _decision_receipt_memory_isolation_row(
                block_id=block_id,
                seed_block=seed_block,
                no_reflection=by_name["no_observed_outcome_reflection"],
                no_memory=by_name["no_decision_memory"],
            )
        )
    if artifact.get("comparison_rows") != recomputed_comparisons:
        raise ValueError("Harness component-ablation comparisons do not recompute")
    if artifact.get("component_isolation_rows") != recomputed_isolations:
        raise ValueError("Harness component-ablation isolation rows do not recompute")
    status_counts = {
        status: sum(row["result_status"] == status for row in recomputed_comparisons)
        for status in (
            "observed_protocol_difference",
            "no_observed_protocol_difference",
            "inconclusive_intervention_not_activated",
        )
    }
    expected_summary = {
        "seed_block_count": len(HARNESS_COMPONENT_ABLATION_SEED_BLOCKS),
        "arm_count": len(HARNESS_COMPONENT_ABLATION_ARMS),
        "arm_run_count": (
            len(HARNESS_COMPONENT_ABLATION_SEED_BLOCKS) * len(HARNESS_COMPONENT_ABLATION_ARMS)
        ),
        "total_persisted_trials": sum(
            int(arm["result_metrics"]["total_trials"]) for block in blocks for arm in block["arms"]
        ),
        "comparison_count": len(recomputed_comparisons),
        "component_isolation_count": len(recomputed_isolations),
        "inconclusive_component_isolation_count": sum(
            row["result_status"].startswith("inconclusive_") for row in recomputed_isolations
        ),
        "interpretation_status_counts": status_counts,
        "all_network_calls_blocked": True,
        "all_evidence_complete": all(
            arm["result_metrics"]["evidence_completeness_rate"] == 1.0
            for block in blocks
            for arm in block["arms"]
        ),
    }
    if artifact.get("summary") != expected_summary:
        raise ValueError("Harness component-ablation summary does not recompute")
    return payload


__all__ = [
    "HARNESS_COMPONENT_ABLATION_ARMS",
    "HARNESS_COMPONENT_ABLATION_CLAIM_BOUNDARY",
    "HARNESS_COMPONENT_ABLATION_EVIDENCE_CLASS",
    "HARNESS_COMPONENT_ABLATION_LABEL",
    "HARNESS_COMPONENT_ABLATION_MANIFEST_SCHEMA_VERSION",
    "HARNESS_COMPONENT_ABLATION_SCHEMA_VERSION",
    "HARNESS_COMPONENT_ABLATION_SEED_BLOCKS",
    "build_harness_component_ablation_artifact",
    "build_harness_component_ablation_manifest",
    "verify_harness_component_ablation_artifact",
    "verify_harness_component_ablation_manifest",
]
