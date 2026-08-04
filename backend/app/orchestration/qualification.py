"""Deterministic two-stage screening and sealed qualification policy.

The proposal loop must never receive the holdout observations consumed here.
This module is intentionally provider-neutral: it accepts only terminal,
secret-free Trial receipts and returns a bounded dispatch/terminal decision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.optimization.scenarios import ScenarioRun, holdout_matrix, training_matrix
from app.schemas import ScenarioSuiteConfig

QUALIFICATION_CONTRACT_SCHEMA = "dronedream.candidate-qualification/v1"
QUALIFICATION_TRIAL_RECEIPT_SCHEMA = "dronedream.qualification-trial-receipt/v1"
QUALIFICATION_RULE_VERSION: Literal["screen-4-sealed-9of10-8to20-18of20/v1"] = (
    "screen-4-sealed-9of10-8to20-18of20/v1"
)
SEALED_QUALIFICATION_POLICY_VERSION: Literal["sealed-two-stage-v1"] = "sealed-two-stage-v1"
SEALED_QUALIFICATION_HOLDOUT_SCHEMA: Literal["dronedream.sealed-qualification-holdout/v1"] = (
    "dronedream.sealed-qualification-holdout/v1"
)

QualificationPhase = Literal["screening", "qualification"]
QualificationTerminalStatus = Literal[
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "INDETERMINATE",
]
QualificationState = Literal[
    "screening",
    "screening_failed",
    "sealed_qualification",
    "qualification_10",
    "qualification_extended_20",
    "qualified",
    "qualification_failed",
    "indeterminate",
]
QualificationAction = Literal[
    "dispatch_screening",
    "seal_and_dispatch_qualification",
    "dispatch_qualification_extension",
    "wait",
    "stop_qualified",
    "stop_failed",
    "stop_indeterminate",
]


class QualificationContractError(ValueError):
    """Raised when receipts violate ordering, phase, or evidence contracts."""


class _FrozenContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class QualificationScenarioRunV1(_FrozenContract):
    """One exact scenario/seed dispatch in the sealed qualification contract."""

    ordinal: int = Field(ge=1, le=20)
    phase: QualificationPhase
    case_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    scenario_type: str = Field(min_length=1, max_length=64)
    seed: int = Field(ge=0, le=2_147_483_647)
    weight: float = Field(gt=0.0, le=1000.0)
    holdout: bool
    config_json: str = Field(min_length=2, max_length=65_536)

    @field_validator("config_json")
    @classmethod
    def _validate_canonical_config_json(cls, value: str) -> str:
        try:
            parsed = json.loads(value)
            canonical = _canonical_json(parsed)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("scenario config must be finite canonical JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("scenario config must be a JSON object")
        if value != canonical:
            raise ValueError("scenario config JSON must use canonical encoding")
        return value

    def config_dict(self) -> dict[str, Any]:
        parsed = json.loads(self.config_json)
        if not isinstance(parsed, dict):  # pragma: no cover - guarded by validation
            raise QualificationContractError("frozen scenario config is not an object")
        return parsed

    @model_validator(mode="after")
    def _validate_phase_role(self) -> QualificationScenarioRunV1:
        if self.holdout is not (self.phase == "qualification"):
            raise ValueError("qualification scenario phase and holdout role diverged")
        return self


class SealedQualificationHoldoutContractV1(_FrozenContract):
    """Exactly four visible screening and twenty hidden qualification runs."""

    contract_schema: Literal["dronedream.sealed-qualification-holdout/v1"] = (
        SEALED_QUALIFICATION_HOLDOUT_SCHEMA
    )
    policy_version: Literal["sealed-two-stage-v1"] = SEALED_QUALIFICATION_POLICY_VERSION
    rule_version: Literal["screen-4-sealed-9of10-8to20-18of20/v1"] = QUALIFICATION_RULE_VERSION
    rule_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    common_random_numbers: bool
    screening: tuple[QualificationScenarioRunV1, ...]
    qualification: tuple[QualificationScenarioRunV1, ...]
    provider_visibility: Literal["screening_only_qualification_never_visible"] = (
        "screening_only_qualification_never_visible"
    )

    @model_validator(mode="after")
    def _validate_frozen_matrix(self) -> SealedQualificationHoldoutContractV1:
        if len(self.screening) != RULE_V1.screening_required:
            raise ValueError("sealed qualification requires exactly four screening runs")
        if len(self.qualification) != RULE_V1.qualification_extended_required:
            raise ValueError("sealed qualification requires exactly twenty holdout runs")
        if [item.phase for item in self.screening] != ["screening"] * 4:
            raise ValueError("screening matrix contains a qualification run")
        if [item.ordinal for item in self.screening] != list(range(1, 5)):
            raise ValueError("screening ordinals must be contiguous from one")
        if [item.phase for item in self.qualification] != ["qualification"] * 20:
            raise ValueError("qualification matrix contains a screening run")
        if [item.ordinal for item in self.qualification] != list(range(1, 21)):
            raise ValueError("qualification ordinals must be contiguous from one")
        screening_keys = {(item.case_id, item.seed) for item in self.screening}
        qualification_keys = {(item.case_id, item.seed) for item in self.qualification}
        if len(screening_keys) != 4 or len(qualification_keys) != 20:
            raise ValueError("qualification scenario/seed pairs must be unique")
        screening_seeds = {item.seed for item in self.screening}
        qualification_seeds = {item.seed for item in self.qualification}
        if screening_seeds & qualification_seeds:
            raise ValueError("screening and qualification seeds must be disjoint")
        return self


@dataclass(frozen=True)
class QualificationRuleV1:
    screening_required: int = 4
    qualification_initial_required: int = 10
    qualification_extended_required: int = 20
    direct_pass_min: int = 9
    extension_trigger_passes: int = 8
    extended_pass_min: int = 18
    max_candidates_per_run: int = 2

    def manifest(self) -> dict[str, object]:
        return {
            "contract_schema": QUALIFICATION_CONTRACT_SCHEMA,
            "rule_version": QUALIFICATION_RULE_VERSION,
            "screening_required": self.screening_required,
            "qualification_initial_required": self.qualification_initial_required,
            "qualification_extended_required": self.qualification_extended_required,
            "direct_pass_min": self.direct_pass_min,
            "extension_trigger_passes": self.extension_trigger_passes,
            "extended_pass_min": self.extended_pass_min,
            "max_candidates_per_run": self.max_candidates_per_run,
            "safety_critical_failure_limit": 0,
            "effect_readback_required_for_every_trial": True,
            "evidence_required_for_every_trial": True,
            "holdout_visibility": "sealed_not_provider_visible",
        }


RULE_V1 = QualificationRuleV1()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def qualification_rule_sha256(rule: QualificationRuleV1 = RULE_V1) -> str:
    return hashlib.sha256(_canonical_json(rule.manifest()).encode("utf-8")).hexdigest()


QUALIFICATION_RULE_SHA256 = qualification_rule_sha256()


def compile_sealed_qualification_contract(
    suite: ScenarioSuiteConfig,
) -> SealedQualificationHoldoutContractV1:
    """Compile a fail-closed 4+20 matrix without generating or guessing seeds."""

    screening_runs = training_matrix(suite)
    qualification_runs = holdout_matrix(suite)
    if len(screening_runs) != RULE_V1.screening_required:
        raise QualificationContractError(
            "sealed qualification suite must preregister exactly four screening runs"
        )
    if len(qualification_runs) != RULE_V1.qualification_extended_required:
        raise QualificationContractError(
            "sealed qualification suite must preregister exactly twenty holdout runs"
        )

    def freeze_run(
        *,
        run: ScenarioRun,
        phase: QualificationPhase,
        ordinal: int,
    ) -> QualificationScenarioRunV1:
        try:
            return QualificationScenarioRunV1(
                ordinal=ordinal,
                phase=phase,
                case_id=run.case_id,
                scenario_type=run.scenario_type,
                seed=run.seed,
                weight=run.weight,
                holdout=run.holdout,
                config_json=_canonical_json(run.config),
            )
        except (TypeError, ValueError) as exc:
            raise QualificationContractError(
                "scenario suite cannot be frozen as a qualification run"
            ) from exc

    try:
        return SealedQualificationHoldoutContractV1(
            rule_sha256=QUALIFICATION_RULE_SHA256,
            common_random_numbers=suite.common_random_numbers,
            screening=tuple(
                freeze_run(run=run, phase="screening", ordinal=index)
                for index, run in enumerate(screening_runs, start=1)
            ),
            qualification=tuple(
                freeze_run(run=run, phase="qualification", ordinal=index)
                for index, run in enumerate(qualification_runs, start=1)
            ),
        )
    except (TypeError, ValueError) as exc:
        raise QualificationContractError(
            "scenario suite violates the sealed qualification contract"
        ) from exc


def sealed_qualification_contract_sha256(
    contract: SealedQualificationHoldoutContractV1,
) -> str:
    return hashlib.sha256(
        _canonical_json(contract.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class QualificationTrialObservation:
    phase: QualificationPhase
    ordinal: int
    terminal_status: QualificationTerminalStatus
    passed: bool
    safety_critical_failure: bool
    effect_readback_complete: bool
    evidence_complete: bool
    evidence_id: str


@dataclass(frozen=True)
class QualificationProgress:
    state: QualificationState
    action: QualificationAction
    reason: str
    next_phase: QualificationPhase | None
    next_ordinals: tuple[int, ...]
    screening_attempted: int
    screening_passed: int
    qualification_attempted: int
    qualification_passed: int
    qualification_target: int
    terminal: bool
    qualified: bool
    sealed: bool


def _validated_phase(
    observations: tuple[QualificationTrialObservation, ...],
    *,
    phase: QualificationPhase,
    limit: int,
) -> tuple[QualificationTrialObservation, ...]:
    selected = tuple(item for item in observations if item.phase == phase)
    ordinals = [item.ordinal for item in selected]
    if any(ordinal < 1 or ordinal > limit for ordinal in ordinals):
        raise QualificationContractError(f"{phase} ordinal exceeds the frozen limit")
    if len(ordinals) != len(set(ordinals)):
        raise QualificationContractError(f"duplicate {phase} ordinal")
    ordered = tuple(sorted(selected, key=lambda item: item.ordinal))
    expected = list(range(1, len(ordered) + 1))
    if [item.ordinal for item in ordered] != expected:
        raise QualificationContractError(f"{phase} receipts must be contiguous from ordinal 1")
    for item in ordered:
        if not item.evidence_id.startswith("sha256:") or len(item.evidence_id) != 71:
            raise QualificationContractError(f"{phase} receipt has an invalid evidence id")
        digest = item.evidence_id.removeprefix("sha256:")
        if any(character not in "0123456789abcdef" for character in digest):
            raise QualificationContractError(f"{phase} receipt has an invalid evidence id")
        if item.passed and (
            item.terminal_status != "COMPLETED"
            or item.safety_critical_failure
            or not item.effect_readback_complete
            or not item.evidence_complete
        ):
            raise QualificationContractError(
                f"passing {phase} receipt lacks complete, safe terminal evidence"
            )
    return ordered


def _progress(
    *,
    state: QualificationState,
    action: QualificationAction,
    reason: str,
    screening: tuple[QualificationTrialObservation, ...],
    qualification: tuple[QualificationTrialObservation, ...],
    target: int,
    next_phase: QualificationPhase | None = None,
    next_ordinals: tuple[int, ...] = (),
    terminal: bool = False,
    qualified: bool = False,
    sealed: bool = False,
) -> QualificationProgress:
    return QualificationProgress(
        state=state,
        action=action,
        reason=reason,
        next_phase=next_phase,
        next_ordinals=next_ordinals,
        screening_attempted=len(screening),
        screening_passed=sum(item.passed for item in screening),
        qualification_attempted=len(qualification),
        qualification_passed=sum(item.passed for item in qualification),
        qualification_target=target,
        terminal=terminal,
        qualified=qualified,
        sealed=sealed,
    )


def evaluate_qualification_progress(
    observations: tuple[QualificationTrialObservation, ...],
    *,
    rule: QualificationRuleV1 = RULE_V1,
) -> QualificationProgress:
    """Return the only legal next action for the frozen Trial receipts."""

    if rule != RULE_V1:
        raise QualificationContractError("unregistered qualification rule")
    screening = _validated_phase(
        observations,
        phase="screening",
        limit=rule.screening_required,
    )
    qualification = _validated_phase(
        observations,
        phase="qualification",
        limit=rule.qualification_extended_required,
    )
    if qualification and len(screening) != rule.screening_required:
        raise QualificationContractError(
            "qualification receipts cannot exist before four screening receipts"
        )
    if qualification and not all(item.passed for item in screening):
        raise QualificationContractError(
            "qualification receipts cannot follow a failed screening gate"
        )

    for item in screening:
        if item.terminal_status == "INDETERMINATE" or not item.evidence_complete:
            return _progress(
                state="indeterminate",
                action="stop_indeterminate",
                reason="screening_evidence_indeterminate",
                screening=screening,
                qualification=qualification,
                target=rule.qualification_initial_required,
                terminal=True,
            )
        if item.safety_critical_failure or not item.effect_readback_complete:
            return _progress(
                state="screening_failed",
                action="stop_failed",
                reason="screening_safety_or_effect_gate_failed",
                screening=screening,
                qualification=qualification,
                target=rule.qualification_initial_required,
                terminal=True,
            )
        if not item.passed:
            return _progress(
                state="screening_failed",
                action="stop_failed",
                reason="screening_repeat_failed",
                screening=screening,
                qualification=qualification,
                target=rule.qualification_initial_required,
                terminal=True,
            )

    if len(screening) < rule.screening_required:
        return _progress(
            state="screening",
            action="dispatch_screening",
            reason="screening_repeats_remaining",
            screening=screening,
            qualification=qualification,
            target=rule.qualification_initial_required,
            next_phase="screening",
            next_ordinals=tuple(range(len(screening) + 1, rule.screening_required + 1)),
        )

    if not qualification:
        return _progress(
            state="sealed_qualification",
            action="seal_and_dispatch_qualification",
            reason="screening_gate_passed",
            screening=screening,
            qualification=qualification,
            target=rule.qualification_initial_required,
            next_phase="qualification",
            next_ordinals=tuple(range(1, rule.qualification_initial_required + 1)),
            sealed=True,
        )

    for item in qualification:
        if item.terminal_status == "INDETERMINATE" or not item.evidence_complete:
            return _progress(
                state="indeterminate",
                action="stop_indeterminate",
                reason="qualification_evidence_indeterminate",
                screening=screening,
                qualification=qualification,
                target=(
                    rule.qualification_extended_required
                    if len(qualification) > rule.qualification_initial_required
                    else rule.qualification_initial_required
                ),
                terminal=True,
                sealed=True,
            )
        if item.safety_critical_failure or not item.effect_readback_complete:
            return _progress(
                state="qualification_failed",
                action="stop_failed",
                reason="qualification_safety_or_effect_gate_failed",
                screening=screening,
                qualification=qualification,
                target=(
                    rule.qualification_extended_required
                    if len(qualification) > rule.qualification_initial_required
                    else rule.qualification_initial_required
                ),
                terminal=True,
                sealed=True,
            )

    if len(qualification) < rule.qualification_initial_required:
        return _progress(
            state="qualification_10",
            action="wait",
            reason="initial_qualification_in_flight",
            screening=screening,
            qualification=qualification,
            target=rule.qualification_initial_required,
            next_phase="qualification",
            next_ordinals=tuple(
                range(len(qualification) + 1, rule.qualification_initial_required + 1)
            ),
            sealed=True,
        )

    initial_passes = sum(item.passed for item in qualification[:10])
    if len(qualification) == rule.qualification_initial_required:
        if initial_passes >= rule.direct_pass_min:
            return _progress(
                state="qualified",
                action="stop_qualified",
                reason="direct_9_of_10_qualification_passed",
                screening=screening,
                qualification=qualification,
                target=rule.qualification_initial_required,
                terminal=True,
                qualified=True,
                sealed=True,
            )
        if initial_passes == rule.extension_trigger_passes:
            return _progress(
                state="qualification_extended_20",
                action="dispatch_qualification_extension",
                reason="exactly_8_of_10_requires_deterministic_extension",
                screening=screening,
                qualification=qualification,
                target=rule.qualification_extended_required,
                next_phase="qualification",
                next_ordinals=tuple(
                    range(
                        rule.qualification_initial_required + 1,
                        rule.qualification_extended_required + 1,
                    )
                ),
                sealed=True,
            )
        return _progress(
            state="qualification_failed",
            action="stop_failed",
            reason="initial_qualification_below_8_of_10",
            screening=screening,
            qualification=qualification,
            target=rule.qualification_initial_required,
            terminal=True,
            sealed=True,
        )

    if initial_passes != rule.extension_trigger_passes:
        raise QualificationContractError(
            "extended receipts require exactly 8 passes in the first ten"
        )
    if len(qualification) < rule.qualification_extended_required:
        return _progress(
            state="qualification_extended_20",
            action="wait",
            reason="deterministic_extension_in_flight",
            screening=screening,
            qualification=qualification,
            target=rule.qualification_extended_required,
            next_phase="qualification",
            next_ordinals=tuple(
                range(len(qualification) + 1, rule.qualification_extended_required + 1)
            ),
            sealed=True,
        )

    total_passes = sum(item.passed for item in qualification)
    if total_passes >= rule.extended_pass_min:
        return _progress(
            state="qualified",
            action="stop_qualified",
            reason="extended_18_of_20_qualification_passed",
            screening=screening,
            qualification=qualification,
            target=rule.qualification_extended_required,
            terminal=True,
            qualified=True,
            sealed=True,
        )
    return _progress(
        state="qualification_failed",
        action="stop_failed",
        reason="extended_qualification_below_18_of_20",
        screening=screening,
        qualification=qualification,
        target=rule.qualification_extended_required,
        terminal=True,
        sealed=True,
    )


__all__ = [
    "QUALIFICATION_CONTRACT_SCHEMA",
    "QUALIFICATION_RULE_SHA256",
    "QUALIFICATION_RULE_VERSION",
    "QUALIFICATION_TRIAL_RECEIPT_SCHEMA",
    "SEALED_QUALIFICATION_HOLDOUT_SCHEMA",
    "SEALED_QUALIFICATION_POLICY_VERSION",
    "QualificationContractError",
    "QualificationProgress",
    "QualificationRuleV1",
    "QualificationScenarioRunV1",
    "QualificationTrialObservation",
    "RULE_V1",
    "SealedQualificationHoldoutContractV1",
    "compile_sealed_qualification_contract",
    "evaluate_qualification_progress",
    "qualification_rule_sha256",
    "sealed_qualification_contract_sha256",
]
