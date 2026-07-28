"""Content-addressed validation evidence for scenario generalization.

The adaptive optimizer must never learn from validation outcomes.  This module
therefore compiles only a report/promotion projection after validation Trials
have run.  It makes the observed train-to-validation shift explicit without
claiming real-flight or open-world generalization.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app import schemas

GENERALIZATION_EVIDENCE_SCHEMA = "dronedream.validation-generalization-evidence/v1"

ValidationStatus = Literal["passed", "failed", "incomplete", "error"]
ShiftAxis = Literal[
    "replicated_validation",
    "seed_shift",
    "configuration_shift",
    "scenario_type_shift",
]
ClaimScope = Literal[
    "repeatability",
    "seed_robustness",
    "configuration_robustness",
    "scenario_type_robustness",
    "mixed_shift_robustness",
]
ObservedShift = Literal["improved_or_equal", "degraded", "mixed"]
Assessment = Literal[
    "not_assessable",
    "failed_validation",
    "qualified_improved_or_equal",
    "qualified_with_degradation",
]

_VALIDATION_STATUSES = frozenset({"passed", "failed", "incomplete", "error"})
_SHIFT_AXIS_ORDER: dict[ShiftAxis, int] = {
    "replicated_validation": 0,
    "seed_shift": 1,
    "configuration_shift": 2,
    "scenario_type_shift": 3,
}
_FLOAT_EPSILON = 1e-12


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class GeneralizationObjectiveGap(_FrozenModel):
    metric: str = Field(min_length=1, max_length=128)
    direction: Literal["minimize", "maximize"]
    training_value: float
    validation_value: float
    signed_degradation: float
    relative_degradation: float | None
    degraded: bool
    improved: bool

    @model_validator(mode="after")
    def _validate_directional_gap(self) -> GeneralizationObjectiveGap:
        expected = (
            self.validation_value - self.training_value
            if self.direction == "minimize"
            else self.training_value - self.validation_value
        )
        if not math.isclose(
            self.signed_degradation,
            expected,
            rel_tol=0.0,
            abs_tol=_FLOAT_EPSILON,
        ):
            raise ValueError("objective degradation is inconsistent with direction")
        if self.degraded != (expected > _FLOAT_EPSILON):
            raise ValueError("objective degraded flag is inconsistent")
        if self.improved != (expected < -_FLOAT_EPSILON):
            raise ValueError("objective improved flag is inconsistent")
        if self.degraded and self.improved:
            raise ValueError("an objective cannot improve and degrade simultaneously")
        return self


class CandidateGeneralizationEvidence(_FrozenModel):
    schema_id: Literal["dronedream.validation-generalization-evidence/v1"] = (
        "dronedream.validation-generalization-evidence/v1"
    )
    evidence_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: Literal["validation_report_only_no_adaptive_feedback"] = (
        "validation_report_only_no_adaptive_feedback"
    )
    outcome_contract_id: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    scenario_suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_status: ValidationStatus
    evidence_complete: bool
    qualified: bool
    assessment: Assessment
    claim_scope: ClaimScope
    shift_axes: tuple[ShiftAxis, ...] = Field(min_length=1, max_length=4)
    training_case_count: int = Field(ge=1)
    validation_case_count: int = Field(ge=1)
    validation_replicate_count: int = Field(ge=1)
    validation_trial_count: int = Field(ge=1)
    validation_completed_trial_count: int = Field(ge=0)
    novel_scenario_type_case_count: int = Field(ge=0)
    configuration_shift_case_count: int = Field(ge=0)
    disjoint_seed_case_count: int = Field(ge=0)
    training_validation_seed_overlap_count: int = Field(ge=0)
    objective_gaps: tuple[GeneralizationObjectiveGap, ...] = ()
    degraded_objective_count: int = Field(ge=0)
    improved_objective_count: int = Field(ge=0)
    observed_shift: ObservedShift | None
    training_scalar_loss: float | None
    validation_scalar_loss: float | None
    scalar_loss_degradation: float | None
    scalar_loss_relative_degradation: float | None

    @model_validator(mode="after")
    def _validate_evidence_state(self) -> CandidateGeneralizationEvidence:
        if tuple(sorted(self.shift_axes, key=_SHIFT_AXIS_ORDER.__getitem__)) != self.shift_axes:
            raise ValueError("generalization shift axes must be canonical")
        if len(set(self.shift_axes)) != len(self.shift_axes):
            raise ValueError("generalization shift axes must be unique")
        if self.novel_scenario_type_case_count > self.validation_case_count:
            raise ValueError("novel scenario type count exceeds validation cases")
        if self.configuration_shift_case_count > self.validation_case_count:
            raise ValueError("configuration shift count exceeds validation cases")
        if self.disjoint_seed_case_count > self.validation_case_count:
            raise ValueError("disjoint seed count exceeds validation cases")
        if self.validation_completed_trial_count > self.validation_trial_count:
            raise ValueError("completed validation Trial count exceeds actual count")
        if self.degraded_objective_count != sum(item.degraded for item in self.objective_gaps):
            raise ValueError("degraded objective count does not match objective gaps")
        if self.improved_objective_count != sum(item.improved for item in self.objective_gaps):
            raise ValueError("improved objective count does not match objective gaps")
        scalar_fields = (
            self.training_scalar_loss,
            self.validation_scalar_loss,
            self.scalar_loss_degradation,
        )
        has_assessment = bool(self.objective_gaps) and all(
            value is not None for value in scalar_fields
        )
        matrix_complete = (
            self.validation_trial_count == self.validation_replicate_count
            and self.validation_completed_trial_count == self.validation_replicate_count
        )
        if self.evidence_complete != (has_assessment and matrix_complete):
            raise ValueError("generalization completeness does not match metric evidence")
        if self.qualified != (self.validation_status == "passed" and self.evidence_complete):
            raise ValueError("generalization qualification does not match validation")
        expected_shift: ObservedShift | None
        if not self.evidence_complete:
            expected_shift = None
        elif self.degraded_objective_count and self.improved_objective_count:
            expected_shift = "mixed"
        elif self.degraded_objective_count:
            expected_shift = "degraded"
        else:
            expected_shift = "improved_or_equal"
        if self.observed_shift != expected_shift:
            raise ValueError("observed shift does not match objective gaps")
        expected_assessment: Assessment
        if not self.evidence_complete:
            expected_assessment = "not_assessable"
        elif not self.qualified:
            expected_assessment = "failed_validation"
        elif self.degraded_objective_count:
            expected_assessment = "qualified_with_degradation"
        else:
            expected_assessment = "qualified_improved_or_equal"
        if self.assessment != expected_assessment:
            raise ValueError("generalization assessment is inconsistent")
        if all(value is not None for value in scalar_fields):
            assert self.training_scalar_loss is not None
            assert self.validation_scalar_loss is not None
            assert self.scalar_loss_degradation is not None
            expected_scalar_gap = self.validation_scalar_loss - self.training_scalar_loss
            if not math.isclose(
                self.scalar_loss_degradation,
                expected_scalar_gap,
                rel_tol=0.0,
                abs_tol=_FLOAT_EPSILON,
            ):
                raise ValueError("scalar-loss degradation is inconsistent")
        elif any(value is not None for value in scalar_fields):
            raise ValueError("scalar-loss evidence must be complete or absent")
        return self


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


def _finite_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be a finite number")
    return result


def _case_config_sha256(case: schemas.ScenarioCaseConfig) -> str:
    return _sha256(case.config)


def _shift_summary(
    scenario_suite: schemas.ScenarioSuiteConfig,
) -> tuple[
    tuple[ShiftAxis, ...],
    ClaimScope,
    int,
    int,
    int,
    int,
]:
    training = [case for case in scenario_suite.cases if case.enabled and not case.holdout]
    validation = [case for case in scenario_suite.cases if case.enabled and case.holdout]
    if not training or not validation:
        raise ValueError("generalization evidence requires training and validation cases")

    training_types = {case.scenario_type for case in training}
    training_config_pairs = {(case.scenario_type, _case_config_sha256(case)) for case in training}
    training_seeds = {seed for case in training for seed in case.seeds}
    validation_seeds = {seed for case in validation for seed in case.seeds}
    axes: set[ShiftAxis] = set()
    novel_type_count = 0
    configuration_shift_count = 0
    disjoint_seed_count = 0
    for case in validation:
        config_pair = (case.scenario_type, _case_config_sha256(case))
        if case.scenario_type not in training_types:
            axes.add("scenario_type_shift")
            novel_type_count += 1
        elif config_pair not in training_config_pairs:
            axes.add("configuration_shift")
            configuration_shift_count += 1
        elif set(case.seeds).isdisjoint(training_seeds):
            axes.add("seed_shift")
            disjoint_seed_count += 1
        else:
            axes.add("replicated_validation")
    ordered_axes = tuple(sorted(axes, key=_SHIFT_AXIS_ORDER.__getitem__))
    if len(ordered_axes) > 1:
        claim_scope: ClaimScope = "mixed_shift_robustness"
    else:
        claim_scope = cast(
            ClaimScope,
            {
                "replicated_validation": "repeatability",
                "seed_shift": "seed_robustness",
                "configuration_shift": "configuration_robustness",
                "scenario_type_shift": "scenario_type_robustness",
            }[ordered_axes[0]],
        )
    return (
        ordered_axes,
        claim_scope,
        novel_type_count,
        configuration_shift_count,
        disjoint_seed_count,
        len(training_seeds & validation_seeds),
    )


def _objective_gaps(
    objective_config: schemas.ObjectiveConfig,
    *,
    training_objectives: Mapping[str, object] | None,
    validation_objectives: Mapping[str, object] | None,
) -> tuple[GeneralizationObjectiveGap, ...]:
    if training_objectives is None or validation_objectives is None:
        return ()
    gaps: list[GeneralizationObjectiveGap] = []
    for objective in objective_config.objectives:
        training_value = _finite_number(
            training_objectives.get(objective.metric),
            field_name=f"training objective {objective.metric}",
        )
        validation_value = _finite_number(
            validation_objectives.get(objective.metric),
            field_name=f"validation objective {objective.metric}",
        )
        signed_degradation = (
            validation_value - training_value
            if objective.direction == "minimize"
            else training_value - validation_value
        )
        relative_degradation = (
            signed_degradation / abs(training_value)
            if abs(training_value) > _FLOAT_EPSILON
            else None
        )
        gaps.append(
            GeneralizationObjectiveGap(
                metric=objective.metric,
                direction=objective.direction,
                training_value=training_value,
                validation_value=validation_value,
                signed_degradation=signed_degradation,
                relative_degradation=relative_degradation,
                degraded=signed_degradation > _FLOAT_EPSILON,
                improved=signed_degradation < -_FLOAT_EPSILON,
            )
        )
    return tuple(gaps)


def compile_candidate_generalization_evidence(
    *,
    objective_config: schemas.ObjectiveConfig,
    scenario_suite: schemas.ScenarioSuiteConfig,
    validation_status: str,
    validation_trial_count: int,
    validation_completed_trial_count: int,
    training_objectives: Mapping[str, object] | None,
    validation_objectives: Mapping[str, object] | None,
    training_scalar_loss: object | None,
    validation_scalar_loss: object | None,
    outcome_contract_id: str | None = None,
    scenario_suite_sha256: str | None = None,
) -> CandidateGeneralizationEvidence:
    """Compile a report-only, content-addressed train/validation shift receipt."""

    if validation_status not in _VALIDATION_STATUSES:
        raise ValueError("unsupported validation status")
    typed_status = cast(ValidationStatus, validation_status)
    if validation_trial_count < 1:
        raise ValueError("generalization evidence requires validation Trials")
    if not 0 <= validation_completed_trial_count <= validation_trial_count:
        raise ValueError("invalid completed validation Trial count")

    training_cases = [case for case in scenario_suite.cases if case.enabled and not case.holdout]
    validation_cases = [case for case in scenario_suite.cases if case.enabled and case.holdout]
    (
        shift_axes,
        claim_scope,
        novel_type_count,
        configuration_shift_count,
        disjoint_seed_count,
        seed_overlap_count,
    ) = _shift_summary(scenario_suite)

    evaluation_available = (
        training_objectives is not None
        and validation_objectives is not None
        and training_scalar_loss is not None
        and validation_scalar_loss is not None
        and validation_trial_count == sum(len(case.seeds) for case in validation_cases)
        and validation_completed_trial_count == validation_trial_count
        and typed_status not in {"incomplete", "error"}
    )
    objective_gaps = (
        _objective_gaps(
            objective_config,
            training_objectives=training_objectives,
            validation_objectives=validation_objectives,
        )
        if evaluation_available
        else ()
    )
    training_loss = (
        _finite_number(training_scalar_loss, field_name="training scalar loss")
        if evaluation_available
        else None
    )
    validation_loss = (
        _finite_number(validation_scalar_loss, field_name="validation scalar loss")
        if evaluation_available
        else None
    )
    scalar_gap = (
        validation_loss - training_loss
        if training_loss is not None and validation_loss is not None
        else None
    )
    scalar_relative_gap = (
        scalar_gap / abs(training_loss)
        if scalar_gap is not None
        and training_loss is not None
        and abs(training_loss) > _FLOAT_EPSILON
        else None
    )
    evidence_complete = (
        evaluation_available
        and bool(objective_gaps)
        and validation_completed_trial_count == validation_trial_count
    )
    qualified = typed_status == "passed" and evidence_complete
    degraded_count = sum(item.degraded for item in objective_gaps)
    improved_count = sum(item.improved for item in objective_gaps)
    if not evidence_complete:
        observed_shift: ObservedShift | None = None
        assessment: Assessment = "not_assessable"
    elif degraded_count and improved_count:
        observed_shift = "mixed"
        assessment = "qualified_with_degradation" if qualified else "failed_validation"
    elif degraded_count:
        observed_shift = "degraded"
        assessment = "qualified_with_degradation" if qualified else "failed_validation"
    else:
        observed_shift = "improved_or_equal"
        assessment = "qualified_improved_or_equal" if qualified else "failed_validation"

    computed_suite_sha = _sha256(scenario_suite.model_dump(mode="json"))
    if scenario_suite_sha256 is not None and scenario_suite_sha256 != computed_suite_sha:
        raise ValueError("scenario suite SHA-256 does not match generalization input")
    suite_sha = computed_suite_sha
    payload = {
        "schema_id": GENERALIZATION_EVIDENCE_SCHEMA,
        "role": "validation_report_only_no_adaptive_feedback",
        "outcome_contract_id": outcome_contract_id,
        "scenario_suite_sha256": suite_sha,
        "validation_status": typed_status,
        "evidence_complete": evidence_complete,
        "qualified": qualified,
        "assessment": assessment,
        "claim_scope": claim_scope,
        "shift_axes": list(shift_axes),
        "training_case_count": len(training_cases),
        "validation_case_count": len(validation_cases),
        "validation_replicate_count": sum(len(case.seeds) for case in validation_cases),
        "validation_trial_count": validation_trial_count,
        "validation_completed_trial_count": validation_completed_trial_count,
        "novel_scenario_type_case_count": novel_type_count,
        "configuration_shift_case_count": configuration_shift_count,
        "disjoint_seed_case_count": disjoint_seed_count,
        "training_validation_seed_overlap_count": seed_overlap_count,
        "objective_gaps": [item.model_dump(mode="json") for item in objective_gaps],
        "degraded_objective_count": degraded_count,
        "improved_objective_count": improved_count,
        "observed_shift": observed_shift,
        "training_scalar_loss": training_loss,
        "validation_scalar_loss": validation_loss,
        "scalar_loss_degradation": scalar_gap,
        "scalar_loss_relative_degradation": scalar_relative_gap,
    }
    return CandidateGeneralizationEvidence.model_validate(
        {
            "evidence_id": _sha256(payload),
            **payload,
        }
    )


def verify_candidate_generalization_evidence(
    value: object,
) -> CandidateGeneralizationEvidence | None:
    """Return verified evidence, rejecting structural or content-hash drift."""

    try:
        evidence = CandidateGeneralizationEvidence.model_validate(value)
    except ValidationError:
        return None
    payload = evidence.model_dump(mode="json", exclude={"evidence_id"})
    if evidence.evidence_id != _sha256(payload):
        return None
    return evidence


__all__ = [
    "GENERALIZATION_EVIDENCE_SCHEMA",
    "CandidateGeneralizationEvidence",
    "GeneralizationObjectiveGap",
    "compile_candidate_generalization_evidence",
    "verify_candidate_generalization_evidence",
]
