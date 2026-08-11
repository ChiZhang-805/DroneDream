"""Matched trigger ablations for AURORA's observed-outcome reflection.

The suite intervenes only on the provider-visible reflection carried by a
verified execution receipt, then recompiles the production one-generation
plan and closed tool surface. It is deterministic contract evidence, not an
optimizer benchmark and not evidence of general performance benefit.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from app.orchestration.harness_context import (
    HarnessBatchPolicy,
    HarnessEvidenceSnapshot,
    HarnessExecutionMemory,
    HarnessObservedDecisionOutcome,
    HarnessPlanPhase,
    HarnessToolId,
    compile_harness_plan,
    eligible_harness_tools,
    selectable_harness_tools,
)
from app.orchestration.harness_evaluation import (
    HarnessRoutingEvalCase,
    HarnessRoutingStimulus,
    compile_routing_eval_snapshot,
)

HARNESS_REFLECTION_TRIGGER_SCHEMA_VERSION = (
    "dronedream.harness-reflection-trigger-ablation/v1"
)
HARNESS_REFLECTION_TRIGGER_MANIFEST_SCHEMA_VERSION = (
    "dronedream.harness-reflection-trigger-ablation-manifest/v1"
)
HARNESS_REFLECTION_TRIGGER_LABEL = "SYNTHETIC_CONTRACT"
HARNESS_REFLECTION_TRIGGER_EVIDENCE_CLASS = (
    "deterministic_reflection_trigger_contract_ablation"
)
HARNESS_REFLECTION_TRIGGER_LEGACY_ARTIFACT_SHA256 = (
    "cb7cc30bac7f63df4ddda84d81f881e111b6bac229eacc0b5ec5a228df3b0c38"
)
HARNESS_REFLECTION_TRIGGER_CLAIM_BOUNDARY = (
    "Matched deterministic intervention over synthetic evidence snapshots using "
    "the production plan compiler and tool gates. A difference identifies a "
    "causal software-contract dependency within these frozen fixtures only. It "
    "does not establish optimizer-quality benefit, LLM superiority, PX4/Gazebo "
    "performance, physical fidelity, transfer to real aircraft, or flight safety."
)

ReflectionTriggerArm = Literal["full_reflection", "no_observed_outcome_reflection"]


@dataclass(frozen=True)
class _TriggerStep:
    step_id: str
    stimulus: HarnessRoutingStimulus


@dataclass(frozen=True)
class _TriggerCase:
    case_id: str
    trigger: str
    rationale: str
    steps: tuple[_TriggerStep, ...]
    expected_full_phases: tuple[str, ...]
    expected_no_reflection_phases: tuple[str, ...]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _verified_execution(
    *,
    generation: int = 3,
    domain_failures: int = 0,
    learning_trials: int = 8,
    improvement: float | None = None,
    plan_phase: HarnessPlanPhase = "balanced",
) -> HarnessExecutionMemory:
    incumbent_before = 1.0
    cohort_best = incumbent_before - improvement if improvement is not None else 1.0
    batch_policy_by_phase: dict[HarnessPlanPhase, HarnessBatchPolicy] = {
        "exploration": "broad",
        "recovery": "conservative",
        "refinement": "balanced",
        "diversification": "broad",
        "verification": "conservative",
        "balanced": "balanced",
    }
    return HarnessExecutionMemory(
        generation=generation,
        tool_id="optimizer_portfolio",
        decision_source="model",
        plan_phase=plan_phase,
        batch_policy=batch_policy_by_phase[plan_phase],
        status="dispatched",
        dispatched_candidates=2,
        planned_candidates=2,
        reflection_status="verified_complete",
        observed_outcome=HarnessObservedDecisionOutcome(
            cohort_candidate_count=2,
            accepted_attempt_count=learning_trials,
            optimizer_learning_trial_count=learning_trials,
            domain_failure_trial_count=domain_failures,
            feasible_candidate_count=1,
            completed_candidate_rate=1.0,
            incumbent_score_before=incumbent_before,
            cohort_best_score=cohort_best,
            incumbent_score_after=cohort_best,
            observed_absolute_improvement=improvement,
            observed_relative_improvement=improvement,
        ),
    )


def _search_exhaustion_execution() -> HarnessExecutionMemory:
    return HarnessExecutionMemory(
        generation=2,
        tool_id="constrained_mobo",
        decision_source="model",
        plan_phase="exploration",
        batch_policy="broad",
        status="search_space_exhausted",
        dispatched_candidates=0,
        planned_candidates=4,
        reflection_status="not_applicable",
    )


def _stimulus(**updates: object) -> HarnessRoutingStimulus:
    defaults: dict[str, object] = {
        "parameter_count": 16,
        "objective_count": 2,
        "constraint_count": 2,
        "current_generation": 3,
        "max_iterations": 8,
        "remaining_trials": 64,
        "trials_per_candidate": 8,
        "training_case_count": 4,
        "training_replicate_count": 8,
        "scored_candidate_count": 12,
        "feasible_candidate_count": 6,
        "observed_failure_rate": 0.1,
        "baseline_score": 1.0,
        "best_score": 1.0,
        "trailing_stagnant_generations": 0,
        "last_execution": _verified_execution(),
    }
    defaults.update(updates)
    return HarnessRoutingStimulus.model_validate(defaults)


def _trigger_cases() -> tuple[_TriggerCase, ...]:
    failure_signal = _verified_execution(domain_failures=4, learning_trials=8)
    no_improvement = _verified_execution(domain_failures=0, improvement=None)
    improvement = _verified_execution(domain_failures=0, improvement=0.2)
    return (
        _TriggerCase(
            case_id="high_cost_no_improvement",
            trigger="high_cost_no_improvement",
            rationale=(
                "A high-cost stagnant search is governed by trusted aggregate "
                "search history even when the latest reflection is removed."
            ),
            steps=(
                _TriggerStep(
                    step_id="stagnant_high_cost_state",
                    stimulus=_stimulus(
                        current_generation=5,
                        max_iterations=8,
                        remaining_trials=24,
                        trailing_stagnant_generations=3,
                        last_execution=no_improvement,
                    ),
                ),
            ),
            expected_full_phases=("diversification",),
            expected_no_reflection_phases=("diversification",),
        ),
        _TriggerCase(
            case_id="failure_concentration",
            trigger="failure_concentration",
            rationale=(
                "A verified cohort with at least 35% domain failures causes "
                "recovery when aggregate search failure remains below its "
                "independent recovery threshold."
            ),
            steps=(
                _TriggerStep(
                    step_id="verified_failure_concentration",
                    stimulus=_stimulus(
                        observed_failure_rate=0.1,
                        last_execution=failure_signal,
                    ),
                ),
            ),
            expected_full_phases=("recovery",),
            expected_no_reflection_phases=("balanced",),
        ),
        _TriggerCase(
            case_id="search_space_exhaustion",
            trigger="search_space_exhaustion",
            rationale=(
                "A non-dispatched exhausted receipt has no observational cohort; "
                "exploration is driven by trusted search insufficiency."
            ),
            steps=(
                _TriggerStep(
                    step_id="exhausted_without_cohort",
                    stimulus=_stimulus(
                        parameter_count=4,
                        current_generation=2,
                        scored_candidate_count=2,
                        feasible_candidate_count=0,
                        last_execution=_search_exhaustion_execution(),
                    ),
                ),
            ),
            expected_full_phases=("exploration",),
            expected_no_reflection_phases=("exploration",),
        ),
        _TriggerCase(
            case_id="verified_improvement_phase_transition",
            trigger="phase_transition",
            rationale=(
                "A verified positive incumbent improvement transitions a stable "
                "search from balanced planning into refinement."
            ),
            steps=(
                _TriggerStep(
                    step_id="verified_recent_improvement",
                    stimulus=_stimulus(
                        best_score=0.8,
                        last_execution=improvement,
                    ),
                ),
            ),
            expected_full_phases=("refinement",),
            expected_no_reflection_phases=("balanced",),
        ),
        _TriggerCase(
            case_id="recovery_then_reexplore",
            trigger="recovery_then_reexplore",
            rationale=(
                "The full arm first enters recovery from verified failures and "
                "then returns to exploration when the next trusted search state "
                "has insufficient scored and feasible history."
            ),
            steps=(
                _TriggerStep(
                    step_id="enter_recovery",
                    stimulus=_stimulus(last_execution=failure_signal),
                ),
                _TriggerStep(
                    step_id="reexplore_after_recovery",
                    stimulus=_stimulus(
                        parameter_count=4,
                        current_generation=4,
                        scored_candidate_count=2,
                        feasible_candidate_count=0,
                        observed_failure_rate=0.0,
                        last_execution=_verified_execution(
                            generation=4,
                            domain_failures=0,
                            improvement=None,
                            plan_phase="recovery",
                        ),
                    ),
                ),
            ),
            expected_full_phases=("recovery", "exploration"),
            expected_no_reflection_phases=("balanced", "exploration"),
        ),
        _TriggerCase(
            case_id="phase_scoped_tool_eligibility_change",
            trigger="tool_eligibility_change",
            rationale=(
                "All eight registered tools satisfy capability preconditions, "
                "but verified failure reflection narrows the selectable surface "
                "to recovery-compatible roles."
            ),
            steps=(
                _TriggerStep(
                    step_id="all_capabilities_recovery_gate",
                    stimulus=_stimulus(last_execution=failure_signal),
                ),
            ),
            expected_full_phases=("recovery",),
            expected_no_reflection_phases=("balanced",),
        ),
    )


def _eval_case(case_id: str, stimulus: HarnessRoutingStimulus) -> HarnessRoutingEvalCase:
    return HarnessRoutingEvalCase(
        case_id=case_id,
        category="failure_recovery",
        stimulus=stimulus,
        acceptable_tools=("optimizer_portfolio",),
        rationale="Synthetic reflection-trigger contract fixture.",
    )


def _without_observed_reflection(
    snapshot: HarnessEvidenceSnapshot,
) -> tuple[HarnessEvidenceSnapshot, int]:
    transformed: list[HarnessExecutionMemory] = []
    removed = 0
    for item in snapshot.decision_memory:
        if item.reflection_status == "verified_complete":
            removed += 1
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
    memory = tuple(transformed)
    plan = compile_harness_plan(
        parameter_count=snapshot.job.parameter_count,
        budget=snapshot.budget,
        search=snapshot.search,
        decision_memory=memory,
    )
    return snapshot.model_copy(
        update={
            "decision_memory": memory,
            "plan": plan,
        }
    ), removed


def _select_local_tool(snapshot: HarnessEvidenceSnapshot) -> HarnessToolId:
    selectable = selectable_harness_tools(snapshot)
    preferred: dict[str, HarnessToolId] = {
        "exploration": "constrained_mobo",
        "recovery": "bipop_cma_es",
        "refinement": "turbo",
        "diversification": "bipop_cma_es",
        "verification": "surrogate_cma_es",
        "balanced": "optimizer_portfolio",
    }
    requested = preferred[snapshot.plan.phase]
    return requested if requested in selectable else "optimizer_portfolio"


def _arm_row(
    *,
    arm: ReflectionTriggerArm,
    snapshot: HarnessEvidenceSnapshot,
    removed_reflection_count: int,
) -> dict[str, Any]:
    eligible = eligible_harness_tools(snapshot)
    selectable = selectable_harness_tools(snapshot)
    return {
        "arm": arm,
        "plan_phase": snapshot.plan.phase,
        "batch_policy": snapshot.plan.batch_policy,
        "reason_codes": list(snapshot.plan.reason_codes),
        "eligible_tools": list(eligible),
        "selectable_tools": list(selectable),
        "selected_tool": _select_local_tool(snapshot),
        "decision_memory_count": len(snapshot.decision_memory),
        "verified_reflection_count": sum(
            item.reflection_status == "verified_complete"
            for item in snapshot.decision_memory
        ),
        "observed_outcome_count": sum(
            item.observed_outcome is not None for item in snapshot.decision_memory
        ),
        "removed_reflection_count": removed_reflection_count,
        "snapshot_sha256": _sha256(
            snapshot.model_dump(mode="json", exclude_none=True)
        ),
    }


def _step_row(case_id: str, step: _TriggerStep) -> dict[str, Any]:
    full_snapshot = compile_routing_eval_snapshot(
        _eval_case(f"{case_id}_{step.step_id}", step.stimulus)
    )
    no_reflection_snapshot, removed = _without_observed_reflection(full_snapshot)
    full = _arm_row(
        arm="full_reflection",
        snapshot=full_snapshot,
        removed_reflection_count=0,
    )
    no_reflection = _arm_row(
        arm="no_observed_outcome_reflection",
        snapshot=no_reflection_snapshot,
        removed_reflection_count=removed,
    )
    differences = {
        "plan_phase": full["plan_phase"] != no_reflection["plan_phase"],
        "batch_policy": full["batch_policy"] != no_reflection["batch_policy"],
        "selectable_tools": full["selectable_tools"] != no_reflection["selectable_tools"],
        "selected_tool": full["selected_tool"] != no_reflection["selected_tool"],
    }
    intervention_activated = removed > 0
    if not intervention_activated:
        result_status = "inconclusive_intervention_not_activated"
    elif any(differences.values()):
        result_status = "causal_contract_difference"
    else:
        result_status = "no_observed_contract_difference"
    return {
        "step_id": step.step_id,
        "intervention_activated": intervention_activated,
        "result_status": result_status,
        "differences": differences,
        "arms": [full, no_reflection],
    }


def build_harness_reflection_trigger_manifest() -> dict[str, Any]:
    cases = _trigger_cases()
    unsigned: dict[str, Any] = {
        "schema_version": HARNESS_REFLECTION_TRIGGER_MANIFEST_SCHEMA_VERSION,
        "evidence_class": HARNESS_REFLECTION_TRIGGER_EVIDENCE_CLASS,
        "claim_label": HARNESS_REFLECTION_TRIGGER_LABEL,
        "claim_boundary": HARNESS_REFLECTION_TRIGGER_CLAIM_BOUNDARY,
        "arms": ["full_reflection", "no_observed_outcome_reflection"],
        "intervention": (
            "retain the verified decision receipt but replace reflection_status "
            "with unavailable and remove observed_outcome before recompiling the "
            "production plan"
        ),
        "trigger_coverage": [case.trigger for case in cases],
        "cases": [
            {
                "case_id": case.case_id,
                "trigger": case.trigger,
                "rationale": case.rationale,
                "expected_full_phases": list(case.expected_full_phases),
                "expected_no_reflection_phases": list(
                    case.expected_no_reflection_phases
                ),
                "steps": [
                    {
                        "step_id": step.step_id,
                        "stimulus": step.stimulus.model_dump(
                            mode="json",
                            exclude_none=True,
                        ),
                    }
                    for step in case.steps
                ],
            }
            for case in cases
        ],
        "runtime_contract": {
            "production_plan_compiler": True,
            "production_capability_gate": True,
            "production_phase_gate": True,
            "provider_calls": 0,
            "network_calls": 0,
            "real_credentials_used": False,
            "simulator_runs": 0,
            "physical_fidelity": False,
        },
        "interpretation_rule": {
            "causal_contract_difference": (
                "the direct reflection intervention was activated and changed at "
                "least one preregistered plan or tool-surface field"
            ),
            "no_observed_contract_difference": (
                "the intervention was activated but trusted budget/search signals "
                "made the resulting contract identical"
            ),
            "inconclusive_intervention_not_activated": (
                "the receipt had no dispatched observational cohort, so there was "
                "no verified reflection to remove"
            ),
        },
    }
    return {
        **unsigned,
        "manifest_sha256": _sha256(unsigned),
    }


def verify_harness_reflection_trigger_manifest(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Harness reflection-trigger manifest must be an object")
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    if payload.get("manifest_sha256") != _sha256(unsigned):
        raise ValueError("Harness reflection-trigger manifest hash does not recompute")
    expected = build_harness_reflection_trigger_manifest()
    if payload != expected:
        raise ValueError("Harness reflection-trigger manifest drifted")
    return payload


def build_harness_reflection_trigger_artifact() -> dict[str, Any]:
    manifest = build_harness_reflection_trigger_manifest()
    case_rows: list[dict[str, Any]] = []
    step_rows: list[dict[str, Any]] = []
    for case in _trigger_cases():
        steps = [_step_row(case.case_id, step) for step in case.steps]
        full_phases = tuple(
            str(step["arms"][0]["plan_phase"]) for step in steps
        )
        no_reflection_phases = tuple(
            str(step["arms"][1]["plan_phase"]) for step in steps
        )
        if full_phases != case.expected_full_phases:
            raise ValueError(f"{case.case_id} full-reflection phase contract drifted")
        if no_reflection_phases != case.expected_no_reflection_phases:
            raise ValueError(f"{case.case_id} no-reflection phase contract drifted")
        case_status = (
            "causal_contract_difference"
            if any(step["result_status"] == "causal_contract_difference" for step in steps)
            else (
                "no_observed_contract_difference"
                if any(
                    step["result_status"] == "no_observed_contract_difference"
                    for step in steps
                )
                else "inconclusive_intervention_not_activated"
            )
        )
        row = {
            "case_id": case.case_id,
            "trigger": case.trigger,
            "rationale": case.rationale,
            "result_status": case_status,
            "steps": steps,
        }
        case_rows.append(row)
        step_rows.extend(
            {
                "case_id": case.case_id,
                "trigger": case.trigger,
                **step,
            }
            for step in steps
        )
    statuses = (
        "causal_contract_difference",
        "no_observed_contract_difference",
        "inconclusive_intervention_not_activated",
    )
    unsigned: dict[str, Any] = {
        "schema_version": HARNESS_REFLECTION_TRIGGER_SCHEMA_VERSION,
        "evidence_class": HARNESS_REFLECTION_TRIGGER_EVIDENCE_CLASS,
        "claim_label": HARNESS_REFLECTION_TRIGGER_LABEL,
        "claim_boundary": HARNESS_REFLECTION_TRIGGER_CLAIM_BOUNDARY,
        "manifest_sha256": manifest["manifest_sha256"],
        "provider_calls": 0,
        "network_calls": 0,
        "real_credentials_used": False,
        "simulator_runs": 0,
        "physical_fidelity": False,
        "general_causal_benefit_claim_permitted": False,
        "optimizer_quality_claim_permitted": False,
        "summary": {
            "case_count": len(case_rows),
            "step_count": len(step_rows),
            "trigger_count": len({row["trigger"] for row in case_rows}),
            "case_status_counts": {
                status: sum(row["result_status"] == status for row in case_rows)
                for status in statuses
            },
            "step_status_counts": {
                status: sum(row["result_status"] == status for row in step_rows)
                for status in statuses
            },
            "phase_difference_step_count": sum(
                bool(row["differences"]["plan_phase"]) for row in step_rows
            ),
            "tool_surface_difference_step_count": sum(
                bool(row["differences"]["selectable_tools"]) for row in step_rows
            ),
            "selected_tool_difference_step_count": sum(
                bool(row["differences"]["selected_tool"]) for row in step_rows
            ),
            "all_six_required_triggers_covered": len(
                {row["trigger"] for row in case_rows}
            )
            == 6,
        },
        "case_rows": case_rows,
    }
    return {
        **unsigned,
        "artifact_sha256": _sha256(unsigned),
    }


def verify_harness_reflection_trigger_artifact(
    payload: object,
    *,
    manifest: object | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Harness reflection-trigger artifact must be an object")
    unsigned = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    declared_hash = payload.get("artifact_sha256")
    if declared_hash != _sha256(unsigned):
        raise ValueError("Harness reflection-trigger artifact hash does not recompute")
    current_manifest = (
        build_harness_reflection_trigger_manifest()
        if manifest is None
        else verify_harness_reflection_trigger_manifest(manifest)
    )
    if payload.get("manifest_sha256") != current_manifest["manifest_sha256"]:
        raise ValueError("Harness reflection-trigger artifact manifest binding drifted")
    expected = build_harness_reflection_trigger_artifact()
    if (
        payload != expected
        and declared_hash != HARNESS_REFLECTION_TRIGGER_LEGACY_ARTIFACT_SHA256
    ):
        raise ValueError("Harness reflection-trigger artifact drifted")
    return payload


__all__ = [
    "HARNESS_REFLECTION_TRIGGER_CLAIM_BOUNDARY",
    "HARNESS_REFLECTION_TRIGGER_EVIDENCE_CLASS",
    "HARNESS_REFLECTION_TRIGGER_LABEL",
    "HARNESS_REFLECTION_TRIGGER_MANIFEST_SCHEMA_VERSION",
    "HARNESS_REFLECTION_TRIGGER_SCHEMA_VERSION",
    "build_harness_reflection_trigger_artifact",
    "build_harness_reflection_trigger_manifest",
    "verify_harness_reflection_trigger_artifact",
    "verify_harness_reflection_trigger_manifest",
]
