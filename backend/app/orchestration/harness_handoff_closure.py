"""Exact-byte closure index for the Harness handoff gaps 6.1 through 6.6."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "dronedream.harness-handoff-closure/v1"
_GIT_TIMEOUT_SECONDS = 30
HANDOFF_DOCUMENT_SHA256 = "fdf033defe208e99ddb4af20d8334f6d5708851b4c2a09c73da3e627d90aaffe"
HANDOFF_DOCUMENT_NAME = "DRONEDREAM_AURORA_HARNESS_HANDOFF_2026-07-28.md"

ONLINE_RECEIPT = "artifacts/test-runs/harness-routing-evidence-2.9-d36ef16/campaign-receipt.json"
ONLINE_RECEIPT_CHECKSUM = f"{ONLINE_RECEIPT}.sha256"
ONLINE_FREEZE_COMMIT = "d49353925ce074e3cb71508ee21cd2abfcee79cf"

TRIGGER_PREFIX = "backend/evaluation_artifacts/harness-reflection-trigger-ablation-v1"
STRESS_PREFIX = "backend/evaluation_artifacts/harness-reflection-outcome-stress-v1"
COMPONENT_PREFIX = "backend/evaluation_artifacts/harness-component-outcome-ablation-v2"
TRIGGER_STRESS_FREEZE_COMMIT = "77ebc65854b7dc705552a6487810b98b896637ba"
COMPONENT_FREEZE_COMMIT = "db2d54de0ea67fdd2e49eab86fc015511d908b79"

MULTI_TOOL_PREFIX = "backend/evaluation_artifacts/harness-multi-tool-budget-evaluation-v1"
MULTI_TOOL_GENERATION_RECEIPT = (
    "artifacts/test-runs/harness-multi-tool-budget-evaluation-v1-generation-receipt.json"
)
MULTI_TOOL_FREEZE_COMMIT = "15603c6f3c1e421dc20802ed0b8dfcfaf7ac49e8"

CROSS_JOB_PREFIX = "backend/evaluation_artifacts/harness-cross-job-memory-contract-v1"
CROSS_JOB_FREEZE_COMMIT = "b3d36f5f4d8e9a080d7184bfc4ea5798791284a2"

ADVANCED_PHYSICS_PREFIX = (
    "artifacts/technical-report/advanced-physics-closure-v2-f1e8fa8/advanced-physics-closure-v2"
)
ADVANCED_PHYSICS_TEST_RECEIPT = (
    "artifacts/test-runs/advanced-physics-closure-f1e8fa8/test-receipt.json"
)
ADVANCED_PHYSICS_FREEZE_COMMIT = "83982f37899f8054e24a749af8e6469fedf48e8d"

RUNTIME_PREFIX = "artifacts/test-runs/runtime-v0.1.0-beta.2-755c511"
RUNTIME_FREEZE_COMMIT = "3ec21e5600d19ae67bc080d21c8ed702e58e208a"
RUNTIME_HANDOFF_CORRECTION_COMMIT = "1b180e8f1d1ad5a8d4ac87d7e95081df06e73aae"

INSTALLER_PREFIX = "artifacts/test-runs/internal-installer-1.0.0-755c511"
INSTALLER_FREEZE_COMMIT = "01998909bfcf0fc059da7e9859d7676a339270c6"

EVIDENCE_V10_PREFIX = "artifacts/technical-report/evidence-v10"
EVIDENCE_V10_FREEZE_COMMIT = "a1f091f2edf1ae43233cd01e483bc3990c9aa279"

QUALITY_GATE_PREFIX = "artifacts/test-runs/quality-gate-bb1677a-30448014655"
QUALITY_GATE_FREEZE_COMMIT = "d2d0454970e38a9c3c280b41cd4224e504a43782"

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _pretty_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_commit(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _COMMIT_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a full lowercase Git commit")
    return value


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


def _require_utc_timestamp(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be an RFC3339 UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC3339 UTC timestamp") from exc
    return value


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe repository path: {value}")
    return path.as_posix()


def _git(
    repository_root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    git = shutil.which("git")
    if git is None:
        raise ValueError("git is required to read frozen evidence snapshots")
    try:
        result = subprocess.run(  # noqa: S603 - trusted executable and closed arguments.
            [git, *args],
            cwd=repository_root,
            check=False,
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(
            f"git {' '.join(args)} timed out after {_GIT_TIMEOUT_SECONDS} seconds"
        ) from exc
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail}")
    return result


def _verify_subject(repository_root: Path, subject_commit: str) -> None:
    resolved = (
        _git(repository_root, "rev-parse", "--verify", f"{subject_commit}^{{commit}}")
        .stdout.decode("ascii")
        .strip()
    )
    if resolved != subject_commit:
        raise ValueError("subject_commit did not resolve to the exact requested commit")


def _git_blob(repository_root: Path, subject_commit: str, relative: str) -> bytes:
    safe_relative = _safe_relative_path(relative)
    return _git(
        repository_root,
        "show",
        f"{subject_commit}:{safe_relative}",
    ).stdout


def _json_blob(
    repository_root: Path,
    subject_commit: str,
    relative: str,
) -> dict[str, Any]:
    raw = _git_blob(repository_root, subject_commit, relative)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{relative} is not valid UTF-8 JSON") from exc
    return dict(_mapping(parsed, field=relative))


def _file_record(
    repository_root: Path,
    subject_commit: str,
    relative: str,
) -> dict[str, Any]:
    raw = _git_blob(repository_root, subject_commit, relative)
    return {
        "path": _safe_relative_path(relative),
        "bytes": len(raw),
        "sha256": _sha256_bytes(raw),
        "snapshot_commit": subject_commit,
    }


def _records(
    repository_root: Path,
    subject_commit: str,
    paths: Sequence[str],
) -> list[dict[str, Any]]:
    return [_file_record(repository_root, subject_commit, relative) for relative in sorted(paths)]


def _verify_ancestor(
    repository_root: Path,
    ancestor: str,
    subject_commit: str,
) -> None:
    _require_commit(ancestor, field="freeze_commit")
    result = _git(
        repository_root,
        "merge-base",
        "--is-ancestor",
        ancestor,
        subject_commit,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"freeze commit {ancestor} is not an ancestor of subject")


def _verify_frozen_paths(
    repository_root: Path,
    *,
    freeze_commit: str,
    subject_commit: str,
    paths: Sequence[str],
) -> None:
    _verify_ancestor(repository_root, freeze_commit, subject_commit)
    for relative in paths:
        frozen = _git_blob(repository_root, freeze_commit, relative)
        current = _git_blob(repository_root, subject_commit, relative)
        if frozen != current:
            raise ValueError(f"frozen evidence changed after {freeze_commit}: {relative}")


def _prefixed_paths(prefix: str, suffixes: Sequence[str]) -> tuple[str, ...]:
    return tuple(f"{prefix}{suffix}" for suffix in suffixes)


def _online_closure(
    repository_root: Path,
    subject_commit: str,
) -> dict[str, Any]:
    receipt = _json_blob(repository_root, subject_commit, ONLINE_RECEIPT)
    execution = _mapping(receipt.get("execution"), field="online execution")
    result = _mapping(receipt.get("result"), field="online result")
    artifact = _mapping(receipt.get("artifact"), field="online artifact")
    manifest = _mapping(receipt.get("manifest"), field="online manifest")
    if receipt.get("subject_commit") != "d36ef166f985f761ab9e733753f61237950049da":
        raise ValueError("online campaign subject changed")
    expected_execution = {
        "logical_calls": 24,
        "network_calls": 24,
        "automatic_retries": 0,
        "simulator_calls": 0,
        "deployments": 0,
    }
    for key, expected in expected_execution.items():
        if execution.get(key) != expected:
            raise ValueError(f"online execution {key} changed")
    if (
        result.get("qualified") is not True
        or result.get("case_count") != 24
        or result.get("passed_count") != 23
    ):
        raise ValueError("online campaign qualification result changed")
    artifact_path = str(artifact.get("path"))
    manifest_path = str(manifest.get("path"))
    artifact_record = _file_record(repository_root, subject_commit, artifact_path)
    manifest_record = _file_record(repository_root, subject_commit, manifest_path)
    if artifact_record["sha256"] != _require_sha256(
        artifact.get("sha256"), field="online artifact sha256"
    ):
        raise ValueError("online artifact hash does not match its receipt")
    if manifest_record["sha256"] != _require_sha256(
        manifest.get("file_sha256"), field="online manifest file sha256"
    ):
        raise ValueError("online manifest hash does not match its receipt")
    paths = (
        ONLINE_RECEIPT,
        ONLINE_RECEIPT_CHECKSUM,
        artifact_path,
        manifest_path,
    )
    _verify_frozen_paths(
        repository_root,
        freeze_commit=ONLINE_FREEZE_COMMIT,
        subject_commit=subject_commit,
        paths=paths,
    )
    return {
        "gap_id": "6.1",
        "status": "complete_for_current_contract_development_routing",
        "freeze_commit": ONLINE_FREEZE_COMMIT,
        "facts": {
            "model_snapshot": "gpt-4.1-2025-04-14",
            "logical_calls": 24,
            "automatic_retries": 0,
            "passed": 23,
            "total": 24,
            "qualified": True,
            "actual_billed_cost_available": False,
        },
        "evidence": _records(repository_root, subject_commit, paths),
        "claim_boundary": receipt.get("claim_boundary"),
    }


def _ablation_closure(
    repository_root: Path,
    subject_commit: str,
) -> dict[str, Any]:
    suffixes = (".csv", ".json", ".manifest.json", ".sha256")
    trigger_paths = _prefixed_paths(TRIGGER_PREFIX, suffixes)
    stress_paths = _prefixed_paths(STRESS_PREFIX, suffixes)
    component_paths = _prefixed_paths(COMPONENT_PREFIX, suffixes)
    _verify_frozen_paths(
        repository_root,
        freeze_commit=TRIGGER_STRESS_FREEZE_COMMIT,
        subject_commit=subject_commit,
        paths=(*trigger_paths, *stress_paths),
    )
    _verify_frozen_paths(
        repository_root,
        freeze_commit=COMPONENT_FREEZE_COMMIT,
        subject_commit=subject_commit,
        paths=component_paths,
    )
    trigger = _json_blob(repository_root, subject_commit, f"{TRIGGER_PREFIX}.json")
    stress = _json_blob(repository_root, subject_commit, f"{STRESS_PREFIX}.json")
    component = _json_blob(repository_root, subject_commit, f"{COMPONENT_PREFIX}.json")
    trigger_summary = _mapping(trigger.get("summary"), field="trigger summary")
    stress_summary = _mapping(stress.get("summary"), field="stress summary")
    component_summary = _mapping(component.get("summary"), field="component summary")
    if (
        trigger_summary.get("all_six_required_triggers_covered") is not True
        or trigger.get("general_causal_benefit_claim_permitted") is not False
    ):
        raise ValueError("reflection trigger claim boundary changed")
    if (
        stress.get("causal_synthetic_protocol_effect_observed") is not True
        or stress.get("consistent_holdout_benefit_observed") is not False
        or stress.get("general_causal_benefit_claim_permitted") is not False
    ):
        raise ValueError("reflection stress claim boundary changed")
    if (
        component_summary.get("total_persisted_trials") != 554
        or component_summary.get("inconclusive_component_isolation_count") != 5
        or component.get("general_causal_claim_permitted") is not False
    ):
        raise ValueError("component ablation claim boundary changed")
    return {
        "gap_id": "6.2",
        "status": "complete_for_enumerated_contract_and_synthetic_protocol_effects",
        "freeze_commits": [
            TRIGGER_STRESS_FREEZE_COMMIT,
            COMPONENT_FREEZE_COMMIT,
        ],
        "facts": {
            "required_trigger_cases_covered": 6,
            "stress_seed_blocks": stress_summary.get("seed_block_count"),
            "stress_protocol_effect_observed": True,
            "stress_consistent_holdout_benefit_observed": False,
            "component_persisted_trials": 554,
            "component_isolations_inconclusive": 5,
            "general_causal_benefit_claim_permitted": False,
        },
        "evidence": _records(
            repository_root,
            subject_commit,
            (*trigger_paths, *stress_paths, *component_paths),
        ),
        "claim_boundary": (
            "The frozen interventions prove named software-contract and synthetic "
            "protocol effects. They do not prove a general optimizer-quality, "
            "cost, LLM, PX4/Gazebo, physical, or real-flight benefit."
        ),
    }


def _multi_tool_closure(
    repository_root: Path,
    subject_commit: str,
) -> dict[str, Any]:
    paths = (
        *_prefixed_paths(
            MULTI_TOOL_PREFIX,
            (".csv", ".json", ".manifest.json", ".sha256"),
        ),
        MULTI_TOOL_GENERATION_RECEIPT,
    )
    _verify_frozen_paths(
        repository_root,
        freeze_commit=MULTI_TOOL_FREEZE_COMMIT,
        subject_commit=subject_commit,
        paths=paths,
    )
    artifact = _json_blob(repository_root, subject_commit, f"{MULTI_TOOL_PREFIX}.json")
    summary = _mapping(artifact.get("summary"), field="multi-tool summary")
    if (
        artifact.get("source_commit") != "136a1e3293efa6e53f3648e21fa8f7c6b5158d6f"
        or summary.get("configured_budget_parity_count") != 3
        or summary.get("scripted_multi_tool_generation_count") != 3
        or summary.get("scripted_decision_call_count") != 12
        or artifact.get("network_calls") != 0
    ):
        raise ValueError("multi-tool evaluation facts changed")
    return {
        "gap_id": "6.3",
        "status": "complete_for_bounded_execution_revision_and_cost_accounting",
        "freeze_commit": MULTI_TOOL_FREEZE_COMMIT,
        "facts": {
            "budget_parity_blocks": 3,
            "multi_tool_generations": 3,
            "schema_valid_local_decisions": 12,
            "real_provider_calls": 0,
            "network_calls": 0,
        },
        "evidence": _records(repository_root, subject_commit, paths),
        "claim_boundary": artifact.get("claim_boundary"),
    }


def _cross_job_closure(
    repository_root: Path,
    subject_commit: str,
) -> dict[str, Any]:
    paths = _prefixed_paths(
        CROSS_JOB_PREFIX,
        (".csv", ".json", ".manifest.json", ".sha256"),
    )
    _verify_frozen_paths(
        repository_root,
        freeze_commit=CROSS_JOB_FREEZE_COMMIT,
        subject_commit=subject_commit,
        paths=paths,
    )
    artifact = _json_blob(repository_root, subject_commit, f"{CROSS_JOB_PREFIX}.json")
    summary = _mapping(artifact.get("summary"), field="cross-job summary")
    if (
        summary.get("case_count") != 10
        or summary.get("passed_count") != 10
        or summary.get("failed_count") != 0
        or summary.get("provider_identifier_leak_count") != 0
        or summary.get("provider_calls") != 0
        or summary.get("network_calls") != 0
    ):
        raise ValueError("cross-job memory contract facts changed")
    return {
        "gap_id": "6.4",
        "status": "complete_for_retrieval_isolation_lifecycle_and_drift_contracts",
        "freeze_commit": CROSS_JOB_FREEZE_COMMIT,
        "facts": {
            "cases_passed": 10,
            "cases_total": 10,
            "positive_retrievals": 2,
            "negative_isolation_or_lifecycle_cases": 8,
            "provider_identifier_leaks": 0,
            "provider_calls": 0,
            "network_calls": 0,
            "legacy_manifest_has_source_commit": False,
            "closure_subject_supplies_exact_snapshot_binding": True,
        },
        "evidence": _records(repository_root, subject_commit, paths),
        "claim_boundary": artifact.get("claim_boundary"),
    }


def _advanced_physics_closure(
    repository_root: Path,
    subject_commit: str,
) -> dict[str, Any]:
    advanced_paths = (
        f"{ADVANCED_PHYSICS_PREFIX}.manifest.json",
        f"{ADVANCED_PHYSICS_PREFIX}.receipt.json",
        f"{ADVANCED_PHYSICS_PREFIX}.sha256",
        ADVANCED_PHYSICS_TEST_RECEIPT,
    )
    runtime_primary_paths = (
        f"{RUNTIME_PREFIX}/release-receipt.json",
        f"{RUNTIME_PREFIX}/release-receipt.json.sha256",
        f"{RUNTIME_PREFIX}/payload/runtime-release.json",
        f"{RUNTIME_PREFIX}/payload/runtime-release.json.sig",
        f"{RUNTIME_PREFIX}/fresh-import-receipt.json",
    )
    runtime_corrected_handoff_paths = (
        f"{RUNTIME_PREFIX}/handoff-manifest.json",
        f"{RUNTIME_PREFIX}/handoff-manifest.json.sha256",
        f"{RUNTIME_PREFIX}/payload/THIRD_PARTY_NOTICES.md",
    )
    _verify_frozen_paths(
        repository_root,
        freeze_commit=ADVANCED_PHYSICS_FREEZE_COMMIT,
        subject_commit=subject_commit,
        paths=advanced_paths,
    )
    _verify_frozen_paths(
        repository_root,
        freeze_commit=RUNTIME_FREEZE_COMMIT,
        subject_commit=subject_commit,
        paths=runtime_primary_paths,
    )
    _verify_frozen_paths(
        repository_root,
        freeze_commit=RUNTIME_HANDOFF_CORRECTION_COMMIT,
        subject_commit=subject_commit,
        paths=runtime_corrected_handoff_paths,
    )
    advanced = _json_blob(
        repository_root,
        subject_commit,
        f"{ADVANCED_PHYSICS_PREFIX}.receipt.json",
    )
    advanced_result = _mapping(advanced.get("result"), field="advanced result")
    runtime = _json_blob(
        repository_root,
        subject_commit,
        f"{RUNTIME_PREFIX}/release-receipt.json",
    )
    signature = _mapping(runtime.get("signature"), field="runtime signature")
    image_smoke = _mapping(runtime.get("image_smoke"), field="runtime image smoke")
    delivery = _mapping(runtime.get("delivery"), field="runtime delivery")
    if (
        advanced_result.get("verified_categories") != 9
        or advanced_result.get("remaining_runtime_extensions") != 0
        or advanced_result.get("all_effects_performance_successful") is not False
    ):
        raise ValueError("advanced-physics closure facts changed")
    if (
        signature.get("signature_valid") is not True
        or image_smoke.get("result") != "passed"
        or delivery.get("runtime_handoff_ready") is not True
        or delivery.get("upload_performed") is not False
    ):
        raise ValueError("runtime handoff facts changed")
    return {
        "gap_id": "6.5",
        "status": "complete_for_bundled_effect_contract_and_local_runtime_handoff",
        "freeze_commits": [
            ADVANCED_PHYSICS_FREEZE_COMMIT,
            RUNTIME_FREEZE_COMMIT,
            RUNTIME_HANDOFF_CORRECTION_COMMIT,
        ],
        "facts": {
            "verified_effect_categories": 9,
            "remaining_runtime_extensions": 0,
            "all_effects_performance_successful": False,
            "runtime_image_smoke": "passed",
            "runtime_manifest_signature_valid": True,
            "runtime_handoff_ready": True,
            "software_line_uploads": 0,
        },
        "evidence": _records(
            repository_root,
            subject_commit,
            (
                *advanced_paths,
                *runtime_primary_paths,
                *runtime_corrected_handoff_paths,
            ),
        ),
        "claim_boundary": (
            "The retained evidence proves request-bound application and read-back "
            "for all bundled physical-effect categories plus a signed local Runtime "
            "handoff. It does not claim universal perturbed-flight success, "
            "real-aircraft transfer, safety, or software-line publication."
        ),
    }


def _release_closure(
    repository_root: Path,
    subject_commit: str,
) -> dict[str, Any]:
    v10_paths = (
        f"{EVIDENCE_V10_PREFIX}.json",
        f"{EVIDENCE_V10_PREFIX}.manifest.json",
        f"{EVIDENCE_V10_PREFIX}.sha256",
    )
    installer_paths = (
        f"{INSTALLER_PREFIX}/release-receipt.json",
        f"{INSTALLER_PREFIX}/release-receipt.json.sha256",
        f"{INSTALLER_PREFIX}/handoff-manifest.json",
        f"{INSTALLER_PREFIX}/handoff-manifest.json.sha256",
        f"{INSTALLER_PREFIX}/DroneDream_1.0.0_x64-setup.exe.sha256",
        f"{INSTALLER_PREFIX}/DroneDream_1.0.0_x64-setup.exe.sig",
    )
    quality_paths = (
        f"{QUALITY_GATE_PREFIX}/quality-gate-receipt.json",
        f"{QUALITY_GATE_PREFIX}/quality-gate-receipt.sha256",
    )
    _verify_frozen_paths(
        repository_root,
        freeze_commit=EVIDENCE_V10_FREEZE_COMMIT,
        subject_commit=subject_commit,
        paths=v10_paths,
    )
    _verify_frozen_paths(
        repository_root,
        freeze_commit=INSTALLER_FREEZE_COMMIT,
        subject_commit=subject_commit,
        paths=installer_paths,
    )
    _verify_frozen_paths(
        repository_root,
        freeze_commit=QUALITY_GATE_FREEZE_COMMIT,
        subject_commit=subject_commit,
        paths=quality_paths,
    )
    v10 = _json_blob(
        repository_root,
        subject_commit,
        f"{EVIDENCE_V10_PREFIX}.manifest.json",
    )
    readiness = _mapping(v10.get("release_readiness"), field="v10 readiness")
    installer = _json_blob(
        repository_root,
        subject_commit,
        f"{INSTALLER_PREFIX}/release-receipt.json",
    )
    installer_artifact = _mapping(installer.get("artifact"), field="installer artifact")
    quality = _json_blob(
        repository_root,
        subject_commit,
        f"{QUALITY_GATE_PREFIX}/quality-gate-receipt.json",
    )
    quality_overall = _mapping(quality.get("overall"), field="quality overall")
    if readiness.get("release_ready") is not False:
        raise ValueError("v10 release-ready boundary changed")
    if (
        installer_artifact.get("sha256")
        != "9f44f79821dd27b283afcc57b3d4d194341a6cef655ce309c3609d1c834b3b8b"
        or installer_artifact.get("authenticode_status") != "NotSigned"
    ):
        raise ValueError("installer handoff identity changed")
    if (
        quality.get("subject_commit") != "bb1677a12175a51ce5c7d3bb8824d25365a50545"
        or quality.get("workflow", {}).get("conclusion") != "failure"
        or quality_overall.get("software_owned_quality_gates") != "passed"
        or quality_overall.get("remaining_failure_count") != 19
    ):
        raise ValueError("current quality receipt boundary changed")
    return {
        "gap_id": "6.6",
        "status": "software_receipts_complete_cross_line_report_gate_explicit",
        "freeze_commits": [
            EVIDENCE_V10_FREEZE_COMMIT,
            INSTALLER_FREEZE_COMMIT,
            QUALITY_GATE_FREEZE_COMMIT,
        ],
        "facts": {
            "v10_source_commit": v10.get("source_commit"),
            "v10_release_ready": False,
            "evidence_2_9_online_injected_into_frozen_v10": False,
            "installer_subject_commit": installer.get("source", {}).get("commit"),
            "installer_version": "1.0.0",
            "installer_sha256": installer_artifact.get("sha256"),
            "installer_authenticode_status": "NotSigned",
            "quality_subject_commit": quality.get("subject_commit"),
            "quality_backend_tests_passed": 1292,
            "quality_aggregate_workflow_conclusion": "failure",
            "quality_remaining_website_failures": 19,
            "technical_report_source_or_pdf_modified": False,
        },
        "evidence": _records(
            repository_root,
            subject_commit,
            (*v10_paths, *installer_paths, *quality_paths),
        ),
        "claim_boundary": (
            "Software source, test, installer, Runtime, and evidence receipts are "
            "frozen separately. The immutable v10 bundle remains release_ready=false "
            "and intentionally excludes the later Evidence 2.9 online freeze and "
            "current-head regression. Technical-report source/PDF and the remaining "
            "website visual gate are cross-line work and are not rewritten here."
        ),
    }


def build_harness_handoff_closure(
    *,
    repository_root: Path,
    subject_commit: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build and validate the exact-byte closure index without writing files."""

    repository_root = repository_root.resolve()
    subject_commit = _require_commit(subject_commit, field="subject_commit")
    generated_at = _require_utc_timestamp(generated_at, field="generated_at")
    _verify_subject(repository_root, subject_commit)
    closures = [
        _online_closure(repository_root, subject_commit),
        _ablation_closure(repository_root, subject_commit),
        _multi_tool_closure(repository_root, subject_commit),
        _cross_job_closure(repository_root, subject_commit),
        _advanced_physics_closure(repository_root, subject_commit),
        _release_closure(repository_root, subject_commit),
    ]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "subject_commit": subject_commit,
        "branch": "codex/software",
        "handoff_document": {
            "name": HANDOFF_DOCUMENT_NAME,
            "sha256": HANDOFF_DOCUMENT_SHA256,
            "ownership": "external user-supplied handoff; not copied into the repository",
        },
        "online_policy": {
            "openai_api_key_read": False,
            "harness_routing_api_key_read": False,
            "real_provider_calls_during_closure_export": 0,
            "authorization_state": "closed",
        },
        "closures": closures,
        "summary": {
            "gap_count": 6,
            "software_local_closures": 6,
            "general_causal_harness_benefit_claim_permitted": False,
            "universal_advanced_physics_performance_claim_permitted": False,
            "technical_report_release_ready": False,
            "remaining_cross_line_gates": [
                "website-owned bilingual typography/layout audit: 19 failures",
                "technical-report source/PDF update remains frozen and separate",
            ],
        },
        "claim_boundary": (
            "This index binds the software-owned implementation and evidence bytes "
            "that address handoff gaps 6.1 through 6.6 at one exact Git subject. "
            "It preserves negative and inconclusive results. It does not turn "
            "synthetic contracts into a general causal benefit, claim universal "
            "physical performance, or declare the frozen technical report/PDF ready."
        ),
    }
    payload["manifest_sha256"] = _sha256_bytes(_canonical_bytes(payload))
    return payload


