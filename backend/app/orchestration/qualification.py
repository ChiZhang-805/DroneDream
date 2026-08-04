"""Deterministic two-stage screening and sealed qualification policy.

The proposal loop must never receive the holdout observations consumed here.
This module is intentionally provider-neutral: it accepts only terminal,
secret-free Trial receipts and returns a bounded dispatch/terminal decision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

QUALIFICATION_CONTRACT_SCHEMA = "dronedream.candidate-qualification/v1"
QUALIFICATION_TRIAL_RECEIPT_SCHEMA = "dronedream.qualification-trial-receipt/v1"
QUALIFICATION_RULE_VERSION = "screen-4-sealed-9of10-8to20-18of20/v1"

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
    "QualificationContractError",
    "QualificationProgress",
    "QualificationRuleV1",
    "QualificationTrialObservation",
    "RULE_V1",
    "evaluate_qualification_progress",
    "qualification_rule_sha256",
]
