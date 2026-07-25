"""Versioned optimization-outcome and candidate-selection contracts."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app import schemas

OUTCOME_CONTRACT_SCHEMA = "dronedream.optimization-outcome/v1"
OUTCOME_CONTRACT_COMPILER_VERSION = "1.6"
SELECTION_KEY_SCHEMA_VERSION = "1.0"
OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT = 0.5

MetricSource = Literal[
    "canonical_trial_metric",
    "candidate_aggregate",
    "adapter_raw_metric",
]

_CANONICAL_METRICS: dict[str, tuple[MetricSource, str, str]] = {
    "rmse": ("canonical_trial_metric", "m", "continuous"),
    "max_error": ("canonical_trial_metric", "m", "continuous"),
    "overshoot_count": ("canonical_trial_metric", "count", "integer"),
    "completion_time": ("canonical_trial_metric", "s", "continuous"),
    "crash_flag": ("canonical_trial_metric", "boolean", "binary"),
    "timeout_flag": ("canonical_trial_metric", "boolean", "binary"),
    "score": ("canonical_trial_metric", "adapter_defined", "continuous"),
    "final_error": ("canonical_trial_metric", "m", "continuous"),
    "pass_flag": ("canonical_trial_metric", "boolean", "binary"),
    "instability_flag": ("canonical_trial_metric", "boolean", "binary"),
    "completion_rate": ("candidate_aggregate", "ratio", "continuous"),
    "failed_trial_rate": ("candidate_aggregate", "ratio", "continuous"),
    "failure_rate": ("candidate_aggregate", "ratio", "continuous"),
    "pass_rate": ("candidate_aggregate", "ratio", "continuous"),
}
_KNOWN_RELIABILITY_DEPENDENCY_GROUP = frozenset(
    {
        "completion_rate",
        "failed_trial_rate",
        "failure_rate",
    }
)
_EXCLUSIVE_COMPOSITE_OBJECTIVES = frozenset({"score"})
_METRIC_REGISTRY = {
    "metrics": _CANONICAL_METRICS,
    "known_dependency_groups": [
        sorted(_KNOWN_RELIABILITY_DEPENDENCY_GROUP),
    ],
    "exclusive_composite_objectives": sorted(
        _EXCLUSIVE_COMPOSITE_OBJECTIVES
    ),
}
_SCENARIO_TYPES = frozenset(
    {
        "nominal",
        "noise_perturbed",
        "wind_perturbed",
        "combined_perturbed",
        "turbulence",
        "gps_dropout",
        "payload_changed",
        "battery_degraded",
        "actuator_delay",
        "custom",
    }
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OutcomeMetricReference(_FrozenModel):
    metric: str
    registry_id: str
    source: MetricSource
    unit: str
    value_kind: str


class OutcomeObjective(_FrozenModel):
    objective_id: str
    metric: OutcomeMetricReference
    direction: schemas.ObjectiveDirection
    weight_decimal: str
    normalization_decimal: str
    target_decimal: str | None
    estimator_scope: Literal["within_case_estimator_then_fixed_suite"]
    robust_estimator: str
    within_case_estimator: str
    across_case_estimator: Literal["mean", "worst"]
    sample_weight_policy: Literal[
        "full_case_weight_after_within_case_estimator"
    ]
    missing_policy: str


class OutcomeConstraint(_FrozenModel):
    constraint_id: str
    metric: OutcomeMetricReference
    operator: schemas.ConstraintOperator
    threshold_decimal: str
    hard: bool
    penalty_decimal: str
    observation_policy: str
    violation_scale_policy: str


class OutcomeScenarioCase(_FrozenModel):
    case_id: str
    scenario_type: schemas.ScenarioType
    seeds: tuple[int, ...]
    weight_decimal: str
    holdout: bool
    config_sha256: str


class OutcomeScenarioPopulation(_FrozenModel):
    case_semantics: Literal["fixed_suite"] = "fixed_suite"
    case_weight_semantics: Literal["decision_priority"] = "decision_priority"
    replicate_semantics: Literal[
        "declared_within_case_estimator_with_failure_rate_separate"
    ] = (
        "declared_within_case_estimator_with_failure_rate_separate"
    )
    common_random_numbers: bool
    cases: tuple[OutcomeScenarioCase, ...]
    missing_metric_policy: Literal["fail_dispatched_case_without_usable_metric"] = (
        "fail_dispatched_case_without_usable_metric"
    )


class OutcomeFailurePolicy(_FrozenModel):
    failed_trial_treatment: Literal["separate_rate_penalty"] = "separate_rate_penalty"
    failed_trial_weight_decimal: str
    optimizer_learning_failure_rate_operator: Literal["lt"] = "lt"
    optimizer_learning_failure_rate_limit_decimal: str
    hard_constraint_penalty_in_scalar_loss: Literal[False] = False
    soft_constraint_penalty_in_scalar_loss: Literal[True] = True


class OutcomeSelectionPolicy(_FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    optimizer_objective_representation_policy: Literal[
        "one_representation_per_tool_call"
    ] = "one_representation_per_tool_call"
    bayesian_multiobjective_policy: Literal[
        "joint_objective_vector_else_scalar_loss"
    ] = "joint_objective_vector_else_scalar_loss"
    scalar_optimizer_policy: Literal["scalar_loss_only"] = "scalar_loss_only"
    bayesian_objective_scale_policy: Literal[
        "fixed_job_objective_normalization"
    ] = "fixed_job_objective_normalization"
    bayesian_scalarization_policy: Literal[
        "fixed_job_objective_weights"
    ] = "fixed_job_objective_weights"
    incomplete_objective_vector_policy: Literal[
        "scalar_loss_else_exploration"
    ] = "scalar_loss_else_exploration"
    precedence: tuple[str, ...] = (
        "evidence_complete",
        "hard_feasible",
        "hard_constraint_violation",
        "training_failure_rate",
        "preference_and_soft_constraint_loss",
        "stable_tiebreak",
    )
    compatibility_score: str = (
        "preference_and_soft_constraint_loss_plus_failed_trial_rate_penalty"
    )


class OutcomePromotionPolicy(_FrozenModel):
    projection_schema: Literal["dronedream.acceptance-projection/v1"] = (
        "dronedream.acceptance-projection/v1"
    )
    rmse_estimator: Literal["within_case_mean_then_fixed_suite_mean"] = (
        "within_case_mean_then_fixed_suite_mean"
    )
    max_error_estimator: Literal["worst_usable_seed"] = "worst_usable_seed"
    pass_rate_estimator: Literal["case_weighted_dispatched_seed_rate"] = (
        "case_weighted_dispatched_seed_rate"
    )
    require_complete_training_matrix: Literal[True] = True
    require_hard_feasible: Literal[True] = True
    require_complete_holdout_matrix_when_configured: Literal[True] = True
    require_every_holdout_trial_pass_when_configured: Literal[True] = True
    target_rmse_decimal: str | None
    target_max_error_decimal: str | None
    min_pass_rate_decimal: str


class OptimizationOutcomeContractV1(_FrozenModel):
    schema_id: Literal["dronedream.optimization-outcome/v1"] = "dronedream.optimization-outcome/v1"
    compiler_version: Literal["1.6"] = "1.6"
    contract_id: str
    metric_admission_policy: Literal["registered_metrics_only"] = (
        "registered_metrics_only"
    )
    metric_dependency_policy: Literal[
        "reject_known_alias_complement_and_composite_overlap"
    ] = "reject_known_alias_complement_and_composite_overlap"
    metric_registry_sha256: str
    objective_config_sha256: str
    scenario_suite_sha256: str
    acceptance_criteria_sha256: str
    compatibility_normalization: tuple[str, ...] = ()
    objectives: tuple[OutcomeObjective, ...]
    constraints: tuple[OutcomeConstraint, ...]
    scenario_population: OutcomeScenarioPopulation
    domain_failure_policy: OutcomeFailurePolicy
    selection_policy: OutcomeSelectionPolicy
    final_promotion_policy: OutcomePromotionPolicy


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _decimal(value: float | int) -> str:
    number = Decimal(str(value))
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _metric_reference(metric: str) -> OutcomeMetricReference:
    registered = _CANONICAL_METRICS.get(metric)
    if registered is None:
        allowed = ", ".join(sorted(_CANONICAL_METRICS))
        raise ValueError(
            f"unregistered optimization metric: {metric}; "
            f"registered metrics are: {allowed}"
        )
    source, unit, value_kind = registered
    return OutcomeMetricReference(
        metric=metric,
        registry_id=f"dronedream.metric.{metric}.v1",
        source=source,
        unit=unit,
        value_kind=value_kind,
    )


def _validate_metric_dependencies(
    objective_config: schemas.ObjectiveConfig,
) -> None:
    objective_metrics = {
        objective.metric for objective in objective_config.objectives
    }
    composite_overlap = objective_metrics & _EXCLUSIVE_COMPOSITE_OBJECTIVES
    if composite_overlap and len(objective_metrics) > 1:
        composite = sorted(composite_overlap)[0]
        raise ValueError(
            f"composite objective metric {composite} cannot be combined "
            "with another objective until its dependency graph is registered"
        )

    objective_reliability = sorted(
        objective_metrics & _KNOWN_RELIABILITY_DEPENDENCY_GROUP
    )
    if len(objective_reliability) > 1:
        raise ValueError(
            "dependent reliability objective metrics cannot be combined: "
            + ", ".join(objective_reliability)
        )

    constraint_metrics = {
        constraint.metric for constraint in objective_config.constraints
    }
    constraint_reliability = sorted(
        constraint_metrics & _KNOWN_RELIABILITY_DEPENDENCY_GROUP
    )
    if len(constraint_reliability) > 1:
        raise ValueError(
            "dependent reliability constraint metrics cannot be combined: "
            + ", ".join(constraint_reliability)
        )


def compile_outcome_contract(
    objective_config: schemas.ObjectiveConfig,
    scenario_suite: schemas.ScenarioSuiteConfig,
    acceptance_criteria: schemas.AcceptanceCriteria,
    *,
    failed_trial_weight: float,
    source_scenario_suite: object | None = None,
    compatibility_normalization: tuple[str, ...] = (),
) -> OptimizationOutcomeContractV1:
    """Compile the exact current outcome semantics into content-addressed JSON."""

    if not math.isfinite(failed_trial_weight) or failed_trial_weight < 0:
        raise ValueError("failed_trial_weight must be finite and non-negative")

    # Resolve every metric before constructing any contract payload. Numeric
    # values in adapter ``raw_metric_json`` are report evidence only until a
    # reviewed registry entry binds their unit, type, source, and semantics.
    for objective in objective_config.objectives:
        _metric_reference(objective.metric)
    for constraint in objective_config.constraints:
        _metric_reference(constraint.metric)
    _validate_metric_dependencies(objective_config)

    objectives = tuple(
        OutcomeObjective(
            objective_id=f"objective-{index + 1}:{item.metric}",
            metric=_metric_reference(item.metric),
            direction=item.direction,
            weight_decimal=_decimal(item.weight),
            normalization_decimal=_decimal(item.normalization),
            target_decimal=(_decimal(item.target) if item.target is not None else None),
            estimator_scope="within_case_estimator_then_fixed_suite",
            robust_estimator=objective_config.robust_aggregation,
            within_case_estimator=objective_config.robust_aggregation,
            across_case_estimator=(
                "worst"
                if objective_config.robust_aggregation == "worst"
                else "mean"
            ),
            sample_weight_policy=(
                "full_case_weight_after_within_case_estimator"
            ),
            missing_policy="fail_dispatched_case_without_usable_metric",
        )
        for index, item in enumerate(objective_config.objectives)
    )
    constraints = tuple(
        OutcomeConstraint(
            constraint_id=(
                f"{item.metric}:{item.operator}:{_decimal(item.threshold)}"
            ),
            metric=_metric_reference(item.metric),
            operator=item.operator,
            threshold_decimal=_decimal(item.threshold),
            hard=item.hard,
            penalty_decimal=_decimal(item.penalty),
            observation_policy="worst_usable_seed_sample",
            violation_scale_policy="max_one_or_absolute_threshold",
        )
        for item in objective_config.constraints
    )
    cases = tuple(
        OutcomeScenarioCase(
            case_id=case.id,
            scenario_type=case.scenario_type,
            seeds=tuple(case.seeds),
            weight_decimal=_decimal(case.weight),
            holdout=case.holdout,
            config_sha256=_sha256(case.config),
        )
        for case in scenario_suite.cases
        if case.enabled
    )
    objective_json = objective_config.model_dump(mode="json")
    scenario_json = (
        scenario_suite.model_dump(mode="json")
        if source_scenario_suite is None
        else source_scenario_suite
    )
    acceptance_json = acceptance_criteria.model_dump(mode="json")
    payload = {
        "schema_id": OUTCOME_CONTRACT_SCHEMA,
        "compiler_version": OUTCOME_CONTRACT_COMPILER_VERSION,
        "metric_admission_policy": "registered_metrics_only",
        "metric_dependency_policy": (
            "reject_known_alias_complement_and_composite_overlap"
        ),
        "metric_registry_sha256": _sha256(_METRIC_REGISTRY),
        "objective_config_sha256": _sha256(objective_json),
        "scenario_suite_sha256": _sha256(scenario_json),
        "acceptance_criteria_sha256": _sha256(acceptance_json),
        "compatibility_normalization": list(compatibility_normalization),
        "objectives": [item.model_dump(mode="json") for item in objectives],
        "constraints": [item.model_dump(mode="json") for item in constraints],
        "scenario_population": OutcomeScenarioPopulation(
            common_random_numbers=scenario_suite.common_random_numbers,
            cases=cases,
        ).model_dump(mode="json"),
        "domain_failure_policy": OutcomeFailurePolicy(
            failed_trial_weight_decimal=_decimal(failed_trial_weight),
            optimizer_learning_failure_rate_limit_decimal=_decimal(
                OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT
            ),
        ).model_dump(mode="json"),
        "selection_policy": OutcomeSelectionPolicy().model_dump(mode="json"),
        "final_promotion_policy": OutcomePromotionPolicy(
            target_rmse_decimal=(
                _decimal(acceptance_criteria.target_rmse)
                if acceptance_criteria.target_rmse is not None
                else None
            ),
            target_max_error_decimal=(
                _decimal(acceptance_criteria.target_max_error)
                if acceptance_criteria.target_max_error is not None
                else None
            ),
            min_pass_rate_decimal=_decimal(acceptance_criteria.min_pass_rate),
        ).model_dump(mode="json"),
    }
    return OptimizationOutcomeContractV1(
        contract_id=f"sha256:{_sha256(payload)}",
        objectives=objectives,
        constraints=constraints,
        scenario_population=OutcomeScenarioPopulation(
            common_random_numbers=scenario_suite.common_random_numbers,
            cases=cases,
        ),
        domain_failure_policy=OutcomeFailurePolicy(
            failed_trial_weight_decimal=_decimal(failed_trial_weight),
            optimizer_learning_failure_rate_limit_decimal=_decimal(
                OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT
            ),
        ),
        selection_policy=OutcomeSelectionPolicy(),
        final_promotion_policy=OutcomePromotionPolicy(
            target_rmse_decimal=(
                _decimal(acceptance_criteria.target_rmse)
                if acceptance_criteria.target_rmse is not None
                else None
            ),
            target_max_error_decimal=(
                _decimal(acceptance_criteria.target_max_error)
                if acceptance_criteria.target_max_error is not None
                else None
            ),
            min_pass_rate_decimal=_decimal(acceptance_criteria.min_pass_rate),
        ),
        metric_registry_sha256=str(payload["metric_registry_sha256"]),
        objective_config_sha256=str(payload["objective_config_sha256"]),
        scenario_suite_sha256=str(payload["scenario_suite_sha256"]),
        acceptance_criteria_sha256=str(payload["acceptance_criteria_sha256"]),
        compatibility_normalization=compatibility_normalization,
    )


def _persisted_scenario_suite(
    raw_suite: object,
) -> tuple[schemas.ScenarioSuiteConfig, object | None, tuple[str, ...]]:
    if raw_suite is None:
        return schemas.ScenarioSuiteConfig(), None, ()
    if not isinstance(raw_suite, dict):
        raise ValueError("persisted scenario suite must be an object")
    try:
        return schemas.ScenarioSuiteConfig(**raw_suite), None, ()
    except ValidationError as original_error:
        if set(raw_suite) - {"cases", "common_random_numbers"}:
            raise original_error
        raw_cases = raw_suite.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise original_error
        aliases = {
            "wind": "wind_perturbed",
            "noise": "noise_perturbed",
            "combined": "combined_perturbed",
        }
        normalized_cases: list[dict[str, object]] = []
        changed = False
        allowed_case_fields = {
            "id",
            "scenario_type",
            "seeds",
            "weight",
            "enabled",
            "holdout",
            "config",
        }
        for index, raw_case in enumerate(raw_cases):
            if not isinstance(raw_case, dict) or set(raw_case) - allowed_case_fields:
                raise original_error
            normalized = dict(raw_case)
            raw_type = normalized.get("scenario_type", "nominal")
            normalized_type = aliases.get(raw_type) if isinstance(raw_type, str) else None
            if normalized_type is not None:
                normalized["scenario_type"] = normalized_type
                changed = True
            elif raw_type not in _SCENARIO_TYPES:
                raise original_error
            else:
                normalized["scenario_type"] = raw_type
            if "id" not in normalized:
                normalized["id"] = f"legacy-{index + 1}-{normalized['scenario_type']}"
                changed = True
            normalized_cases.append(normalized)
        if not changed:
            raise original_error
        normalized_suite = {
            "cases": normalized_cases,
            "common_random_numbers": raw_suite.get(
                "common_random_numbers",
                True,
            ),
        }
        return (
            schemas.ScenarioSuiteConfig(**normalized_suite),
            raw_suite,
            ("legacy_scenario_aliases_v1",),
        )


def compile_job_outcome_contract(
    job: object,
    *,
    failed_trial_weight: float,
) -> OptimizationOutcomeContractV1:
    """Compile a persisted Job-like object without coupling to the ORM model."""

    objective_config = schemas.ObjectiveConfig(
        **(getattr(job, "objective_config_json", None) or {})
    )
    scenario_suite, source_scenario_suite, compatibility_normalization = (
        _persisted_scenario_suite(
            getattr(job, "scenario_suite_json", None),
        )
    )
    acceptance = schemas.AcceptanceCriteria(
        target_rmse=getattr(job, "target_rmse", None),
        target_max_error=getattr(job, "target_max_error", None),
        min_pass_rate=getattr(job, "min_pass_rate", 0.8),
    )
    return compile_outcome_contract(
        objective_config,
        scenario_suite,
        acceptance,
        failed_trial_weight=failed_trial_weight,
        source_scenario_suite=source_scenario_suite,
        compatibility_normalization=compatibility_normalization,
    )


def build_selection_key(
    *,
    evidence_complete: bool,
    hard_feasible: bool,
    hard_constraint_violation: float,
    training_failure_rate: float,
    decision_loss: float,
) -> dict[str, object]:
    if (
        not math.isfinite(hard_constraint_violation)
        or hard_constraint_violation < 0
        or not math.isfinite(training_failure_rate)
        or training_failure_rate < 0
        or training_failure_rate > 1
        or not math.isfinite(decision_loss)
    ):
        raise ValueError(
            "selection-key violations/rates must be non-negative and all values finite"
        )
    return {
        "schema_version": SELECTION_KEY_SCHEMA_VERSION,
        "evidence_complete": evidence_complete,
        "hard_feasible": hard_feasible,
        "hard_constraint_violation": hard_constraint_violation,
        "training_failure_rate": training_failure_rate,
        "decision_loss": decision_loss,
    }


def selection_order_key(
    aggregate: object,
    aggregated_score: object,
) -> tuple[int, int, float, float, float]:
    """Return the shared lexicographic order used by numerical and public paths."""

    fallback = (
        float(aggregated_score)
        if isinstance(aggregated_score, int | float)
        and not isinstance(aggregated_score, bool)
        and math.isfinite(float(aggregated_score))
        else float("inf")
    )
    if not isinstance(aggregate, dict):
        return (0 if math.isfinite(fallback) else 1, 0, 0.0, 0.0, fallback)
    key = aggregate.get("selection_key")
    if not isinstance(key, dict) or key.get("schema_version") != SELECTION_KEY_SCHEMA_VERSION:
        return (0 if math.isfinite(fallback) else 1, 0, 0.0, 0.0, fallback)

    def finite_nonnegative(name: str) -> float | None:
        value = key.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            return None
        return float(value)

    hard_violation = finite_nonnegative("hard_constraint_violation")
    failure_rate = finite_nonnegative("training_failure_rate")
    if failure_rate is not None and failure_rate > 1:
        failure_rate = None
    raw_decision_loss = key.get("decision_loss")
    decision_loss = (
        float(raw_decision_loss)
        if isinstance(raw_decision_loss, int | float)
        and not isinstance(raw_decision_loss, bool)
        and math.isfinite(float(raw_decision_loss))
        else None
    )
    evidence_complete = key.get("evidence_complete")
    hard_feasible = key.get("hard_feasible")
    if (
        not isinstance(evidence_complete, bool)
        or not isinstance(hard_feasible, bool)
        or hard_violation is None
        or failure_rate is None
        or decision_loss is None
    ):
        return (1, 1, float("inf"), float("inf"), fallback)
    return (
        0 if evidence_complete else 1,
        0 if hard_feasible else 1,
        0.0 if hard_feasible else hard_violation,
        failure_rate,
        decision_loss,
    )


__all__ = [
    "OUTCOME_CONTRACT_COMPILER_VERSION",
    "OUTCOME_CONTRACT_SCHEMA",
    "OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT",
    "SELECTION_KEY_SCHEMA_VERSION",
    "OptimizationOutcomeContractV1",
    "build_selection_key",
    "compile_job_outcome_contract",
    "compile_outcome_contract",
    "selection_order_key",
]
