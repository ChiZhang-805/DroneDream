from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from app.orchestration.qualification import (
    QUALIFICATION_RULE_SHA256,
    RULE_V1,
    SEALED_QUALIFICATION_HOLDOUT_SCHEMA,
    QualificationContractError,
    QualificationRuleV1,
    QualificationScenarioRunV1,
    QualificationTrialObservation,
    SealedQualificationHoldoutContractV1,
    compile_sealed_qualification_contract,
    evaluate_qualification_progress,
    qualification_rule_sha256,
    sealed_qualification_contract_sha256,
)
from app.schemas import ScenarioCaseConfig, ScenarioSuiteConfig


def _evidence(ordinal: int, *, phase: str) -> str:
    value = f"{phase}:{ordinal}".encode()
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _receipt(
    phase: str,
    ordinal: int,
    *,
    passed: bool = True,
    terminal_status: str = "COMPLETED",
    safety_critical_failure: bool = False,
    effect_readback_complete: bool = True,
    evidence_complete: bool = True,
) -> QualificationTrialObservation:
    return QualificationTrialObservation(
        phase=phase,  # type: ignore[arg-type]
        ordinal=ordinal,
        terminal_status=terminal_status,  # type: ignore[arg-type]
        passed=passed,
        safety_critical_failure=safety_critical_failure,
        effect_readback_complete=effect_readback_complete,
        evidence_complete=evidence_complete,
        evidence_id=_evidence(ordinal, phase=phase),
    )


def _screening(*, passed: bool = True) -> tuple[QualificationTrialObservation, ...]:
    return tuple(_receipt("screening", ordinal, passed=passed) for ordinal in range(1, 5))


def _qualification(
    passes: int,
    *,
    total: int = 10,
) -> tuple[QualificationTrialObservation, ...]:
    return tuple(
        _receipt("qualification", ordinal, passed=ordinal <= passes)
        for ordinal in range(1, total + 1)
    )


def _sealed_suite() -> ScenarioSuiteConfig:
    return ScenarioSuiteConfig(
        common_random_numbers=True,
        cases=[
            ScenarioCaseConfig(
                id="screen-nominal",
                scenario_type="nominal",
                seeds=[101, 102],
                config={"wind_mps": 0.0},
            ),
            ScenarioCaseConfig(
                id="screen-wind",
                scenario_type="wind_perturbed",
                seeds=[201, 202],
                config={"wind_mps": 2.0},
            ),
            ScenarioCaseConfig(
                id="sealed-holdout",
                scenario_type="combined_perturbed",
                seeds=list(range(901, 921)),
                holdout=True,
                config={"wind_mps": 3.0, "noise_scale": 1.1},
            ),
        ],
    )


def test_sealed_contract_freezes_exact_preregistered_4_plus_20_matrix() -> None:
    suite = _sealed_suite()
    contract = compile_sealed_qualification_contract(suite)

    assert contract.contract_schema == SEALED_QUALIFICATION_HOLDOUT_SCHEMA
    assert contract.rule_sha256 == QUALIFICATION_RULE_SHA256
    assert contract.common_random_numbers is True
    assert [item.ordinal for item in contract.screening] == [1, 2, 3, 4]
    assert [item.seed for item in contract.screening] == [101, 102, 201, 202]
    assert all(item.phase == "screening" and not item.holdout for item in contract.screening)
    assert [item.ordinal for item in contract.qualification] == list(range(1, 21))
    assert [item.seed for item in contract.qualification] == list(range(901, 921))
    assert all(item.phase == "qualification" and item.holdout for item in contract.qualification)
    assert sealed_qualification_contract_sha256(contract) == sealed_qualification_contract_sha256(
        compile_sealed_qualification_contract(suite)
    )


@pytest.mark.parametrize(
    ("screening_seeds", "holdout_seeds", "message"),
    [
        ([101, 102, 103], list(range(901, 921)), "exactly four screening"),
        ([101, 102, 103, 104, 105], list(range(901, 921)), "exactly four screening"),
        ([101, 102, 103, 104], list(range(901, 920)), "exactly twenty holdout"),
        ([101, 102, 103, 104], list(range(901, 922)), "exactly twenty holdout"),
    ],
)
def test_sealed_contract_refuses_to_guess_missing_or_extra_repeats(
    screening_seeds: list[int],
    holdout_seeds: list[int],
    message: str,
) -> None:
    suite = ScenarioSuiteConfig(
        cases=[
            ScenarioCaseConfig(id="screen", seeds=screening_seeds),
            ScenarioCaseConfig(id="holdout", seeds=holdout_seeds, holdout=True),
        ]
    )

    with pytest.raises(QualificationContractError, match=message):
        compile_sealed_qualification_contract(suite)


