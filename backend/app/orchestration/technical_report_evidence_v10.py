"""Build the software-owned v10 technical-report evidence bundle.

The v9 bundle remains immutable.  This module re-verifies every v9 source by
exact bytes, then adds the latest retained online routing campaign, the
Evidence 2.9 offline multi-tool budget campaign, and the complete bundled
advanced-physics closure.  The resulting bundle deliberately records remaining
online and release gates instead of upgrading partial evidence into a broader
claim.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import subprocess
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from app.orchestration.harness_context import (
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_PROMPT_TEMPLATE_VERSION,
    HARNESS_TOOL_REGISTRY_VERSION,
)
from app.orchestration.harness_evaluation import (
    grade_routing_prediction_artifact,
    load_archived_routing_prediction_artifact,
    load_routing_eval_cases,
)
from app.orchestration.harness_multi_tool_budget_evaluation import (
    HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY,
    HARNESS_MULTI_TOOL_BUDGET_EVAL_MANIFEST_SCHEMA_VERSION,
    HARNESS_MULTI_TOOL_BUDGET_EVAL_SCHEMA_VERSION,
)
from app.simulator.advanced_physics_closure_evidence import (
    verify_advanced_physics_closure,
)

SCHEMA_VERSION = "dronedream.technical-report-evidence.v10"
MANIFEST_SCHEMA_VERSION = "dronedream.technical-report-evidence-manifest.v2"
EVIDENCE_CLASS = "SOFTWARE_PROVENANCE_BOUND_REPORT_EVIDENCE"
CLAIM_BOUNDARY = (
    "Exact-byte aggregation of the previously frozen v9 report evidence, one "
    "retained 24-call OpenAI development-corpus routing campaign, the offline "
    "Evidence 2.9 multi-tool dispatcher budget evaluation, and real PX4/Gazebo "
    "bundled-effect evidence. Evidence classes remain separate. The bundle does "
    "not establish current Evidence 2.9 online routing, causal Harness outcome "
    "benefit, optimizer superiority, universal perturbed-flight success, "
    "sim-to-real transfer, real-aircraft safety, or final report/release readiness."
)

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ONLINE_EVIDENCE_VERSION = "2.8"
_ONLINE_PROMPT_VERSION = "1.7"
_ONLINE_PROMPT_SHA256 = "81b3cae64b16f6b8294ef05acd9792f5d86c36e6d9e2afecf2f60d4d4db41903"
_ONLINE_MODEL_SNAPSHOT = "gpt-4.1-2025-04-14"
_BASE_V9_FREEZE_COMMIT = "8102ffecb37b1f1b0e25c80d6b02db05325ca986"
_ONLINE_ROUTING_FREEZE_COMMIT = "ef00362927475b2fc411a4d82084bbbae8846582"
_MULTI_TOOL_FREEZE_COMMIT = "15603c6f3c1e421dc20802ed0b8dfcfaf7ac49e8"
_ADVANCED_PHYSICS_FREEZE_COMMIT = "83982f37899f8054e24a749af8e6469fedf48e8d"


@dataclass(frozen=True)
class EvidencePaths:
    base_bundle: str = "artifacts/technical-report/evidence-v9.json"
    base_manifest: str = "artifacts/technical-report/evidence-v9.manifest.json"
    base_checksums: str = "artifacts/technical-report/evidence-v9.sha256"
    routing_corpus: str = "backend/tests/fixtures/harness_routing_eval_v1.jsonl"
    online_routing_artifact: str = (
        "backend/evaluation_artifacts/"
        "harness-routing-gpt-4.1-2025-04-14-evidence-2.8-prompt-1.7-20260728.json"
    )
    online_routing_manifest: str = (
        "backend/evaluation_artifacts/"
        "harness-routing-gpt-4.1-2025-04-14-evidence-2.8-prompt-1.7-20260728."
        "manifest.json"
    )
    multi_tool_artifact: str = (
        "backend/evaluation_artifacts/harness-multi-tool-budget-evaluation-v1.json"
    )
    multi_tool_manifest: str = (
        "backend/evaluation_artifacts/harness-multi-tool-budget-evaluation-v1.manifest.json"
    )
    multi_tool_csv: str = "backend/evaluation_artifacts/harness-multi-tool-budget-evaluation-v1.csv"
    multi_tool_checksums: str = (
        "backend/evaluation_artifacts/harness-multi-tool-budget-evaluation-v1.sha256"
    )
    multi_tool_generation_receipt: str = (
        "artifacts/test-runs/harness-multi-tool-budget-evaluation-v1-generation-receipt.json"
    )
    advanced_physics_root: str = "artifacts/technical-report/advanced-physics-closure-v2-f1e8fa8"
    advanced_physics_test_receipt: str = (
        "artifacts/test-runs/advanced-physics-closure-f1e8fa8/test-receipt.json"
    )


DEFAULT_PATHS = EvidencePaths()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _pretty_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _self_hash(payload: Mapping[str, Any], field: str) -> str:
    return _sha256_bytes(
        _canonical_bytes({key: value for key, value in payload.items() if key != field})
    )


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _sequence(value: object, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _require_commit(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _COMMIT_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a full lowercase Git commit")
    return value


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


def _require_timestamp(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be an explicit UTC timestamp")
    try:
        datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be an explicit UTC timestamp") from exc
    return value


def _safe_path(value: str, *, field: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"{field} must be a safe repository-relative path")
    return path


def _repo_path(repository_root: Path, relative: str) -> Path:
    return repository_root.joinpath(*_safe_path(relative, field="source path").parts)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON evidence must be an object: {path}")
    return value


def _file_record(repository_root: Path, relative: str) -> dict[str, Any]:
    path = _repo_path(repository_root, relative)
    if not path.is_file():
        raise ValueError(f"evidence source is missing: {relative}")
    raw = path.read_bytes()
    return {
        "path": relative,
        "bytes": len(raw),
        "sha256": _sha256_bytes(raw),
    }


def _git_snapshot_record(
    repository_root: Path,
    relative: str,
    *,
    source_commit: str,
) -> dict[str, Any]:
    safe_relative = _safe_path(relative, field="snapshot source path").as_posix()
    try:
        completed = subprocess.run(
            ["git", "show", f"{source_commit}:{safe_relative}"],
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"could not read source snapshot {source_commit}:{safe_relative}") from exc
    raw = completed.stdout
    return {
        "path": safe_relative,
        "bytes": len(raw),
        "sha256": _sha256_bytes(raw),
        "snapshot_commit": source_commit,
        "byte_source": "git_commit_blob",
    }


def _freeze_bound_record(
    repository_root: Path,
    relative: str,
    *,
    freeze_commit: str,
) -> dict[str, Any]:
    current = _file_record(repository_root, relative)
    frozen = _git_snapshot_record(
        repository_root,
        relative,
        source_commit=freeze_commit,
    )
    if current["bytes"] != frozen["bytes"] or current["sha256"] != frozen["sha256"]:
        raise ValueError(f"evidence source drifted from freeze commit {freeze_commit}: {relative}")
    return {
        **current,
        "snapshot_commit": freeze_commit,
        "byte_source": "working_tree_matches_git_commit_blob",
    }


def _verify_checksum_file(
    *,
    checksum_path: Path,
    records: list[Mapping[str, Any]],
) -> None:
    expected_lines = [
        f"{record['sha256']}  {PurePosixPath(str(record['path'])).name}" for record in records
    ]
    raw = checksum_path.read_bytes()
    try:
        actual_lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"checksum file is not ASCII: {checksum_path}") from exc
    if actual_lines != expected_lines or not raw.endswith((b"\n", b"\r\n")):
        raise ValueError(f"checksum file drifted: {checksum_path}")


def _verify_base_v9(
    repository_root: Path,
    paths: EvidencePaths,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    bundle_record = _freeze_bound_record(
        repository_root,
        paths.base_bundle,
        freeze_commit=_BASE_V9_FREEZE_COMMIT,
    )
    manifest_record = _freeze_bound_record(
        repository_root,
        paths.base_manifest,
        freeze_commit=_BASE_V9_FREEZE_COMMIT,
    )
    checksum_record = _freeze_bound_record(
        repository_root,
        paths.base_checksums,
        freeze_commit=_BASE_V9_FREEZE_COMMIT,
    )
    bundle = _load_json(_repo_path(repository_root, paths.base_bundle))
    manifest = _load_json(_repo_path(repository_root, paths.base_manifest))
    if bundle.get("schema_version") != "dronedream.technical-report-evidence.v9":
        raise ValueError("base evidence bundle is not v9")
    if manifest.get("schema_version") != "dronedream.technical-report-evidence-manifest.v1":
        raise ValueError("base evidence manifest schema drifted")
    base_source_commit = _require_commit(
        bundle.get("source_commit"),
        field="base bundle source_commit",
    )
    base_generated_at = _require_timestamp(
        bundle.get("generated_at"),
        field="base bundle generated_at",
    )
    if bundle.get("bundle_sha256") != _self_hash(bundle, "bundle_sha256"):
        raise ValueError("base evidence internal bundle hash drifted")
    if (
        manifest.get("source_commit") != base_source_commit
        or manifest.get("generated_at") != base_generated_at
    ):
        raise ValueError("base evidence manifest provenance drifted")
    manifest_bundle = _mapping(manifest.get("bundle"), field="base manifest bundle")
    if (
        manifest_bundle.get("path") != PurePosixPath(paths.base_bundle).name
        or manifest_bundle.get("file_sha256") != bundle_record["sha256"]
        or manifest_bundle.get("bundle_sha256") != bundle["bundle_sha256"]
    ):
        raise ValueError("base evidence manifest bundle binding drifted")
    bundle_sources = _mapping(bundle.get("sources"), field="base bundle sources")
    manifest_sources = _mapping(manifest.get("sources"), field="base manifest sources")
    if bundle_sources != manifest_sources:
        raise ValueError("base evidence source manifests disagree")
    verified_sources: dict[str, dict[str, Any]] = {}
    for role, raw_source in sorted(bundle_sources.items()):
        source = _mapping(raw_source, field=f"base source {role}")
        relative = source.get("path")
        if not isinstance(relative, str):
            raise ValueError(f"base source {role}.path must be a string")
        record = _git_snapshot_record(
            repository_root,
            relative,
            source_commit=_BASE_V9_FREEZE_COMMIT,
        )
        if source.get("sha256") != record["sha256"]:
            raise ValueError(f"base source {role} SHA-256 drifted")
        verified_sources[str(role)] = record
    _verify_checksum_file(
        checksum_path=_repo_path(repository_root, paths.base_checksums),
        records=[bundle_record, manifest_record],
    )
    return (
        bundle,
        {
            "bundle": bundle_record,
            "manifest": manifest_record,
            "checksums": checksum_record,
            "freeze_commit": _BASE_V9_FREEZE_COMMIT,
        },
        verified_sources,
    )


def _verify_online_routing(
    repository_root: Path,
    paths: EvidencePaths,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    artifact_record = _freeze_bound_record(
        repository_root,
        paths.online_routing_artifact,
        freeze_commit=_ONLINE_ROUTING_FREEZE_COMMIT,
    )
    manifest_record = _freeze_bound_record(
        repository_root,
        paths.online_routing_manifest,
        freeze_commit=_ONLINE_ROUTING_FREEZE_COMMIT,
    )
    corpus_record = _freeze_bound_record(
        repository_root,
        paths.routing_corpus,
        freeze_commit=_ONLINE_ROUTING_FREEZE_COMMIT,
    )
    artifact_path = _repo_path(repository_root, paths.online_routing_artifact)
    manifest = _load_json(_repo_path(repository_root, paths.online_routing_manifest))
    if manifest.get("schema_version") != ("dronedream.harness-routing-online-campaign-manifest/v1"):
        raise ValueError("online routing campaign manifest schema drifted")
    if manifest.get("manifest_sha256") != _self_hash(manifest, "manifest_sha256"):
        raise ValueError("online routing manifest internal hash drifted")
    artifact_binding = _mapping(manifest.get("artifact"), field="online artifact binding")
    if (
        artifact_binding.get("path") != paths.online_routing_artifact
        or artifact_binding.get("bytes") != artifact_record["bytes"]
        or artifact_binding.get("sha256") != artifact_record["sha256"]
    ):
        raise ValueError("online routing artifact byte binding drifted")
    cases = load_routing_eval_cases(_repo_path(repository_root, paths.routing_corpus))
    artifact = load_archived_routing_prediction_artifact(
        artifact_path,
        cases,
        evidence_schema_version=_ONLINE_EVIDENCE_VERSION,
        prompt_template_version=_ONLINE_PROMPT_VERSION,
        prompt_suite_sha256=_ONLINE_PROMPT_SHA256,
    )
    report = grade_routing_prediction_artifact(artifact, cases)
    campaign = _mapping(manifest.get("campaign"), field="online campaign")
    campaign_source_commit = _require_commit(
        campaign.get("source_commit"),
        field="online campaign source_commit",
    )
    campaign_generated_at = _require_timestamp(
        manifest.get("generated_at"),
        field="online campaign generated_at",
    )
    if (
        campaign.get("exit_code") != 0
        or campaign.get("source_branch") != "codex/software"
        or campaign.get("source_tree_clean") is not True
        or campaign.get("provider_calls") != len(cases)
        or campaign.get("network_calls") != len(cases)
        or campaign.get("output_replaced") is not False
        or artifact.provider != "openai"
        or artifact.model_snapshot != _ONLINE_MODEL_SNAPSHOT
    ):
        raise ValueError("online routing campaign provenance drifted")
    credential_handling = _mapping(
        manifest.get("credential_handling"),
        field="online credential handling",
    )
    if (
        credential_handling.get("api_key_persisted") is not False
        or credential_handling.get("api_key_printed") is not False
        or credential_handling.get("secret_values_in_artifact") is not False
    ):
        raise ValueError("online routing credential boundary drifted")
    if (
        artifact.evidence_schema_version != artifact_binding.get("evidence_schema_version")
        or artifact.tool_registry_version != artifact_binding.get("tool_registry_version")
        or artifact.prompt_template_version != artifact_binding.get("prompt_template_version")
        or artifact.prompt_suite_sha256 != artifact_binding.get("prompt_suite_sha256")
        or artifact.corpus_sha256 != artifact_binding.get("corpus_sha256")
        or artifact.model_snapshot != artifact_binding.get("model_snapshot")
        or artifact.provider != artifact_binding.get("provider")
        or artifact.generation_config.model_dump(mode="json")
        != artifact_binding.get("generation_config")
    ):
        raise ValueError("online routing artifact metadata drifted")
    result = _mapping(manifest.get("result"), field="online result")
    failed_rows = [
        {
            "case_id": grade.case_id,
            "category": grade.category,
            "selected_tool": grade.selected_tool,
            "acceptable_tools": list(grade.acceptable_tools),
        }
        for grade in report.predictions.grades
        if not grade.acceptable
    ]
    recomputed_result = {
        "case_count": report.predictions.case_count,
        "passed_count": report.predictions.passed_count,
        "pass_rate": report.predictions.pass_rate,
        "minimum_category_pass_rate": report.qualification.minimum_category_pass_rate,
        "uniform_random_expected_pass_rate": (report.baselines.uniform_random_expected_pass_rate),
        "best_constant_pass_rate": report.baselines.best_constant_pass_rate,
        "absolute_lift_over_best_constant": report.absolute_lift_over_best_constant,
        "qualified": report.qualification.qualified,
        "failed_requirements": list(report.qualification.failed_requirements),
        "failed_cases": failed_rows,
    }
    if dict(result) != recomputed_result:
        raise ValueError("online routing result does not recompute")
    prediction_counts = Counter(
        prediction.selected_tool for prediction in artifact.predictions.values()
    )
    contract_current = (
        artifact.evidence_schema_version == HARNESS_EVIDENCE_SCHEMA_VERSION
        and artifact.tool_registry_version == HARNESS_TOOL_REGISTRY_VERSION
        and artifact.prompt_template_version == HARNESS_PROMPT_TEMPLATE_VERSION
    )
    summary = {
        "evidence_class": "online_development_routing_corpus",
        "claim_boundary": manifest["claim_boundary"],
        "source_commit": campaign_source_commit,
        "generated_at": campaign_generated_at,
        "provider": artifact.provider,
        "model_snapshot": artifact.model_snapshot,
        "provider_calls": campaign["provider_calls"],
        "network_calls": campaign["network_calls"],
        "contract_current": contract_current,
        "qualification_scope": "archived_evidence_2_8_prompt_1_7",
        "current_contract": {
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
            "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
        },
        "artifact_contract": {
            "evidence_schema_version": artifact.evidence_schema_version,
            "tool_registry_version": artifact.tool_registry_version,
            "prompt_template_version": artifact.prompt_template_version,
            "prompt_suite_sha256": artifact.prompt_suite_sha256,
            "corpus_sha256": artifact.corpus_sha256,
        },
        "generation_config": artifact.generation_config.model_dump(mode="json"),
        "case_count": report.predictions.case_count,
        "passed_count": report.predictions.passed_count,
        "pass_rate": report.predictions.pass_rate,
        "category_rows": [
            {"category": category, **category_result}
            for category, category_result in sorted(report.predictions.category_results.items())
        ],
        "tool_selection_rows": [
            {"tool": tool, "selected_count": count}
            for tool, count in sorted(prediction_counts.items())
        ],
        "uniform_random_expected_pass_rate": (report.baselines.uniform_random_expected_pass_rate),
        "best_constant_pass_rate": report.baselines.best_constant_pass_rate,
        "best_constant_tools": list(report.baselines.best_constant_tools),
        "absolute_lift_over_uniform_random": (report.absolute_lift_over_uniform_random),
        "absolute_lift_over_best_constant": report.absolute_lift_over_best_constant,
        "qualified": report.qualification.qualified,
        "failed_requirements": list(report.qualification.failed_requirements),
        "failed_cases": failed_rows,
        "credential_handling": dict(credential_handling),
    }
    case_rows = [
        {
            "case_id": grade.case_id,
            "category": grade.category,
            "selected_tool": grade.selected_tool,
            "acceptable_tools": "|".join(grade.acceptable_tools),
            "passed": grade.acceptable,
        }
        for grade in report.predictions.grades
    ]
    return (
        summary,
        {
            "routing_corpus": corpus_record,
            "routing_predictions": artifact_record,
            "routing_online_manifest": manifest_record,
        },
        case_rows,
    )


def _verify_multi_tool_budget(
    repository_root: Path,
    paths: EvidencePaths,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    records = {
        "harness_multi_tool_budget": _freeze_bound_record(
            repository_root,
            paths.multi_tool_artifact,
            freeze_commit=_MULTI_TOOL_FREEZE_COMMIT,
        ),
        "harness_multi_tool_budget_manifest": _freeze_bound_record(
            repository_root,
            paths.multi_tool_manifest,
            freeze_commit=_MULTI_TOOL_FREEZE_COMMIT,
        ),
        "harness_multi_tool_budget_csv": _freeze_bound_record(
            repository_root,
            paths.multi_tool_csv,
            freeze_commit=_MULTI_TOOL_FREEZE_COMMIT,
        ),
        "harness_multi_tool_budget_sha256": _freeze_bound_record(
            repository_root,
            paths.multi_tool_checksums,
            freeze_commit=_MULTI_TOOL_FREEZE_COMMIT,
        ),
        "harness_multi_tool_budget_generation_receipt": _freeze_bound_record(
            repository_root,
            paths.multi_tool_generation_receipt,
            freeze_commit=_MULTI_TOOL_FREEZE_COMMIT,
        ),
    }
    artifact = _load_json(_repo_path(repository_root, paths.multi_tool_artifact))
    manifest = _load_json(_repo_path(repository_root, paths.multi_tool_manifest))
    receipt = _load_json(_repo_path(repository_root, paths.multi_tool_generation_receipt))
    if artifact.get("schema_version") != HARNESS_MULTI_TOOL_BUDGET_EVAL_SCHEMA_VERSION:
        raise ValueError("multi-tool artifact schema drifted")
    if manifest.get("schema_version") != (HARNESS_MULTI_TOOL_BUDGET_EVAL_MANIFEST_SCHEMA_VERSION):
        raise ValueError("multi-tool manifest schema drifted")
    if artifact.get("artifact_sha256") != _self_hash(artifact, "artifact_sha256"):
        raise ValueError("multi-tool artifact internal hash drifted")
    if manifest.get("manifest_sha256") != _self_hash(manifest, "manifest_sha256"):
        raise ValueError("multi-tool manifest internal hash drifted")
    source_commit = _require_commit(
        artifact.get("source_commit"),
        field="multi-tool source_commit",
    )
    generated_at = _require_timestamp(
        artifact.get("generated_at"),
        field="multi-tool generated_at",
    )
    contracts = _mapping(artifact.get("contracts"), field="multi-tool contracts")
    if (
        manifest.get("source_commit") != source_commit
        or manifest.get("generated_at") != generated_at
        or manifest.get("artifact_sha256") != artifact["artifact_sha256"]
        or manifest.get("claim_boundary") != HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY
        or artifact.get("claim_boundary") != HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY
        or contracts.get("evidence_schema_version") != HARNESS_EVIDENCE_SCHEMA_VERSION
        or contracts.get("tool_registry_version") != HARNESS_TOOL_REGISTRY_VERSION
        or manifest.get("contracts") != contracts
    ):
        raise ValueError("multi-tool artifact/manifest binding drifted")
    runtime = _mapping(manifest.get("runtime"), field="multi-tool runtime")
    if runtime != {
        "network_calls": 0,
        "real_credentials_used": False,
        "real_provider_calls": 0,
        "simulator_backend": "mock",
    }:
        raise ValueError("multi-tool offline runtime boundary drifted")
    summary = _mapping(artifact.get("summary"), field="multi-tool summary")
    blocks = _sequence(artifact.get("block_rows"), field="multi-tool block_rows")
    if (
        summary.get("block_count") != len(blocks)
        or summary.get("configured_budget_parity_count") != len(blocks)
        or summary.get("scripted_multi_tool_generation_count") != len(blocks)
        or artifact.get("real_provider_calls") != 0
        or artifact.get("network_calls") != 0
        or artifact.get("real_credentials_used") is not False
        or artifact.get("physical_fidelity") is not False
        or artifact.get("llm_quality_claim_permitted") is not False
        or artifact.get("optimizer_superiority_claim_permitted") is not False
        or artifact.get("causal_harness_benefit_claim_permitted") is not False
    ):
        raise ValueError("multi-tool summary or claim boundary drifted")
    _verify_checksum_file(
        checksum_path=_repo_path(repository_root, paths.multi_tool_checksums),
        records=[
            records["harness_multi_tool_budget"],
            records["harness_multi_tool_budget_csv"],
            records["harness_multi_tool_budget_manifest"],
        ],
    )
    if receipt.get("schema_version") != (
        "dronedream.harness-multi-tool-budget-generation-receipt/v1"
    ):
        raise ValueError("multi-tool generation receipt schema drifted")
    successful = _mapping(
        receipt.get("successful_attempt"),
        field="multi-tool successful_attempt",
    )
    verification = _mapping(
        receipt.get("verification"),
        field="multi-tool verification",
    )
    if (
        successful.get("source_commit") != source_commit
        or successful.get("generated_at") != generated_at
        or successful.get("exit_code") != 0
        or successful.get("artifact_internal_sha256") != artifact["artifact_sha256"]
        or successful.get("artifact_file_sha256") != records["harness_multi_tool_budget"]["sha256"]
        or successful.get("manifest_internal_sha256") != manifest["manifest_sha256"]
        or successful.get("manifest_file_sha256")
        != records["harness_multi_tool_budget_manifest"]["sha256"]
        or successful.get("csv_file_sha256") != records["harness_multi_tool_budget_csv"]["sha256"]
        or successful.get("provider_calls") != 0
        or successful.get("network_calls") != 0
        or successful.get("real_credentials_used") is not False
        or verification.get("exit_code") != 0
    ):
        raise ValueError("multi-tool generation receipt binding drifted")
    block_rows: list[dict[str, Any]] = []
    for raw_block in blocks:
        block = _mapping(raw_block, field="multi-tool block")
        arms = _sequence(block.get("arms"), field="multi-tool arms")
        by_name = {
            str(_mapping(arm, field="multi-tool arm").get("arm")): _mapping(
                arm,
                field="multi-tool arm",
            )
            for arm in arms
        }
        direct = by_name.get("direct_portfolio")
        scripted = by_name.get("scripted_multi_tool")
        if direct is None or scripted is None:
            raise ValueError("multi-tool block arms drifted")
        block_rows.append(
            {
                "block_id": block.get("block_id"),
                "seed_block": block.get("seed_block"),
                "configured_budget_equal": block.get("configured_budget_equal"),
                "direct_realized_trials": direct.get("realized_dispatched_trials"),
                "scripted_realized_trials": scripted.get("realized_dispatched_trials"),
                "scripted_minus_direct_trial_delta": block.get(
                    "realized_trial_delta_scripted_minus_direct"
                ),
                "scripted_decision_calls": scripted.get("scripted_decision_calls"),
                "scripted_multi_tool_generations": _mapping(
                    scripted.get("plan_trace"),
                    field="multi-tool plan_trace",
                ).get("multi_tool_generation_count"),
            }
        )
    return (
        {
            "evidence_class": artifact["evidence_class"],
            "claim_boundary": artifact["claim_boundary"],
            "source_commit": source_commit,
            "generated_at": generated_at,
            "contracts": dict(contracts),
            "configured_budget": artifact["configured_budget"],
            "seed_blocks": artifact["seed_blocks"],
            "summary": dict(summary),
            "block_rows": block_rows,
            "runtime": dict(runtime),
            "physical_fidelity": False,
            "llm_quality_claim_permitted": False,
            "optimizer_superiority_claim_permitted": False,
            "causal_harness_benefit_claim_permitted": False,
            "artifact_sha256": artifact["artifact_sha256"],
            "manifest_sha256": manifest["manifest_sha256"],
        },
        records,
        block_rows,
    )


def _verify_advanced_physics(
    repository_root: Path,
    paths: EvidencePaths,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    evidence_root = _repo_path(repository_root, paths.advanced_physics_root)
    manifest, receipt = verify_advanced_physics_closure(
        repository_root=repository_root,
        evidence_root=evidence_root,
    )
    manifest_path = f"{paths.advanced_physics_root}/advanced-physics-closure-v2.manifest.json"
    receipt_path = f"{paths.advanced_physics_root}/advanced-physics-closure-v2.receipt.json"
    checksum_path = f"{paths.advanced_physics_root}/advanced-physics-closure-v2.sha256"
    records = {
        "advanced_physics_manifest": _freeze_bound_record(
            repository_root,
            manifest_path,
            freeze_commit=_ADVANCED_PHYSICS_FREEZE_COMMIT,
        ),
        "advanced_physics_receipt": _freeze_bound_record(
            repository_root,
            receipt_path,
            freeze_commit=_ADVANCED_PHYSICS_FREEZE_COMMIT,
        ),
        "advanced_physics_sha256": _freeze_bound_record(
            repository_root,
            checksum_path,
            freeze_commit=_ADVANCED_PHYSICS_FREEZE_COMMIT,
        ),
        "advanced_physics_test_receipt": _freeze_bound_record(
            repository_root,
            paths.advanced_physics_test_receipt,
            freeze_commit=_ADVANCED_PHYSICS_FREEZE_COMMIT,
        ),
    }
    test_receipt = _load_json(_repo_path(repository_root, paths.advanced_physics_test_receipt))
    if test_receipt.get("schema_version") != (
        "dronedream.advanced-physics-closure-test-receipt/v1"
    ):
        raise ValueError("advanced-physics test receipt schema drifted")
    test_result = _mapping(
        test_receipt.get("result"),
        field="advanced-physics test result",
    )
    environment = _mapping(
        test_receipt.get("environment"),
        field="advanced-physics test environment",
    )
    binding = _mapping(
        test_receipt.get("bundle_binding"),
        field="advanced-physics bundle binding",
    )
    manifest_binding = _mapping(
        binding.get("manifest"),
        field="advanced-physics manifest binding",
    )
    receipt_binding = _mapping(
        binding.get("receipt"),
        field="advanced-physics receipt binding",
    )
    if (
        test_receipt.get("subject_commit") != manifest["subject_commit"]
        or test_receipt.get("exit_code") != 0
        or test_result.get("tests") != 52
        or test_result.get("passed") != 52
        or test_result.get("failures") != 0
        or test_result.get("errors") != 0
        or environment.get("openai_api_key_used") is not False
        or environment.get("network_calls") != 0
        or manifest_binding.get("sha256") != records["advanced_physics_manifest"]["sha256"]
        or manifest_binding.get("internal_sha256") != manifest["manifest_sha256"]
        or receipt_binding.get("sha256") != records["advanced_physics_receipt"]["sha256"]
        or receipt_binding.get("internal_sha256") != receipt["receipt_sha256"]
    ):
        raise ValueError("advanced-physics test receipt binding drifted")
    coverage = _sequence(manifest.get("coverage"), field="advanced-physics coverage")
    coverage_rows = [
        {
            "category": row["category"],
            "effect_ids": "|".join(row["effect_ids"]),
            "source_role": row["source_role"],
            "evidence_strength": row["evidence_strength"],
            "all_retained_trials_passed": row["performance_success_for_all_retained_trials"],
        }
        for row in coverage
        if isinstance(row, Mapping)
    ]
    if len(coverage_rows) != len(coverage):
        raise ValueError("advanced-physics coverage contains a non-object")
    return (
        {
            "evidence_class": manifest["evidence_class"],
            "claim_boundary": manifest["claim_boundary"],
            "subject_commit": manifest["subject_commit"],
            "generated_at": manifest["generated_at"],
            "runtime_identity": manifest["runtime_identity"],
            "capability_contract": manifest["capability_contract"],
            "coverage": coverage_rows,
            "remaining_runtime_extensions": manifest["remaining_runtime_extensions"],
            "summary": manifest["summary"],
            "manifest_sha256": manifest["manifest_sha256"],
            "receipt_sha256": receipt["receipt_sha256"],
            "test_summary": dict(test_result),
            "openai_api_key_used": False,
            "network_calls": 0,
        },
        records,
        coverage_rows,
    )


def build_technical_report_evidence_v10(
    *,
    repository_root: Path,
    source_commit: str,
    generated_at: str,
    paths: EvidencePaths = DEFAULT_PATHS,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Recompute every source and return a deterministic v10 bundle."""

    source_commit = _require_commit(source_commit, field="source_commit")
    generated_at = _require_timestamp(generated_at, field="generated_at")
    base, base_records, verified_base_sources = _verify_base_v9(
        repository_root,
        paths,
    )
    online, online_records, online_rows = _verify_online_routing(
        repository_root,
        paths,
    )
    multi_tool, multi_tool_records, multi_tool_rows = _verify_multi_tool_budget(
        repository_root,
        paths,
    )
    physics, physics_records, physics_rows = _verify_advanced_physics(
        repository_root,
        paths,
    )
    sources = dict(verified_base_sources)
    archived_routing = sources.pop("routing_predictions")
    sources["routing_predictions_v9"] = archived_routing
    sources.update(
        {
            "evidence_v9_bundle": base_records["bundle"],
            "evidence_v9_manifest": base_records["manifest"],
            "evidence_v9_sha256": base_records["checksums"],
        }
    )
    sources.update(online_records)
    sources.update(multi_tool_records)
    sources.update(physics_records)
    base_sections = {
        key: value
        for key, value in base.items()
        if key
        not in {
            "schema_version",
            "source_commit",
            "generated_at",
            "sources",
            "routing",
            "bundle_sha256",
        }
    }
    online_refresh_required = online["contract_current"] is not True
    unsigned: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_commit": source_commit,
        "generated_at": generated_at,
        "evidence_class": EVIDENCE_CLASS,
        "claim_boundary": CLAIM_BOUNDARY,
        "sources": dict(sorted(sources.items())),
        "source_lineage": {
            "evidence_v9_source_commit": base["source_commit"],
            "evidence_v9_freeze_commit": base_records["freeze_commit"],
            "online_routing_source_commit": online["source_commit"],
            "online_routing_freeze_commit": _ONLINE_ROUTING_FREEZE_COMMIT,
            "multi_tool_budget_source_commit": multi_tool["source_commit"],
            "multi_tool_budget_freeze_commit": _MULTI_TOOL_FREEZE_COMMIT,
            "advanced_physics_subject_commit": physics["subject_commit"],
            "advanced_physics_freeze_commit": _ADVANCED_PHYSICS_FREEZE_COMMIT,
        },
        "base_evidence": {
            "schema_version": base["schema_version"],
            "source_commit": base["source_commit"],
            "generated_at": base["generated_at"],
            "bundle_sha256": base["bundle_sha256"],
        },
        **base_sections,
        "routing_archived_v9": base["routing"],
        "routing": online,
        "harness_multi_tool_budget": multi_tool,
        "advanced_physics": physics,
        "release_readiness": {
            "release_ready": False,
            "online_routing_current_for_evidence_2_9": not online_refresh_required,
            "online_provider_refresh_requires_separate_user_approval": (online_refresh_required),
            "current_source_full_regression_receipt_included": False,
            "current_source_windows_rust_gate_included": False,
            "report_pdf_gate_included": False,
            "claim_boundary": (
                "This evidence export is not a final release receipt. A current "
                "Evidence 2.9 online campaign requires a new, batch-specific user "
                "approval before any API-key access. Current-source full regression, "
                "Windows Rust, and report/PDF gates must remain separate and explicit."
            ),
        },
    }
    bundle = {
        **unsigned,
        "bundle_sha256": _sha256_bytes(_canonical_bytes(unsigned)),
    }
    return (
        bundle,
        {
            "online_routing_cases": online_rows,
            "multi_tool_budget_blocks": multi_tool_rows,
            "advanced_physics_coverage": physics_rows,
        },
    )


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    if not rows:
        raise ValueError("cannot serialize empty CSV evidence")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(rows[0]),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _output_payloads(
    *,
    bundle: Mapping[str, Any],
    csv_rows: Mapping[str, list[dict[str, Any]]],
    bundle_name: str,
    manifest_name: str,
) -> tuple[bytes, dict[str, bytes], dict[str, Any], bytes]:
    bundle_bytes = _pretty_bytes(bundle)
    csv_payloads = {f"{name}.csv": _csv_bytes(rows) for name, rows in sorted(csv_rows.items())}
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source_commit": bundle["source_commit"],
        "generated_at": bundle["generated_at"],
        "claim_boundary": bundle["claim_boundary"],
        "bundle": {
            "path": bundle_name,
            "bytes": len(bundle_bytes),
            "file_sha256": _sha256_bytes(bundle_bytes),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "sources": bundle["sources"],
        "csv_exports": {
            name: {
                "path": f"csv-v10/{name}",
                "bytes": len(payload),
                "sha256": _sha256_bytes(payload),
            }
            for name, payload in csv_payloads.items()
        },
        "release_readiness": bundle["release_readiness"],
    }
    manifest_bytes = _pretty_bytes(manifest)
    checksum_rows = [
        (_sha256_bytes(bundle_bytes), bundle_name),
        (_sha256_bytes(manifest_bytes), manifest_name),
        *[(_sha256_bytes(payload), f"csv-v10/{name}") for name, payload in csv_payloads.items()],
    ]
    checksum_bytes = "".join(
        f"{digest}  {relative}\n" for digest, relative in checksum_rows
    ).encode("ascii")
    return bundle_bytes, csv_payloads, manifest, checksum_bytes


