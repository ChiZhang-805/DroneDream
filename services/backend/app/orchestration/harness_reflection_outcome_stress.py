"""Long-horizon matched outcome stress test for AURORA reflection.

This protocol extends the existing component ablation to four generations so
later routed tools can materialize distinct candidate cohorts. The fixed mock
landscape and local scripted router make the intervention reproducible, but
the pilot-informed synthetic protocol is not a confirmatory benchmark.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from typing import Any, cast

from app.orchestration.harness_component_ablation import (
    HARNESS_COMPONENT_ABLATION_ARMS,
    HARNESS_COMPONENT_ABLATION_SEED_BLOCKS,
    HarnessComponentArm,
    _run_arm,
    _verify_arm,
    build_harness_component_ablation_manifest,
)

HARNESS_REFLECTION_OUTCOME_STRESS_SCHEMA_VERSION = (
    "dronedream.harness-reflection-outcome-stress/v1"
)
HARNESS_REFLECTION_OUTCOME_STRESS_MANIFEST_SCHEMA_VERSION = (
    "dronedream.harness-reflection-outcome-stress-manifest/v1"
)
HARNESS_REFLECTION_OUTCOME_STRESS_EVIDENCE_CLASS = (
    "synthetic_mock_long_horizon_component_stress"
)
HARNESS_REFLECTION_OUTCOME_STRESS_LABEL = "SYNTHETIC_MOCK_PILOT_INFORMED"
HARNESS_REFLECTION_OUTCOME_STRESS_CLAIM_BOUNDARY = (
    "Matched deterministic component intervention on MockSimulatorAdapter with "
    "a local scripted router and a pilot-informed four-generation budget. "
    "Results establish only protocol effects in these frozen synthetic seed "
    "blocks. They do not establish a general quality benefit, LLM superiority, "
    "PX4/Gazebo performance, physical fidelity, real-aircraft transfer, or "
    "flight safety."
)
HARNESS_REFLECTION_OUTCOME_STRESS_MAX_ITERATIONS = 4
HARNESS_REFLECTION_OUTCOME_STRESS_MAX_TOTAL_TRIALS = 120
HARNESS_REFLECTION_OUTCOME_STRESS_LEGACY_MANIFEST_SHA256 = (
    "bbf3d39405fd9092d59cf5d0557d14616f8d4a8739e1865f7e2cf6fda811e1b2"
)

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


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def build_harness_reflection_outcome_stress_manifest() -> dict[str, Any]:
    parent = build_harness_component_ablation_manifest()
    unsigned: dict[str, Any] = {
        "schema_version": HARNESS_REFLECTION_OUTCOME_STRESS_MANIFEST_SCHEMA_VERSION,
        "evidence_class": HARNESS_REFLECTION_OUTCOME_STRESS_EVIDENCE_CLASS,
        "claim_label": HARNESS_REFLECTION_OUTCOME_STRESS_LABEL,
        "claim_boundary": HARNESS_REFLECTION_OUTCOME_STRESS_CLAIM_BOUNDARY,
        "pilot_informed_protocol": True,
        "confirmatory_claim_permitted": False,
        "parent_component_protocol_manifest_sha256": parent["manifest_sha256"],
        "arms": list(HARNESS_COMPONENT_ABLATION_ARMS),
        "seed_blocks": list(HARNESS_COMPONENT_ABLATION_SEED_BLOCKS),
        "primary_contrast": {
            "reference_arm": "full_aurora",
            "comparison_arm": "no_observed_outcome_reflection",
            "component": "observed_outcome_reflection",
        },
        "secondary_contrasts": [
            {
                "reference_arm": "full_aurora",
                "comparison_arm": "no_decision_memory",
                "component": "decision_memory_including_reflection",
            },
            {
                "reference_arm": "full_aurora",
                "comparison_arm": "fixed_deterministic_portfolio",
                "component": "harness_router",
            },
        ],
        "budget": {
            "max_iterations": HARNESS_REFLECTION_OUTCOME_STRESS_MAX_ITERATIONS,
            "max_total_trials": HARNESS_REFLECTION_OUTCOME_STRESS_MAX_TOTAL_TRIALS,
            "same_declared_budget_for_every_arm": True,
            "realized_trial_count_is_an_outcome": True,
            "driver_step_limit": (
                HARNESS_REFLECTION_OUTCOME_STRESS_MAX_TOTAL_TRIALS + 20
            ),
        },
        "scenario_matrix": parent["scenario_matrix"],
        "objective_contract": parent["objective_contract"],
        "initial_design": parent["initial_design"],
        "time_to_target": parent["time_to_target"],
        "interventions": parent["interventions"],
        "scripted_router_policy": parent["scripted_router_policy"],
        "runtime_contract": parent["runtime_contract"],
        "metrics": list(_RESULT_METRICS),
        "analysis": {
            "holdout_loss_direction": "lower_is_better",
            "total_trials_direction": "lower_is_lower_realized_cost",
            "paired_seed_block_signs_reported": True,
            "ties_use_absolute_tolerance": 1e-12,
            "quality_benefit_requires": (
                "full_aurora lower holdout loss in every seed block of the "
                "primary contrast with no contradictory paired sign"
            ),
            "protocol_effect": (
                "the direct intervention is activated and changes the routed "
                "tool sequence, realized outcome hash, or preregistered metrics"
            ),
        },
    }
    return {
        **unsigned,
        "manifest_sha256": _sha256(unsigned),
    }


def verify_harness_reflection_outcome_stress_manifest(
    payload: object,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Harness reflection outcome-stress manifest must be an object")
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    if payload.get("manifest_sha256") != _sha256(unsigned):
        raise ValueError(
            "Harness reflection outcome-stress manifest hash does not recompute"
        )
    expected = build_harness_reflection_outcome_stress_manifest()
    runtime = payload.get("runtime_contract")
    legacy = (
        isinstance(runtime, dict)
        and runtime.get("evidence_schema_version") == "2.7"
        and runtime.get("prompt_template_version") == "1.6"
        and payload.get("manifest_sha256")
        == HARNESS_REFLECTION_OUTCOME_STRESS_LEGACY_MANIFEST_SHA256
    )
    if payload != expected and not legacy:
        raise ValueError("Harness reflection outcome-stress manifest drifted")
    return payload


def _comparison_row(
    *,
    block_id: int,
    seed_block: int,
    reference: dict[str, Any],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    activation = comparison["component_activation"]
    differing_metrics = [
        metric
        for metric in _RESULT_METRICS
        if reference["result_metrics"][metric] != comparison["result_metrics"][metric]
    ]
    tool_sequence_changed = (
        reference["tool_sequence"] != comparison["tool_sequence"]
    )
    outcome_changed = reference["outcome_sha256"] != comparison["outcome_sha256"]
    intervention_activated = bool(
        activation["provider_visible_intervention_activated"]
    )
    if not intervention_activated:
        result_status = "inconclusive_intervention_not_activated"
    elif tool_sequence_changed or outcome_changed or differing_metrics:
        result_status = "causal_protocol_difference"
    else:
        result_status = "no_observed_protocol_difference"
    full_holdout = float(reference["result_metrics"]["holdout_loss"])
    comparison_holdout = float(comparison["result_metrics"]["holdout_loss"])
    holdout_delta_comparison_minus_full = comparison_holdout - full_holdout
    full_trials = int(reference["result_metrics"]["total_trials"])
    comparison_trials = int(comparison["result_metrics"]["total_trials"])
    return {
        "block_id": block_id,
        "seed_block": seed_block,
        "reference_arm": reference["arm"],
        "comparison_arm": comparison["arm"],
        "intervention_component": activation["component"],
        "intervention_activated": intervention_activated,
        "result_status": result_status,
        "tool_sequence_changed": tool_sequence_changed,
        "outcome_changed": outcome_changed,
        "differing_metrics": differing_metrics,
        "full_holdout_loss": full_holdout,
        "comparison_holdout_loss": comparison_holdout,
        "holdout_delta_comparison_minus_full": holdout_delta_comparison_minus_full,
        "full_total_trials": full_trials,
        "comparison_total_trials": comparison_trials,
        "trial_delta_comparison_minus_full": comparison_trials - full_trials,
    }


def _paired_direction(values: list[float]) -> dict[str, int]:
    tolerance = 1e-12
    return {
        "full_better": sum(value > tolerance for value in values),
        "comparison_better": sum(value < -tolerance for value in values),
        "tie": sum(abs(value) <= tolerance for value in values),
    }


def _contrast_summary(
    comparison_rows: list[dict[str, Any]],
    *,
    comparison_arm: str,
) -> dict[str, Any]:
    rows = [
        row
        for row in comparison_rows
        if row["comparison_arm"] == comparison_arm
    ]
    holdout_deltas = [
        float(row["holdout_delta_comparison_minus_full"]) for row in rows
    ]
    trial_deltas = [float(row["trial_delta_comparison_minus_full"]) for row in rows]
    holdout_signs = _paired_direction(holdout_deltas)
    trial_signs = _paired_direction(trial_deltas)
    return {
        "comparison_arm": comparison_arm,
        "block_count": len(rows),
        "intervention_activated_blocks": sum(
            bool(row["intervention_activated"]) for row in rows
        ),
        "causal_protocol_difference_blocks": sum(
            row["result_status"] == "causal_protocol_difference" for row in rows
        ),
        "tool_sequence_changed_blocks": sum(
            bool(row["tool_sequence_changed"]) for row in rows
        ),
        "outcome_changed_blocks": sum(bool(row["outcome_changed"]) for row in rows),
        "holdout_paired_signs": holdout_signs,
        "holdout_delta_comparison_minus_full_mean": statistics.fmean(
            holdout_deltas
        ),
        "holdout_delta_comparison_minus_full_median": statistics.median(
            holdout_deltas
        ),
        "realized_trial_paired_signs": trial_signs,
        "trial_delta_comparison_minus_full_total": int(sum(trial_deltas)),
        "trial_delta_comparison_minus_full_mean": statistics.fmean(trial_deltas),
        "consistent_full_holdout_benefit": (
            holdout_signs["full_better"] == len(rows)
            and holdout_signs["comparison_better"] == 0
        ),
        "consistent_full_realized_trial_reduction": (
            trial_signs["full_better"] == len(rows)
            and trial_signs["comparison_better"] == 0
        ),
    }


def _build_from_blocks(
    *,
    manifest: dict[str, Any],
    block_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    comparison_rows: list[dict[str, Any]] = []
    for block in block_rows:
        by_name = {str(arm["arm"]): arm for arm in block["arms"]}
        reference = by_name["full_aurora"]
        for comparison_arm in HARNESS_COMPONENT_ABLATION_ARMS[1:]:
            comparison_rows.append(
                _comparison_row(
                    block_id=int(block["block_id"]),
                    seed_block=int(block["seed_block"]),
                    reference=reference,
                    comparison=by_name[comparison_arm],
                )
            )
    contrasts = {
        arm: _contrast_summary(comparison_rows, comparison_arm=arm)
        for arm in HARNESS_COMPONENT_ABLATION_ARMS[1:]
    }
    primary = contrasts["no_observed_outcome_reflection"]
    status_names = (
        "causal_protocol_difference",
        "no_observed_protocol_difference",
        "inconclusive_intervention_not_activated",
    )
    unsigned: dict[str, Any] = {
        "schema_version": HARNESS_REFLECTION_OUTCOME_STRESS_SCHEMA_VERSION,
        "evidence_class": HARNESS_REFLECTION_OUTCOME_STRESS_EVIDENCE_CLASS,
        "claim_label": HARNESS_REFLECTION_OUTCOME_STRESS_LABEL,
        "claim_boundary": HARNESS_REFLECTION_OUTCOME_STRESS_CLAIM_BOUNDARY,
        "manifest_sha256": manifest["manifest_sha256"],
        "physical_fidelity": False,
        "simulator_backend": "mock",
        "live_model_calls": False,
        "network_calls": sum(
            int(arm["network_calls"])
            for block in block_rows
            for arm in block["arms"]
        ),
        "real_credentials_used": False,
        "general_causal_benefit_claim_permitted": False,
        "llm_superiority_claim_permitted": False,
        "px4_or_flight_claim_permitted": False,
        "consistent_holdout_benefit_observed": bool(
            primary["consistent_full_holdout_benefit"]
        ),
        "causal_synthetic_protocol_effect_observed": (
            int(primary["causal_protocol_difference_blocks"])
            == len(HARNESS_COMPONENT_ABLATION_SEED_BLOCKS)
        ),
        "summary": {
            "seed_block_count": len(HARNESS_COMPONENT_ABLATION_SEED_BLOCKS),
            "arm_count": len(HARNESS_COMPONENT_ABLATION_ARMS),
            "arm_run_count": (
                len(HARNESS_COMPONENT_ABLATION_SEED_BLOCKS)
                * len(HARNESS_COMPONENT_ABLATION_ARMS)
            ),
            "comparison_count": len(comparison_rows),
            "total_persisted_trials": sum(
                int(arm["result_metrics"]["total_trials"])
                for block in block_rows
                for arm in block["arms"]
            ),
            "interpretation_status_counts": {
                status: sum(
                    row["result_status"] == status for row in comparison_rows
                )
                for status in status_names
            },
            "all_network_calls_blocked": all(
                arm["network_calls"] == 0
                and arm["network_connect_guard_enforced"] is True
                for block in block_rows
                for arm in block["arms"]
            ),
            "all_evidence_complete": all(
                arm["result_metrics"]["evidence_completeness_rate"] == 1.0
                for block in block_rows
                for arm in block["arms"]
            ),
            "primary_holdout_direction_mixed": (
                primary["holdout_paired_signs"]["full_better"] > 0
                and primary["holdout_paired_signs"]["comparison_better"] > 0
            ),
            "primary_full_lower_realized_trials_every_block": bool(
                primary["consistent_full_realized_trial_reduction"]
            ),
        },
        "contrast_summaries": contrasts,
        "comparison_rows": comparison_rows,
        "block_rows": block_rows,
    }
    return {
        **unsigned,
        "artifact_sha256": _sha256(unsigned),
    }


def build_harness_reflection_outcome_stress_artifact() -> dict[str, Any]:
    manifest = build_harness_reflection_outcome_stress_manifest()
    block_rows: list[dict[str, Any]] = []
    for block_id, seed_block in enumerate(
        HARNESS_COMPONENT_ABLATION_SEED_BLOCKS,
        start=1,
    ):
        arms = [
            _run_arm(
                seed_block,
                cast(HarnessComponentArm, arm),
                max_iterations=HARNESS_REFLECTION_OUTCOME_STRESS_MAX_ITERATIONS,
                max_total_trials=HARNESS_REFLECTION_OUTCOME_STRESS_MAX_TOTAL_TRIALS,
            )
            for arm in HARNESS_COMPONENT_ABLATION_ARMS
        ]
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
    return _build_from_blocks(manifest=manifest, block_rows=block_rows)


def verify_harness_reflection_outcome_stress_artifact(
    payload: object,
    *,
    manifest: object | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Harness reflection outcome-stress artifact must be an object")
    unsigned = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    if payload.get("artifact_sha256") != _sha256(unsigned):
        raise ValueError(
            "Harness reflection outcome-stress artifact hash does not recompute"
        )
    current_manifest = (
        build_harness_reflection_outcome_stress_manifest()
        if manifest is None
        else verify_harness_reflection_outcome_stress_manifest(manifest)
    )
    if payload.get("manifest_sha256") != current_manifest["manifest_sha256"]:
        raise ValueError(
            "Harness reflection outcome-stress artifact manifest binding drifted"
        )
    raw_blocks = payload.get("block_rows")
    if not isinstance(raw_blocks, list) or len(raw_blocks) != len(
        HARNESS_COMPONENT_ABLATION_SEED_BLOCKS
    ):
        raise ValueError("Harness reflection outcome-stress blocks are invalid")
    for block_id, (block, seed_block) in enumerate(
        zip(
            raw_blocks,
            HARNESS_COMPONENT_ABLATION_SEED_BLOCKS,
            strict=True,
        ),
        start=1,
    ):
        if (
            not isinstance(block, dict)
            or block.get("block_id") != block_id
            or block.get("seed_block") != seed_block
            or block.get("training_seeds")
            != [seed_block + 1, seed_block + 2, seed_block + 3]
            or block.get("holdout_seeds") != [seed_block + 99]
        ):
            raise ValueError("Harness reflection outcome-stress block is invalid")
        arms = block.get("arms")
        if not isinstance(arms, list) or [
            arm.get("arm") if isinstance(arm, dict) else None for arm in arms
        ] != list(HARNESS_COMPONENT_ABLATION_ARMS):
            raise ValueError("Harness reflection outcome-stress arm order drifted")
        for arm, expected_name in zip(
            arms,
            HARNESS_COMPONENT_ABLATION_ARMS,
            strict=True,
        ):
            _verify_arm(
                arm,
                expected_name=expected_name,
                expected_prompt_count=HARNESS_REFLECTION_OUTCOME_STRESS_MAX_ITERATIONS,
            )
    recomputed = _build_from_blocks(
        manifest=current_manifest,
        block_rows=cast(list[dict[str, Any]], raw_blocks),
    )
    if payload != recomputed:
        raise ValueError("Harness reflection outcome-stress summaries drifted")
    return payload


__all__ = [
    "HARNESS_REFLECTION_OUTCOME_STRESS_CLAIM_BOUNDARY",
    "HARNESS_REFLECTION_OUTCOME_STRESS_EVIDENCE_CLASS",
    "HARNESS_REFLECTION_OUTCOME_STRESS_LABEL",
    "HARNESS_REFLECTION_OUTCOME_STRESS_MANIFEST_SCHEMA_VERSION",
    "HARNESS_REFLECTION_OUTCOME_STRESS_MAX_ITERATIONS",
    "HARNESS_REFLECTION_OUTCOME_STRESS_MAX_TOTAL_TRIALS",
    "HARNESS_REFLECTION_OUTCOME_STRESS_SCHEMA_VERSION",
    "build_harness_reflection_outcome_stress_artifact",
    "build_harness_reflection_outcome_stress_manifest",
    "verify_harness_reflection_outcome_stress_artifact",
    "verify_harness_reflection_outcome_stress_manifest",
]