def test_sealed_contract_rejects_phase_role_and_duplicate_pairs() -> None:
    valid = compile_sealed_qualification_contract(_sealed_suite())
    payload = valid.model_dump(mode="json")
    payload["screening"][0]["holdout"] = True
    with pytest.raises(ValidationError, match="phase and holdout role"):
        SealedQualificationHoldoutContractV1.model_validate(payload)

    payload = valid.model_dump(mode="json")
    payload["qualification"][1]["case_id"] = payload["qualification"][0]["case_id"]
    payload["qualification"][1]["seed"] = payload["qualification"][0]["seed"]
    with pytest.raises(ValidationError, match="pairs must be unique"):
        SealedQualificationHoldoutContractV1.model_validate(payload)


def test_sealed_contract_hash_binds_scenario_config_without_mutating_source() -> None:
    suite = _sealed_suite()
    original = suite.model_dump(mode="json")
    first = compile_sealed_qualification_contract(suite)

    changed_payload = first.model_dump(mode="json")
    changed_payload["qualification"][0]["config_json"] = '{"wind_mps":4.0}'
    changed = SealedQualificationHoldoutContractV1.model_validate(changed_payload)

    assert sealed_qualification_contract_sha256(first) != sealed_qualification_contract_sha256(
        changed
    )
    assert suite.model_dump(mode="json") == original


def test_scenario_config_is_deeply_frozen_as_canonical_json() -> None:
    run = compile_sealed_qualification_contract(_sealed_suite()).qualification[0]

    assert run.config_json == '{"noise_scale":1.1,"wind_mps":3.0}'
    assert run.config_dict() == {"noise_scale": 1.1, "wind_mps": 3.0}
    with pytest.raises(ValidationError, match="canonical encoding"):
        QualificationScenarioRunV1.model_validate(
            {**run.model_dump(mode="json"), "config_json": '{"wind_mps": 3.0}'},
        )
    with pytest.raises(ValidationError, match="JSON object"):
        QualificationScenarioRunV1.model_validate(
            {**run.model_dump(mode="json"), "config_json": "[]"},
        )


def test_scenario_run_contract_forbids_unknown_fields() -> None:
    payload = (
        compile_sealed_qualification_contract(_sealed_suite()).screening[0].model_dump(mode="json")
    )
    payload["secret"] = "must-not-enter-contract"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        QualificationScenarioRunV1.model_validate(payload)


