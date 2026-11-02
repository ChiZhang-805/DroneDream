"""Fixed-budget offline ablation for the bounded cognitive-turn policy.

The production adaptive trigger is exercised over frozen, provider-safe
evidence snapshots.  Qualification outcomes are deliberately scripted fixtures
so this module can test accounting, stopping and trigger precision without a
network provider or simulator.  It is not optimizer-performance evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from statistics import median
from types import SimpleNamespace
from typing import Any, Literal, cast

from app import models
from app.orchestration.cognitive_budget import (
    COGNITIVE_POLICY_VERSION,
    COGNITIVE_TRIGGER_POLICY_VERSION,
    evaluate_adaptive_triggers,
)
from app.orchestration.harness_context import (
    HarnessExecutionMemory,
    HarnessObservedDecisionOutcome,
)
from app.orchestration.harness_evaluation import (
    HarnessEvalCategory,
    HarnessRoutingEvalCase,
    HarnessRoutingStimulus,
    compile_routing_eval_snapshot,
)

COGNITIVE_ABLATION_SCHEMA_VERSION = "dronedream.cognitive-budget-ablation/v1"
COGNITIVE_ABLATION_MANIFEST_SCHEMA_VERSION = (
    "dronedream.cognitive-budget-ablation-manifest/v1"
)
COGNITIVE_ABLATION_LABEL = "SYNTHETIC_FIXED_BUDGET"
COGNITIVE_ABLATION_CLAIM_BOUNDARY = (
    "Deterministic offline state-machine evidence over frozen scripted outcomes. "
    "It exercises the production adaptive trigger and equal maximum simulation, "
    "trial, scenario, seed, model-fixture and tool-version budgets across arms. "
    "It does not call a provider or simulator and cannot establish optimizer "
    "quality, model superiority, PX4/Gazebo performance, physical fidelity, "
    "transfer to aircraft, flight safety, or a global optimum."
)

ArmName = Literal["one_turn", "fixed_two_turn", "adaptive_two_to_four_turn"]
ARMS: tuple[ArmName, ...] = (
    "one_turn",
    "fixed_two_turn",
    "adaptive_two_to_four_turn",
)
GENERATION_CAP = 4
TRIALS_PER_GENERATION = 6
TRIAL_CAP = GENERATION_CAP * TRIALS_PER_GENERATION
SIMULATION_CAP = TRIAL_CAP
SIMULATION_WALL_MS = 7_000
PROVIDER_TURN_WALL_MS = 1_500
MODEL_FIXTURE = "sequence-provider-fixture-v1"
TOOL_FIXTURE = "bounded-local-tool-fixture-v1"
SCENARIO_FIXTURE = "cognitive-trigger-scenarios-v1"
SEEDS = (2026080401, 2026080402, 2026080403)


@dataclass(frozen=True)
class _Case:
    case_id: str
    category: HarnessEvalCategory
    stimulus: HarnessRoutingStimulus
    expected_optional_turn: bool
    qualification_generation: dict[ArmName, int | None]
    tool_direction_conflict: bool = False
    hard_boundary_candidate: bool = False
    cooldown_reasons: tuple[str, ...] = ()


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


def _observed_execution(
    *,
    cohort_best_score: float = 1.0,
    domain_failures: int = 0,
) -> HarnessExecutionMemory:
    incumbent = 1.0
    improved = max(0.0, incumbent - cohort_best_score)
    return HarnessExecutionMemory(
        generation=2,
        tool_id="optimizer_portfolio",
        decision_source="model",
        plan_phase="balanced",
        batch_policy="balanced",
        status="dispatched",
        dispatched_candidates=2,
        planned_candidates=2,
        reflection_status="verified_complete",
        observed_outcome=HarnessObservedDecisionOutcome(
            cohort_candidate_count=2,
            accepted_attempt_count=4,
            optimizer_learning_trial_count=4,
            domain_failure_trial_count=domain_failures,
            feasible_candidate_count=1,
            completed_candidate_rate=1.0,
            incumbent_score_before=incumbent,
            cohort_best_score=cohort_best_score,
            incumbent_score_after=min(incumbent, cohort_best_score),
            observed_absolute_improvement=improved if improved > 0.0 else None,
            observed_relative_improvement=improved if improved > 0.0 else None,
        ),
    )


def _stimulus(**updates: object) -> HarnessRoutingStimulus:
    defaults: dict[str, object] = {
        "parameter_count": 12,
        "objective_count": 3,
        "constraint_count": 3,
        "current_generation": 2,
        "max_iterations": GENERATION_CAP,
        "remaining_trials": 12,
        "trials_per_candidate": 3,
        "training_case_count": 3,
        "training_replicate_count": 9,
        "scored_candidate_count": 4,
        "feasible_candidate_count": 2,
        "observed_failure_rate": 0.0,
        "baseline_score": 1.0,
        "best_score": 0.85,
        "trailing_stagnant_generations": 0,
    }
    defaults.update(updates)
    return HarnessRoutingStimulus.model_validate(defaults)


def _cases() -> tuple[_Case, ...]:
    return (
        _Case(
            case_id="direct_first_turn_stop",
            category="local_progress",
            stimulus=_stimulus(current_generation=1, remaining_trials=18),
            expected_optional_turn=False,
            qualification_generation={
                "one_turn": 1,
                "fixed_two_turn": 1,
                "adaptive_two_to_four_turn": 1,
            },
        ),
        _Case(
            case_id="steady_progress_no_extra_reasoning",
            category="local_progress",
            stimulus=_stimulus(),
            expected_optional_turn=False,
            qualification_generation={
                "one_turn": 2,
                "fixed_two_turn": 2,
                "adaptive_two_to_four_turn": 2,
            },
        ),
        _Case(
            case_id="trailing_stagnation_diagnosis",
            category="stagnation",
            stimulus=_stimulus(trailing_stagnant_generations=2, best_score=1.0),
            expected_optional_turn=True,
            qualification_generation={
                "one_turn": None,
                "fixed_two_turn": 4,
                "adaptive_two_to_four_turn": 3,
            },
        ),
        _Case(
            case_id="conflicting_tool_directions",
            category="mixed_tool_history",
            stimulus=_stimulus(),
            expected_optional_turn=True,
            tool_direction_conflict=True,
            qualification_generation={
                "one_turn": 4,
                "fixed_two_turn": 3,
                "adaptive_two_to_four_turn": 2,
            },
        ),
        _Case(
            case_id="prediction_outcome_mismatch",
            category="failure_recovery",
            stimulus=_stimulus(last_execution=_observed_execution(cohort_best_score=1.25)),
            expected_optional_turn=True,
            qualification_generation={
                "one_turn": None,
                "fixed_two_turn": 4,
                "adaptive_two_to_four_turn": 3,
            },
        ),
        _Case(
            case_id="domain_failure_spike",
            category="failure_recovery",
            stimulus=_stimulus(last_execution=_observed_execution(domain_failures=2)),
            expected_optional_turn=True,
            qualification_generation={
                "one_turn": None,
                "fixed_two_turn": 3,
                "adaptive_two_to_four_turn": 2,
            },
        ),
        _Case(
            case_id="ood_without_transfer_memory",
            category="cold_start",
            stimulus=_stimulus(observed_failure_rate=0.3),
            expected_optional_turn=True,
            qualification_generation={
                "one_turn": None,
                "fixed_two_turn": 4,
                "adaptive_two_to_four_turn": 3,
            },
        ),
        _Case(
            case_id="hard_boundary_safety_review",
            category="constraint_pressure",
            stimulus=_stimulus(),
            expected_optional_turn=True,
            hard_boundary_candidate=True,
            qualification_generation={
                "one_turn": None,
                "fixed_two_turn": 3,
                "adaptive_two_to_four_turn": 2,
            },
        ),
        _Case(
            case_id="cooldown_suppresses_duplicate_stagnation",
            category="stagnation",
            stimulus=_stimulus(trailing_stagnant_generations=2, best_score=1.0),
            expected_optional_turn=False,
            cooldown_reasons=("trailing_stagnation",),
            qualification_generation={
                "one_turn": 3,
                "fixed_two_turn": 2,
                "adaptive_two_to_four_turn": 2,
            },
        ),
        _Case(
            case_id="severity_escalation_over_cooldown",
            category="constraint_pressure",
            stimulus=_stimulus(),
            expected_optional_turn=True,
            hard_boundary_candidate=True,
            cooldown_reasons=("hard_boundary_candidate",),
            qualification_generation={
                "one_turn": None,
                "fixed_two_turn": 3,
                "adaptive_two_to_four_turn": 2,
            },
        ),
        _Case(
            case_id="no_validated_winner_under_frozen_budget",
            category="tight_budget",
            stimulus=_stimulus(),
            expected_optional_turn=False,
            qualification_generation={
                "one_turn": None,
                "fixed_two_turn": None,
                "adaptive_two_to_four_turn": None,
            },
        ),
    )


def _case_descriptor(case: _Case) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "category": case.category,
        "stimulus": case.stimulus.model_dump(mode="json", exclude_none=True),
        "expected_optional_turn": case.expected_optional_turn,
        "tool_direction_conflict": case.tool_direction_conflict,
        "hard_boundary_candidate": case.hard_boundary_candidate,
        "cooldown_reasons": list(case.cooldown_reasons),
        "qualification_generation": case.qualification_generation,
    }


def build_cognitive_budget_ablation_manifest() -> dict[str, Any]:
    cases = [_case_descriptor(case) for case in _cases()]
    unsigned: dict[str, Any] = {
        "schema_version": COGNITIVE_ABLATION_MANIFEST_SCHEMA_VERSION,
        "claim_label": COGNITIVE_ABLATION_LABEL,
        "claim_boundary": COGNITIVE_ABLATION_CLAIM_BOUNDARY,
        "cognitive_policy_version": COGNITIVE_POLICY_VERSION,
        "trigger_policy_version": COGNITIVE_TRIGGER_POLICY_VERSION,
        "arms": list(ARMS),
        "fixed_budget": {
            "generation_cap": GENERATION_CAP,
            "trial_cap": TRIAL_CAP,
            "simulation_cap": SIMULATION_CAP,
            "trials_per_generation": TRIALS_PER_GENERATION,
            "provider_retries": 0,
        },
        "fixtures": {
            "model": MODEL_FIXTURE,
            "tools": TOOL_FIXTURE,
            "scenarios": SCENARIO_FIXTURE,
            "seeds": list(SEEDS),
        },
        "case_count": len(cases),
        "cases_sha256": _sha256(cases),
        "cases": cases,
    }
    return {**unsigned, "manifest_sha256": _sha256(unsigned)}


def _trigger_row(case: _Case) -> dict[str, Any]:
    eval_case = HarnessRoutingEvalCase(
        case_id=case.case_id,
        category=case.category,
        stimulus=case.stimulus,
        acceptable_tools=("optimizer_portfolio",),
        rationale="Frozen cognitive-budget ablation fixture.",
    )
    snapshot = compile_routing_eval_snapshot(eval_case)
    generation_index = case.stimulus.current_generation + 1
    prior_receipts = [
        SimpleNamespace(
            generation_index=generation_index - 1,
            trigger_reasons_json=[reason],
        )
        for reason in case.cooldown_reasons
    ]
    job = cast(
        models.Job,
        SimpleNamespace(
            target_rmse=None,
            target_max_error=None,
            scenario_suite_json={},
            candidates=[],
            cognitive_turn_receipts=prior_receipts,
        ),
    )
    evaluation = evaluate_adaptive_triggers(
        job,
        generation_index=generation_index,
        snapshot=snapshot,
        proposal_tools={"proposal-a": "optimizer_portfolio"},
        selected_proposal_refs=("proposal-a",),
        tool_direction_conflict=case.tool_direction_conflict,
        hard_boundary_candidate=case.hard_boundary_candidate,
    )
    optional_turn_count = int(evaluation.diagnosis_required) + int(
        evaluation.critic_required
    )
    return {
        "expected_optional_turn": case.expected_optional_turn,
        "optional_turn_triggered": optional_turn_count > 0,
        "diagnosis_reasons": list(evaluation.diagnosis_reasons),
        "critic_reasons": list(evaluation.critic_reasons),
        "suppressed_by_cooldown": list(evaluation.suppressed_by_cooldown),
        "optional_turn_count": optional_turn_count,
        "holdout_outcomes_visible": evaluation.evidence["holdout_outcomes_visible"],
        "trigger_evidence_sha256": _sha256(evaluation.evidence),
    }


def _arm_row(case: _Case, arm: ArmName, trigger: dict[str, Any]) -> dict[str, Any]:
    qualification_generation = case.qualification_generation[arm]
    generations_consumed = qualification_generation or GENERATION_CAP
    if arm == "one_turn":
        provider_turns = generations_consumed
    elif arm == "fixed_two_turn":
        provider_turns = generations_consumed * 2
    else:
        first_turn_stop = case.case_id == "direct_first_turn_stop"
        provider_turns = (
            1
            if first_turn_stop
            else generations_consumed * 2 + int(trigger["optional_turn_count"])
        )
    trials = min(TRIAL_CAP, generations_consumed * TRIALS_PER_GENERATION)
    qualified = qualification_generation is not None
    return {
        "arm": arm,
        "qualified": qualified,
        "terminal_result": "first_qualified" if qualified else "no_validated_winner",
        "generations_to_first_qualified": qualification_generation,
        "trials_to_first_qualified": trials if qualified else None,
        "simulations_to_first_qualified": trials if qualified else None,
        "provider_turns_to_first_qualified": provider_turns if qualified else None,
        "consumed_generations": generations_consumed,
        "consumed_trials": trials,
        "consumed_simulations": trials,
        "simulated_provider_turns_attempted": provider_turns,
        "simulated_provider_turns_succeeded": provider_turns,
        "provider_retries": 0,
        "time_to_first_qualified_ms": (
            trials * SIMULATION_WALL_MS + provider_turns * PROVIDER_TURN_WALL_MS
            if qualified
            else None
        ),
    }


def _arm_summary(rows: list[dict[str, Any]], arm: ArmName) -> dict[str, Any]:
    selected = [row for row in rows if row["arm"] == arm]
    qualified = [row for row in selected if row["qualified"]]
    times = [int(row["time_to_first_qualified_ms"]) for row in qualified]
    simulations = [int(row["simulations_to_first_qualified"]) for row in qualified]
    calls = [int(row["provider_turns_to_first_qualified"]) for row in qualified]
    return {
        "arm": arm,
        "case_count": len(selected),
        "qualified_case_count": len(qualified),
        "qualification_rate": len(qualified) / len(selected),
        "no_validated_winner_count": len(selected) - len(qualified),
        "median_time_to_first_qualified_ms": median(times) if times else None,
        "median_simulations_to_first_qualified": median(simulations) if simulations else None,
        "median_provider_turns_to_first_qualified": median(calls) if calls else None,
        "total_consumed_simulations": sum(int(row["consumed_simulations"]) for row in selected),
        "total_simulated_provider_turns": sum(
            int(row["simulated_provider_turns_attempted"]) for row in selected
        ),
    }


def build_cognitive_budget_ablation_artifact() -> dict[str, Any]:
    manifest = build_cognitive_budget_ablation_manifest()
    case_rows: list[dict[str, Any]] = []
    flat_arm_rows: list[dict[str, Any]] = []
    trigger_counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for case in _cases():
        trigger = _trigger_row(case)
        expected = bool(trigger["expected_optional_turn"])
        observed = bool(trigger["optional_turn_triggered"])
        bucket = "tp" if expected and observed else "fp" if observed else "fn" if expected else "tn"
        trigger_counts[bucket] += 1
        arms = [_arm_row(case, arm, trigger) for arm in ARMS]
        flat_arm_rows.extend(arms)
        case_rows.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "trigger": trigger,
                "arms": arms,
            }
        )
    true_positive_denominator = trigger_counts["tp"] + trigger_counts["fp"]
    negative_denominator = trigger_counts["fp"] + trigger_counts["tn"]
    summaries = [_arm_summary(flat_arm_rows, arm) for arm in ARMS]
    triggered_cases = [
        row for row in case_rows if row["trigger"]["expected_optional_turn"]
    ]
    marginal_rows = []
    for row in triggered_cases:
        fixed = next(item for item in row["arms"] if item["arm"] == "fixed_two_turn")
        adaptive = next(
            item for item in row["arms"] if item["arm"] == "adaptive_two_to_four_turn"
        )
        marginal_rows.append(
            {
                "case_id": row["case_id"],
                "additional_provider_turns_vs_fixed_two": (
                    adaptive["simulated_provider_turns_attempted"]
                    - fixed["simulated_provider_turns_attempted"]
                ),
                "simulations_saved_vs_fixed_two": (
                    fixed["consumed_simulations"] - adaptive["consumed_simulations"]
                ),
                "adaptive_qualified": adaptive["qualified"],
                "fixed_two_qualified": fixed["qualified"],
            }
        )
    unsigned: dict[str, Any] = {
        "schema_version": COGNITIVE_ABLATION_SCHEMA_VERSION,
        "claim_label": COGNITIVE_ABLATION_LABEL,
        "claim_boundary": COGNITIVE_ABLATION_CLAIM_BOUNDARY,
        "manifest_sha256": manifest["manifest_sha256"],
        "real_provider_calls": 0,
        "network_calls": 0,
        "simulator_runs": 0,
        "real_credentials_used": False,
        "optimizer_quality_claim_permitted": False,
        "general_model_benefit_claim_permitted": False,
        "case_rows": case_rows,
        "summary": {
            "case_count": len(case_rows),
            "arm_count": len(ARMS),
            "fixed_budget_equal_across_arms": True,
            "trigger_confusion": trigger_counts,
            "trigger_precision": (
                trigger_counts["tp"] / true_positive_denominator
                if true_positive_denominator
                else None
            ),
            "trigger_false_positive_rate": (
                trigger_counts["fp"] / negative_denominator
                if negative_denominator
                else None
            ),
            "arm_summaries": summaries,
            "marginal_optional_turn_rows": marginal_rows,
        },
    }
    return {**unsigned, "artifact_sha256": _sha256(unsigned)}


def verify_cognitive_budget_ablation_manifest(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Cognitive-budget ablation manifest must be an object")
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    if payload.get("manifest_sha256") != _sha256(unsigned):
        raise ValueError("Cognitive-budget ablation manifest hash does not recompute")
    if payload != build_cognitive_budget_ablation_manifest():
        raise ValueError("Cognitive-budget ablation manifest drifted")
    return payload


def verify_cognitive_budget_ablation_artifact(
    payload: object,
    *,
    manifest: object | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Cognitive-budget ablation artifact must be an object")
    unsigned = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    if payload.get("artifact_sha256") != _sha256(unsigned):
        raise ValueError("Cognitive-budget ablation artifact hash does not recompute")
    current_manifest = (
        build_cognitive_budget_ablation_manifest()
        if manifest is None
        else verify_cognitive_budget_ablation_manifest(manifest)
    )
    if payload.get("manifest_sha256") != current_manifest["manifest_sha256"]:
        raise ValueError("Cognitive-budget ablation manifest binding drifted")
    if payload != build_cognitive_budget_ablation_artifact():
        raise ValueError("Cognitive-budget ablation artifact drifted")
    return payload


__all__ = [
    "ARMS",
    "COGNITIVE_ABLATION_CLAIM_BOUNDARY",
    "COGNITIVE_ABLATION_LABEL",
    "COGNITIVE_ABLATION_MANIFEST_SCHEMA_VERSION",
    "COGNITIVE_ABLATION_SCHEMA_VERSION",
    "build_cognitive_budget_ablation_artifact",
    "build_cognitive_budget_ablation_manifest",
    "verify_cognitive_budget_ablation_artifact",
    "verify_cognitive_budget_ablation_manifest",
]