def export_technical_report_evidence_v10(
    *,
    repository_root: Path,
    output_path: Path,
    manifest_path: Path,
    checksum_path: Path,
    csv_directory: Path,
    source_commit: str,
    generated_at: str,
    paths: EvidencePaths = DEFAULT_PATHS,
) -> dict[str, Any]:
    """Build and write an exact-byte v10 evidence bundle."""

    bundle, csv_rows = build_technical_report_evidence_v10(
        repository_root=repository_root,
        source_commit=source_commit,
        generated_at=generated_at,
        paths=paths,
    )
    bundle_bytes, csv_payloads, manifest, checksum_bytes = _output_payloads(
        bundle=bundle,
        csv_rows=csv_rows,
        bundle_name=output_path.name,
        manifest_name=manifest_path.name,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    checksum_path.parent.mkdir(parents=True, exist_ok=True)
    csv_directory.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(bundle_bytes)
    manifest_path.write_bytes(_pretty_bytes(manifest))
    checksum_path.write_bytes(checksum_bytes)
    for name, payload in csv_payloads.items():
        (csv_directory / name).write_bytes(payload)
    return bundle


def verify_technical_report_evidence_v10(
    *,
    repository_root: Path,
    output_path: Path,
    manifest_path: Path,
    checksum_path: Path,
    csv_directory: Path,
    paths: EvidencePaths = DEFAULT_PATHS,
) -> dict[str, Any]:
    """Recompute sources and verify every exported byte."""

    bundle = _load_json(output_path)
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("technical-report evidence bundle schema drifted")
    if bundle.get("bundle_sha256") != _self_hash(bundle, "bundle_sha256"):
        raise ValueError("technical-report evidence internal bundle hash drifted")
    expected, csv_rows = build_technical_report_evidence_v10(
        repository_root=repository_root,
        source_commit=_require_commit(
            bundle.get("source_commit"),
            field="source_commit",
        ),
        generated_at=_require_timestamp(
            bundle.get("generated_at"),
            field="generated_at",
        ),
        paths=paths,
    )
    if bundle != expected:
        raise ValueError("technical-report evidence bundle does not recompute")
    bundle_bytes, csv_payloads, expected_manifest, checksum_bytes = _output_payloads(
        bundle=expected,
        csv_rows=csv_rows,
        bundle_name=output_path.name,
        manifest_name=manifest_path.name,
    )
    if output_path.read_bytes() != bundle_bytes:
        raise ValueError("technical-report evidence bundle bytes drifted")
    if _load_json(manifest_path) != expected_manifest:
        raise ValueError("technical-report evidence manifest does not recompute")
    if manifest_path.read_bytes() != _pretty_bytes(expected_manifest):
        raise ValueError("technical-report evidence manifest bytes drifted")
    if checksum_path.read_bytes() != checksum_bytes:
        raise ValueError("technical-report evidence checksum file drifted")
    expected_names = set(csv_payloads)
    actual_names = {path.name for path in csv_directory.glob("*.csv")}
    if actual_names != expected_names:
        raise ValueError("technical-report evidence CSV inventory drifted")
    for name, payload in csv_payloads.items():
        if (csv_directory / name).read_bytes() != payload:
            raise ValueError(f"technical-report evidence CSV drifted: {name}")
    return bundle


__all__ = [
    "CLAIM_BOUNDARY",
    "DEFAULT_PATHS",
    "EVIDENCE_CLASS",
    "EvidencePaths",
    "MANIFEST_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "build_technical_report_evidence_v10",
    "export_technical_report_evidence_v10",
    "verify_technical_report_evidence_v10",
]