def test_rule_manifest_hash_is_canonical_and_stable() -> None:
    canonical = json.dumps(
        RULE_V1.manifest(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    assert hashlib.sha256(canonical).hexdigest() == QUALIFICATION_RULE_SHA256
    assert qualification_rule_sha256() == QUALIFICATION_RULE_SHA256
    assert len(QUALIFICATION_RULE_SHA256) == 64
    assert RULE_V1.manifest()["holdout_visibility"] == "sealed_not_provider_visible"


def test_unregistered_rule_is_rejected() -> None:
    with pytest.raises(QualificationContractError, match="unregistered"):
        evaluate_qualification_progress(
            (),
            rule=QualificationRuleV1(screening_required=3),
        )


def test_screening_dispatches_exact_missing_ordinals() -> None:
    initial = evaluate_qualification_progress(())
    partial = evaluate_qualification_progress((_receipt("screening", 1), _receipt("screening", 2)))

    assert initial.action == "dispatch_screening"
    assert initial.next_ordinals == (1, 2, 3, 4)
    assert initial.screening_attempted == 0
    assert partial.action == "dispatch_screening"
    assert partial.next_ordinals == (3, 4)
    assert partial.screening_attempted == 2
    assert partial.screening_passed == 2


@pytest.mark.parametrize(
    ("receipt", "state", "reason"),
    [
        (
            _receipt("screening", 1, passed=False),
            "screening_failed",
            "screening_repeat_failed",
        ),
        (
            _receipt("screening", 1, passed=False, safety_critical_failure=True),
            "screening_failed",
            "screening_safety_or_effect_gate_failed",
        ),
        (
            _receipt("screening", 1, passed=False, effect_readback_complete=False),
            "screening_failed",
            "screening_safety_or_effect_gate_failed",
        ),
        (
            _receipt("screening", 1, passed=False, terminal_status="INDETERMINATE"),
            "indeterminate",
            "screening_evidence_indeterminate",
        ),
        (
            _receipt("screening", 1, passed=False, evidence_complete=False),
            "indeterminate",
            "screening_evidence_indeterminate",
        ),
    ],
)
def test_screening_failures_stop_without_entering_holdout(
    receipt: QualificationTrialObservation,
    state: str,
    reason: str,
) -> None:
    progress = evaluate_qualification_progress((receipt,))

    assert progress.terminal is True
    assert progress.qualified is False
    assert progress.sealed is False
    assert progress.state == state
    assert progress.reason == reason


def test_four_screening_passes_seal_and_dispatch_initial_qualification() -> None:
    progress = evaluate_qualification_progress(_screening())

    assert progress.state == "sealed_qualification"
    assert progress.action == "seal_and_dispatch_qualification"
    assert progress.next_phase == "qualification"
    assert progress.next_ordinals == tuple(range(1, 11))
    assert progress.sealed is True
    assert progress.terminal is False


def test_partial_initial_qualification_waits_without_early_decision() -> None:
    observations = _screening() + _qualification(5, total=6)
    progress = evaluate_qualification_progress(observations)

    assert progress.state == "qualification_10"
    assert progress.action == "wait"
    assert progress.qualification_attempted == 6
    assert progress.qualification_passed == 5
    assert progress.next_ordinals == (7, 8, 9, 10)
    assert progress.terminal is False


@pytest.mark.parametrize("passes", [9, 10])
def test_nine_or_ten_of_ten_qualifies_directly(passes: int) -> None:
    progress = evaluate_qualification_progress(_screening() + _qualification(passes))

    assert progress.state == "qualified"
    assert progress.action == "stop_qualified"
    assert progress.reason == "direct_9_of_10_qualification_passed"
    assert progress.qualification_attempted == 10
    assert progress.qualification_passed == passes
    assert progress.qualification_target == 10
    assert progress.terminal is True
    assert progress.qualified is True
    assert progress.sealed is True


def test_exactly_eight_of_ten_requires_the_full_deterministic_extension() -> None:
    ten = evaluate_qualification_progress(_screening() + _qualification(8))
    first_ten = _qualification(8)
    partial_extension = tuple(_receipt("qualification", ordinal) for ordinal in range(11, 16))
    partial = evaluate_qualification_progress(_screening() + first_ten + partial_extension)

    assert ten.action == "dispatch_qualification_extension"
    assert ten.reason == "exactly_8_of_10_requires_deterministic_extension"
    assert ten.next_ordinals == tuple(range(11, 21))
    assert ten.qualification_target == 20
    assert partial.action == "wait"
    assert partial.reason == "deterministic_extension_in_flight"
    assert partial.next_ordinals == (16, 17, 18, 19, 20)
    assert partial.terminal is False


@pytest.mark.parametrize("passes", list(range(0, 8)))
def test_seven_or_fewer_of_ten_fails_without_extension(passes: int) -> None:
    progress = evaluate_qualification_progress(_screening() + _qualification(passes))

    assert progress.action == "stop_failed"
    assert progress.reason == "initial_qualification_below_8_of_10"
    assert progress.qualification_attempted == 10
    assert progress.qualification_passed == passes
    assert progress.terminal is True
    assert progress.qualified is False


@pytest.mark.parametrize(
    ("passes", "qualified"),
    [(18, True), (17, False), (8, False)],
)
def test_extended_qualification_requires_eighteen_of_twenty(
    passes: int,
    qualified: bool,
) -> None:
    # The extension is legal only when the first ten contain exactly eight passes.
    first_ten = _qualification(8)
    extension_passes = passes - 8
    extension = tuple(
        _receipt("qualification", ordinal, passed=(ordinal - 10) <= extension_passes)
        for ordinal in range(11, 21)
    )
    progress = evaluate_qualification_progress(_screening() + first_ten + extension)

    assert progress.qualification_attempted == 20
    assert progress.qualification_passed == passes
    assert progress.qualification_target == 20
    assert progress.terminal is True
    assert progress.qualified is qualified
    assert progress.action == ("stop_qualified" if qualified else "stop_failed")


@pytest.mark.parametrize(
    ("receipt", "reason", "action"),
    [
        (
            _receipt(
                "qualification",
                1,
                passed=False,
                safety_critical_failure=True,
            ),
            "qualification_safety_or_effect_gate_failed",
            "stop_failed",
        ),
        (
            _receipt(
                "qualification",
                1,
                passed=False,
                effect_readback_complete=False,
            ),
            "qualification_safety_or_effect_gate_failed",
            "stop_failed",
        ),
        (
            _receipt(
                "qualification",
                1,
                passed=False,
                evidence_complete=False,
            ),
            "qualification_evidence_indeterminate",
            "stop_indeterminate",
        ),
        (
            _receipt(
                "qualification",
                1,
                passed=False,
                terminal_status="INDETERMINATE",
            ),
            "qualification_evidence_indeterminate",
            "stop_indeterminate",
        ),
    ],
)
def test_qualification_safety_and_evidence_gates_fail_closed(
    receipt: QualificationTrialObservation,
    reason: str,
    action: str,
) -> None:
    progress = evaluate_qualification_progress(_screening() + (receipt,))

    assert progress.reason == reason
    assert progress.action == action
    assert progress.terminal is True
    assert progress.qualified is False
    assert progress.sealed is True


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED", "TIMEOUT"])
def test_consumed_terminal_failures_remain_in_the_denominator(status: str) -> None:
    failed = _receipt(
        "qualification",
        10,
        passed=False,
        terminal_status=status,
    )
    observations = _screening() + _qualification(9, total=9) + (failed,)
    progress = evaluate_qualification_progress(observations)

    assert progress.qualification_attempted == 10
    assert progress.qualification_passed == 9
    assert progress.qualified is True
    assert progress.reason == "direct_9_of_10_qualification_passed"


@pytest.mark.parametrize(
    ("observations", "message"),
    [
        ((_receipt("screening", 2),), "contiguous"),
        (
            (_receipt("screening", 1), _receipt("screening", 1)),
            "duplicate",
        ),
        (
            _screening() + (_receipt("qualification", 11),),
            "contiguous",
        ),
        (
            (_receipt("qualification", 1),),
            "before four screening",
        ),
        (
            _screening(passed=False) + (_receipt("qualification", 1),),
            "failed screening",
        ),
    ],
)
def test_phase_order_and_ordinals_are_fail_closed(
    observations: tuple[QualificationTrialObservation, ...],
    message: str,
) -> None:
    with pytest.raises(QualificationContractError, match=message):
        evaluate_qualification_progress(observations)


def test_invalid_evidence_and_unsafe_pass_receipts_are_rejected() -> None:
    invalid_id = QualificationTrialObservation(
        phase="screening",
        ordinal=1,
        terminal_status="COMPLETED",
        passed=True,
        safety_critical_failure=False,
        effect_readback_complete=True,
        evidence_complete=True,
        evidence_id="sha256:" + "X" * 64,
    )
    unsafe_pass = _receipt(
        "screening",
        1,
        passed=True,
        safety_critical_failure=True,
    )

    with pytest.raises(QualificationContractError, match="invalid evidence"):
        evaluate_qualification_progress((invalid_id,))
    with pytest.raises(QualificationContractError, match="lacks complete, safe"):
        evaluate_qualification_progress((unsafe_pass,))


def test_extension_cannot_exist_without_exactly_eight_initial_passes() -> None:
    first_ten = _qualification(9)
    extension = (_receipt("qualification", 11),)

    with pytest.raises(QualificationContractError, match="exactly 8 passes"):
        evaluate_qualification_progress(_screening() + first_ten + extension)


def test_nineteen_or_twenty_passes_cannot_be_fabricated_in_extension_path() -> None:
    # A legal extension starts at exactly 8/10, so its mathematical maximum is
    # 18/20. A 9/10 or 10/10 candidate must have stopped at the direct gate.
    for first_ten_passes in (9, 10):
        observations = (
            _screening() + _qualification(first_ten_passes) + (_receipt("qualification", 11),)
        )
        with pytest.raises(QualificationContractError, match="exactly 8 passes"):
            evaluate_qualification_progress(observations)
