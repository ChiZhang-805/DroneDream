"""Locked, deterministic holdout for Harness tool-eligibility routing policy.

This suite evaluates only the production capability/precondition gate exposed
by ``eligible_harness_tools``. It does not call a model, execute a simulator, or
claim optimizer-quality improvements. Holdout labels and results are restricted
to immutable evaluation artifacts and cannot flow into development or runtime
feedback.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.orchestration.harness_context import (
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_TOOL_DEFINITIONS,
    HARNESS_TOOL_ELIGIBILITY_POLICY_VERSION,
    HARNESS_TOOL_REGISTRY_VERSION,
    HarnessToolId,
    eligible_harness_tools,
)
from app.orchestration.harness_evaluation import (
    HarnessRoutingEvalCase,
    HarnessRoutingStimulus,
    assert_routing_result_flow,
    compile_routing_eval_snapshot,
    load_routing_eval_cases,
    routing_corpus_sha256,
)
from app.orchestration.harness_routing_campaign import write_frozen_routing_artifact

HARNESS_ROUTING_HOLDOUT_SCHEMA_VERSION = "1.0"
HARNESS_ROUTING_HOLDOUT_MANIFEST_SCHEMA_VERSION = "1.0"
HARNESS_ROUTING_HOLDOUT_RESULT_SCHEMA_VERSION = "1.0"


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HarnessRoutingPolicyHoldoutCase(_ClosedModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(
        min_length=3,
        max_length=96,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    category: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    stimulus: HarnessRoutingStimulus
    expected_eligible_tools: tuple[HarnessToolId, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _validate_expected_tools(self) -> HarnessRoutingPolicyHoldoutCase:
        if len(set(self.expected_eligible_tools)) != len(self.expected_eligible_tools):
            raise ValueError("expected_eligible_tools must be unique")
        if any(tool_id not in HARNESS_TOOL_DEFINITIONS for tool_id in self.expected_eligible_tools):
            raise ValueError("expected_eligible_tools contains an unknown tool")
        required_fallbacks = {"cma_es", "optimizer_portfolio"}
        if not required_fallbacks <= set(self.expected_eligible_tools):
            raise ValueError("expected_eligible_tools must include both always-eligible fallbacks")
        return self


class HarnessRoutingPolicyHoldoutManifest(_ClosedModel):
    schema_version: Literal["1.0"] = "1.0"
    corpus_role: Literal["locked_holdout"] = "locked_holdout"
    evidence_class: Literal["deterministic_router_policy_holdout"] = (
        "deterministic_router_policy_holdout"
    )
    corpus_filename: str = Field(min_length=1, max_length=160)
    case_count: int = Field(ge=1)
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_input_suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    immutable: Literal[True] = True
    result_policy: Literal["artifact_only_no_writeback"] = "artifact_only_no_writeback"
    forbidden_consumers: tuple[
        Literal[
            "development_case_generation",
            "model_prompt_examples",
            "router_training",
            "runtime_feedback",
        ],
        ...,
    ] = (
        "development_case_generation",
        "model_prompt_examples",
        "router_training",
        "runtime_feedback",
    )


class HarnessRoutingPolicyHoldoutBundle(_ClosedModel):
    manifest: HarnessRoutingPolicyHoldoutManifest
    cases: tuple[HarnessRoutingPolicyHoldoutCase, ...] = Field(min_length=1)


class HarnessRoutingPolicyHoldoutGrade(_ClosedModel):
    case_id: str
    category: str
    expected_eligible_tools: tuple[HarnessToolId, ...]
    actual_eligible_tools: tuple[HarnessToolId, ...]
    passed: bool


class HarnessRoutingPolicyHoldoutResult(_ClosedModel):
    schema_version: Literal["1.0"] = "1.0"
    source_role: Literal["locked_holdout"] = "locked_holdout"
    evidence_class: Literal["deterministic_router_policy_holdout"] = (
        "deterministic_router_policy_holdout"
    )
    result_destination: Literal["evaluation_artifact"] = "evaluation_artifact"
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_input_suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    development_corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_schema_version: str
    tool_registry_version: str
    eligibility_policy_version: str
    case_count: int = Field(ge=1)
    passed_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    exact_match_required: Literal[True] = True
    qualified: bool
    grades: tuple[HarnessRoutingPolicyHoldoutGrade, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_summary(self) -> HarnessRoutingPolicyHoldoutResult:
        actual_passed = sum(grade.passed for grade in self.grades)
        if self.case_count != len(self.grades):
            raise ValueError("case_count must equal grade count")
        if self.passed_count != actual_passed:
            raise ValueError("passed_count must equal passing grade count")
        if self.pass_rate != self.passed_count / self.case_count:
            raise ValueError("pass_rate must equal passed_count / case_count")
        if self.qualified is not (self.passed_count == self.case_count):
            raise ValueError("qualified must require exact match on every case")
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


def _case_ids_sha256(
    cases: tuple[HarnessRoutingPolicyHoldoutCase, ...],
) -> str:
    return _sha256([case.case_id for case in cases])


def routing_policy_holdout_corpus_sha256(
    cases: tuple[HarnessRoutingPolicyHoldoutCase, ...],
) -> str:
    return _sha256([case.model_dump(mode="json") for case in cases])


def routing_policy_input_suite_sha256(
    cases: tuple[HarnessRoutingPolicyHoldoutCase, ...],
) -> str:
    snapshots = []
    for case in cases:
        snapshot = compile_routing_eval_snapshot(_as_eval_case(case))
        snapshots.append(
            {
                "case_id": case.case_id,
                "snapshot": snapshot.model_dump(mode="json", exclude_none=True),
            }
        )
    return _sha256(snapshots)


def routing_policy_holdout_manifest_sha256(
    manifest: HarnessRoutingPolicyHoldoutManifest,
) -> str:
    return _sha256(manifest.model_dump(mode="json"))


def _as_eval_case(
    case: HarnessRoutingPolicyHoldoutCase,
) -> HarnessRoutingEvalCase:
    return HarnessRoutingEvalCase(
        case_id=case.case_id,
        category="mixed_tool_history",
        stimulus=case.stimulus,
        acceptable_tools=("cma_es",),
        rationale="Locked eligibility-policy input; labels are never compiled.",
    )


def _load_holdout_cases(
    path: Path,
) -> tuple[HarnessRoutingPolicyHoldoutCase, ...]:
    cases: list[HarnessRoutingPolicyHoldoutCase] = []
    seen_ids: set[str] = set()
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("unable to read locked routing holdout corpus") from exc
    for line_number, raw_line in enumerate(raw_lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            case = HarnessRoutingPolicyHoldoutCase.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(f"invalid locked routing holdout case at line {line_number}") from exc
        if case.case_id in seen_ids:
            raise ValueError(f"duplicate locked routing holdout case_id: {case.case_id}")
        seen_ids.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError("locked routing holdout corpus is empty")
    return tuple(cases)


def load_locked_routing_policy_holdout(
    corpus_path: Path,
    manifest_path: Path,
    development_corpus_path: Path,
) -> HarnessRoutingPolicyHoldoutBundle:
    """Load a holdout only after all role, hash, and separation checks pass."""

    try:
        manifest = HarnessRoutingPolicyHoldoutManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ValueError("invalid locked routing holdout manifest") from exc
    if manifest.corpus_filename != corpus_path.name:
        raise ValueError("holdout manifest corpus_filename does not match corpus")
    cases = _load_holdout_cases(corpus_path)
    development_cases = load_routing_eval_cases(development_corpus_path)
    if corpus_path.resolve() == development_corpus_path.resolve():
        raise ValueError("holdout and development corpora must be separate files")
    development_ids = {case.case_id for case in development_cases}
    overlap = sorted(development_ids & {case.case_id for case in cases})
    if overlap:
        raise ValueError(f"holdout and development case IDs must be disjoint: {overlap}")
    checks = {
        "case_count": len(cases),
        "corpus_sha256": routing_policy_holdout_corpus_sha256(cases),
        "case_ids_sha256": _case_ids_sha256(cases),
        "policy_input_suite_sha256": routing_policy_input_suite_sha256(cases),
        "development_corpus_sha256": routing_corpus_sha256(development_cases),
    }
    for field_name, actual in checks.items():
        if getattr(manifest, field_name) != actual:
            raise ValueError(f"holdout manifest {field_name} does not match current inputs")
    return HarnessRoutingPolicyHoldoutBundle(manifest=manifest, cases=cases)


def evaluate_locked_routing_policy_holdout(
    bundle: HarnessRoutingPolicyHoldoutBundle,
) -> HarnessRoutingPolicyHoldoutResult:
    """Evaluate exact production eligibility sets without adaptive writeback."""

    assert_routing_result_flow("locked_holdout", "evaluation_artifact")
    grades: list[HarnessRoutingPolicyHoldoutGrade] = []
    for case in bundle.cases:
        snapshot = compile_routing_eval_snapshot(_as_eval_case(case))
        actual = eligible_harness_tools(snapshot)
        grades.append(
            HarnessRoutingPolicyHoldoutGrade(
                case_id=case.case_id,
                category=case.category,
                expected_eligible_tools=case.expected_eligible_tools,
                actual_eligible_tools=actual,
                passed=actual == case.expected_eligible_tools,
            )
        )
    passed_count = sum(grade.passed for grade in grades)
    return HarnessRoutingPolicyHoldoutResult(
        corpus_sha256=bundle.manifest.corpus_sha256,
        manifest_sha256=routing_policy_holdout_manifest_sha256(bundle.manifest),
        case_ids_sha256=bundle.manifest.case_ids_sha256,
        policy_input_suite_sha256=bundle.manifest.policy_input_suite_sha256,
        development_corpus_sha256=bundle.manifest.development_corpus_sha256,
        evidence_schema_version=HARNESS_EVIDENCE_SCHEMA_VERSION,
        tool_registry_version=HARNESS_TOOL_REGISTRY_VERSION,
        eligibility_policy_version=HARNESS_TOOL_ELIGIBILITY_POLICY_VERSION,
        case_count=len(grades),
        passed_count=passed_count,
        pass_rate=passed_count / len(grades),
        qualified=passed_count == len(grades),
        grades=tuple(grades),
    )


def load_locked_routing_policy_result(
    path: Path,
    bundle: HarnessRoutingPolicyHoldoutBundle,
) -> HarnessRoutingPolicyHoldoutResult:
    """Verify a committed result against a fresh deterministic evaluation."""

    try:
        result = HarnessRoutingPolicyHoldoutResult.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ValueError("invalid locked routing holdout result artifact") from exc
    expected = evaluate_locked_routing_policy_holdout(bundle)
    if result != expected:
        raise ValueError("locked routing holdout result does not match current corpus and policy")
    return result


def write_locked_routing_policy_result(
    path: Path,
    result: HarnessRoutingPolicyHoldoutResult,
    *,
    destination: Literal[
        "evaluation_artifact",
        "development_evidence",
        "router_training",
        "runtime_feedback",
    ] = "evaluation_artifact",
) -> None:
    """Create a result artifact while rejecting every adaptive destination."""

    assert_routing_result_flow("locked_holdout", destination)
    write_frozen_routing_artifact(path, result)


__all__ = [
    "HARNESS_ROUTING_HOLDOUT_MANIFEST_SCHEMA_VERSION",
    "HARNESS_ROUTING_HOLDOUT_RESULT_SCHEMA_VERSION",
    "HARNESS_ROUTING_HOLDOUT_SCHEMA_VERSION",
    "HarnessRoutingPolicyHoldoutBundle",
    "HarnessRoutingPolicyHoldoutCase",
    "HarnessRoutingPolicyHoldoutManifest",
    "HarnessRoutingPolicyHoldoutResult",
    "evaluate_locked_routing_policy_holdout",
    "load_locked_routing_policy_holdout",
    "load_locked_routing_policy_result",
    "routing_policy_holdout_corpus_sha256",
    "routing_policy_holdout_manifest_sha256",
    "routing_policy_input_suite_sha256",
    "write_locked_routing_policy_result",
]