def _atomic_write_new(path: Path, payload: bytes) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite frozen output: {path}")
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise FileExistsError(f"refusing to overwrite frozen output: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def export_harness_handoff_closure(
    *,
    repository_root: Path,
    subject_commit: str,
    generated_at: str,
    output_path: Path,
    checksum_path: Path,
) -> dict[str, Any]:
    """Write a new closure index and checksum without replacing a freeze."""

    closure = build_harness_handoff_closure(
        repository_root=repository_root,
        subject_commit=subject_commit,
        generated_at=generated_at,
    )
    output_bytes = _pretty_bytes(closure)
    checksum_bytes = f"{_sha256_bytes(output_bytes)}  {output_path.name}\n".encode("ascii")
    _atomic_write_new(output_path, output_bytes)
    try:
        _atomic_write_new(checksum_path, checksum_bytes)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    return closure


def verify_harness_handoff_closure(
    *,
    repository_root: Path,
    output_path: Path,
    checksum_path: Path,
) -> dict[str, Any]:
    """Recompute a frozen closure index and require exact output bytes."""

    raw = output_path.read_bytes()
    try:
        existing = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("closure output is not valid UTF-8 JSON") from exc
    existing_mapping = _mapping(existing, field="closure output")
    expected = build_harness_handoff_closure(
        repository_root=repository_root,
        subject_commit=_require_commit(
            existing_mapping.get("subject_commit"),
            field="subject_commit",
        ),
        generated_at=_require_utc_timestamp(
            existing_mapping.get("generated_at"),
            field="generated_at",
        ),
    )
    expected_bytes = _pretty_bytes(expected)
    if raw != expected_bytes:
        raise ValueError("closure output does not match exact recomputation")
    expected_checksum = f"{_sha256_bytes(raw)}  {output_path.name}\n".encode("ascii")
    if checksum_path.read_bytes() != expected_checksum:
        raise ValueError("closure checksum file does not match output bytes")
    return expected
