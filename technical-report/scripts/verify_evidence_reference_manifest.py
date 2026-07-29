from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def run_git(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def git_json(repo: Path, ref_commit: str, path: str) -> tuple[bytes, dict[str, Any]]:
    payload = run_git(repo, "show", f"{ref_commit}:{path}")
    return payload, json.loads(payload.decode("utf-8"))


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value: dict[str, Any], excluded_key: str) -> str:
    unsigned = dict(value)
    unsigned.pop(excluded_key, None)
    payload = json.dumps(
        unsigned,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload)


def canonical_value_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload)


def git_blob_oid(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def sha256_current_file(path: Path, serialization: str | None) -> str:
    payload = path.read_bytes()
    if serialization is None:
        return sha256(payload)
    if serialization != "utf8_lf":
        raise ValueError(f"unsupported current hash serialization: {serialization}")
    text = payload.decode("utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return sha256(normalized.encode("utf-8"))


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def verify_commit(repo: Path, commit: str, failures: list[str]) -> None:
    try:
        resolved = run_git(repo, "rev-parse", f"{commit}^{{commit}}").decode().strip()
    except subprocess.CalledProcessError:
        failures.append(f"missing commit: {commit}")
        return
    require(resolved == commit, f"commit did not resolve exactly: {commit}", failures)


def commit_resolves(repo: Path, commit: str) -> bool:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"],
        cwd=repo,
        capture_output=True,
    )
    return completed.returncode == 0


def verify_ancestor(repo: Path, ancestor: str, descendant: str, failures: list[str]) -> None:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo,
        capture_output=True,
    )
    require(
        completed.returncode == 0,
        f"ancestry mismatch: {ancestor} is not an ancestor of {descendant}",
        failures,
    )


def main() -> int:
    repo = Path(run_git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
    manifest_path = repo / "technical-report" / "evidence-reference-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    verified_artifacts: list[dict[str, str]] = []
    verified_sources: list[dict[str, str]] = []

    require(
        manifest.get("schema_version")
        == "dronedream.technical-report-evidence-reference-manifest.v1",
        "unexpected manifest schema",
        failures,
    )
    require(
        manifest.get("ownership", {}).get("raw_evidence_copied") is False,
        "manifest must forbid copied raw evidence",
        failures,
    )
    migration = manifest.get("migration_provenance", {})
    require(
        migration.get("external_source_read_only") is True,
        "external migration source must remain read-only",
        failures,
    )
    external_root = Path(str(migration.get("external_source_root", "")))
    for entry in migration.get("initial_byte_verification", []):
        relative = Path(entry["path"])
        external_path = Path(entry.get("external_source_path", external_root / relative))
        current_path = repo / "technical-report" / relative
        if not external_path.is_file():
            failures.append(f"missing external migration source: {relative}")
            continue
        source_actual = sha256_file(external_path)
        require(
            source_actual == entry["source_sha256"],
            f"external source SHA-256 mismatch: {relative}",
            failures,
        )
        if not current_path.is_file():
            failures.append(f"missing migrated report file: {relative}")
            continue
        try:
            current_actual = sha256_current_file(
                current_path,
                entry.get("current_hash_serialization"),
            )
        except (UnicodeDecodeError, ValueError) as exc:
            failures.append(f"invalid current hash serialization for {relative}: {exc}")
            continue
        if entry.get("modified_after_migration") is False:
            require(
                current_actual == entry["source_sha256"],
                f"unexpected post-migration change: {relative}",
                failures,
            )
        else:
            require(
                current_actual == entry.get("current_sha256"),
                f"declared post-migration SHA-256 mismatch: {relative}",
                failures,
            )

    software = manifest["software"]
    website = manifest["website"]
    physical = software["physical_campaign"]
    advanced = software["advanced_physics"]
    negative_control = software["advanced_physics_runtime_negative_control"]
    actuator_probe = software["advanced_physics_actuator_failure_probe"]
    advanced_closure = software["advanced_physics_closure"]
    evidence_v10 = software["evidence_v10"]
    documentation_alignment = software["documentation_alignment"]
    current_backend_regression = software["current_backend_regression"]
    cross_job = software["cross_job_memory"]
    online_routing = software["online_routing"]
    multi_tool_budget = software["multi_tool_budget"]
    commit_fields = [
        software["subject_commit"],
        software["provenance_commit"],
        software["branch_head"],
        evidence_v10["source_commit"],
        evidence_v10["freeze_commit"],
        documentation_alignment["commit"],
        current_backend_regression["subject_commit"],
        current_backend_regression["receipt_head"],
        cross_job["implementation_commit"],
        cross_job["subject_commit"],
        cross_job["receipt_head"],
        online_routing["implementation_commit"],
        online_routing["evidence_head"],
        multi_tool_budget["source_commit"],
        multi_tool_budget["evidence_head"],
        physical["subject_commit"],
        physical["reachable_implementation_commit"],
        physical["reachable_runtime_observation_commit"],
        physical["evidence_head"],
        advanced["subject_commit"],
        advanced["exporter_commit"],
        advanced["evidence_head"],
        negative_control["implementation_commit"],
        negative_control["evidence_head"],
        actuator_probe["implementation_commit"],
        actuator_probe["evidence_head"],
        advanced_closure["subject_commit"],
        advanced_closure["evidence_head"],
        website["subject_commit"],
        website["attestation_commit"],
    ]
    for commit in commit_fields:
        verify_commit(repo, commit, failures)

    verify_ancestor(
        repo,
        software["subject_commit"],
        software["provenance_commit"],
        failures,
    )
    verify_ancestor(
        repo,
        software["provenance_commit"],
        software["branch_head"],
        failures,
    )
    verify_ancestor(
        repo,
        cross_job["implementation_commit"],
        cross_job["subject_commit"],
        failures,
    )
    verify_ancestor(
        repo,
        cross_job["subject_commit"],
        cross_job["receipt_head"],
        failures,
    )
    require(
        cross_job["subject_commit"] == software["subject_commit"]
        and cross_job["receipt_head"] == software["provenance_commit"],
        "cross-Job memory chain must bind the software subject and v9 receipt head",
        failures,
    )
    verify_ancestor(
        repo,
        online_routing["implementation_commit"],
        online_routing["evidence_head"],
        failures,
    )
    verify_ancestor(
        repo,
        online_routing["evidence_head"],
        software["branch_head"],
        failures,
    )
    verify_ancestor(
        repo,
        multi_tool_budget["source_commit"],
        multi_tool_budget["evidence_head"],
        failures,
    )
    verify_ancestor(
        repo,
        multi_tool_budget["evidence_head"],
        software["branch_head"],
        failures,
    )
    verify_ancestor(
        repo,
        physical["subject_commit"],
        physical["reachable_implementation_commit"],
        failures,
    )
    verify_ancestor(
        repo,
        physical["reachable_implementation_commit"],
        physical["reachable_runtime_observation_commit"],
        failures,
    )
    verify_ancestor(
        repo,
        physical["reachable_runtime_observation_commit"],
        physical["evidence_head"],
        failures,
    )
    verify_ancestor(
        repo,
        physical["evidence_head"],
        software["branch_head"],
        failures,
    )
    verify_ancestor(
        repo,
        advanced["subject_commit"],
        advanced["exporter_commit"],
        failures,
    )
    verify_ancestor(
        repo,
        advanced["exporter_commit"],
        advanced["evidence_head"],
        failures,
    )
    verify_ancestor(
        repo,
        advanced["evidence_head"],
        negative_control["implementation_commit"],
        failures,
    )
    verify_ancestor(
        repo,
        negative_control["implementation_commit"],
        negative_control["evidence_head"],
        failures,
    )
    verify_ancestor(
        repo,
        negative_control["evidence_head"],
        actuator_probe["implementation_commit"],
        failures,
    )
    verify_ancestor(
        repo,
        actuator_probe["implementation_commit"],
        actuator_probe["evidence_head"],
        failures,
    )
    verify_ancestor(
        repo,
        actuator_probe["evidence_head"],
        advanced_closure["subject_commit"],
        failures,
    )
    verify_ancestor(
        repo,
        advanced_closure["subject_commit"],
        advanced_closure["evidence_head"],
        failures,
    )
    verify_ancestor(
        repo,
        advanced_closure["evidence_head"],
        evidence_v10["source_commit"],
        failures,
    )
    verify_ancestor(
        repo,
        evidence_v10["source_commit"],
        evidence_v10["freeze_commit"],
        failures,
    )
    verify_ancestor(
        repo,
        evidence_v10["freeze_commit"],
        documentation_alignment["commit"],
        failures,
    )
    verify_ancestor(
        repo,
        documentation_alignment["commit"],
        current_backend_regression["subject_commit"],
        failures,
    )
    verify_ancestor(
        repo,
        current_backend_regression["subject_commit"],
        current_backend_regression["receipt_head"],
        failures,
    )
    require(
        documentation_alignment
        == {
            "commit": "755c511539fe561207ca38ff5079f471a4110896",
            "authority": "secondary_narrative_reference",
            "experimental_evidence": False,
            "authoritative_evidence_source": (
                "evidence_v10_bundle_manifest_and_receipt"
            ),
        },
        "software documentation-alignment head or authority drifted",
        failures,
    )
    require(
        current_backend_regression
        == {
            "subject_commit": "755c511539fe561207ca38ff5079f471a4110896",
            "receipt_head": "1e542b7bc63908e1d9775eb7e8cd2bd0e3cabb3e",
            "generated_at": "2026-07-29T00:28:51Z",
            "exact_final_commit_run": True,
            "full_passed": 1284,
            "full_failed": 0,
            "full_pytest_seconds": 831.79,
            "focused_passed": 73,
            "focused_failed": 0,
            "focused_pytest_seconds": 29.73,
            "openai_api_key_removed_before_run": True,
            "provider_calls": 0,
            "claim_class": (
                "exact_source_offline_backend_regression_without_frontend_"
                "desktop_rust_release_or_physical_claim"
            ),
        }
        and current_backend_regression["subject_commit"]
        == documentation_alignment["commit"]
        and current_backend_regression["receipt_head"] == software["branch_head"],
        "current backend regression metadata or subject/receipt boundary drifted",
        failures,
    )
    require(
        physical.get("declared_commit_resolution")
        == "unresolvable_in_fetched_repository",
        "physical provenance discrepancy status drifted",
        failures,
    )
    for field in (
        "handoff_declared_exporter_verifier_commit",
        "embedded_exporter_observer_commit",
    ):
        declared_commit = str(physical[field])
        require(
            not commit_resolves(repo, declared_commit),
            f"physical declared source identifier unexpectedly resolves: {field}",
            failures,
        )
    verify_ancestor(
        repo,
        website["subject_commit"],
        website["attestation_commit"],
        failures,
    )

    software_json: dict[str, dict[str, Any]] = {}
    for artifact in software["artifacts"]:
        try:
            payload = run_git(
                repo,
                "show",
                f"{artifact['ref_commit']}:{artifact['path']}",
            )
        except subprocess.CalledProcessError:
            failures.append(f"unreadable software artifact: {artifact['id']}")
            continue
        actual = sha256(payload)
        require(
            actual == artifact["file_sha256"],
            f"SHA-256 mismatch for {artifact['id']}: {actual}",
            failures,
        )
        if str(artifact["path"]).endswith(".json"):
            try:
                software_json[artifact["id"]] = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                failures.append(f"unreadable software JSON artifact: {artifact['id']}")
        verified_artifacts.append({"id": artifact["id"], "sha256": actual})

    source_reference_ids: set[str] = set()
    reference_by_id = {
        str(item["id"]): item for item in software.get("source_references", [])
    }
    for source in software.get("source_references", []):
        source_id = str(source["id"])
        require(
            source_id not in source_reference_ids,
            f"duplicate software source reference: {source_id}",
            failures,
        )
        source_reference_ids.add(source_id)
        verify_commit(repo, source["ref_commit"], failures)
        verify_ancestor(repo, source["ref_commit"], software["branch_head"], failures)
        require(
            bool(str(source.get("evidence_role", "")).strip()),
            f"source reference lacks an evidence role: {source_id}",
            failures,
        )
        try:
            payload = run_git(
                repo,
                "show",
                f"{source['ref_commit']}:{source['path']}",
            )
        except subprocess.CalledProcessError:
            failures.append(f"unreadable software source reference: {source_id}")
            continue
        actual = sha256(payload)
        require(
            actual == source["file_sha256"],
            f"SHA-256 mismatch for {source_id}: {actual}",
            failures,
        )
        verified_sources.append(
            {
                "id": source_id,
                "path": source["path"],
                "sha256": actual,
            }
        )

    current_receipt_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "current_backend_regression_receipt"
    )
    current_manifest_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "current_backend_regression_manifest"
    )
    current_checksums_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "current_backend_regression_checksums"
    )
    current_full_junit_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "current_backend_regression_full_junit"
    )
    current_focused_junit_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "current_backend_regression_focused_junit"
    )
    current_receipt = software_json.get("current_backend_regression_receipt", {})
    current_manifest = software_json.get("current_backend_regression_manifest", {})
    current_focused_checks = current_receipt.get("focused_checks", [])
    current_focused = current_focused_checks[0] if current_focused_checks else {}
    require(
        current_receipt.get("schema_version") == "dronedream.test-run-receipt.v2"
        and current_receipt.get("source_commit")
        == current_backend_regression["subject_commit"]
        and current_receipt.get("generated_at")
        == current_backend_regression["generated_at"]
        and current_receipt.get("receipt_sha256")
        == current_receipt_entry["internal_receipt_sha256"]
        and canonical_json_sha256(current_receipt, "receipt_sha256")
        == current_receipt_entry["internal_receipt_sha256"]
        and current_receipt.get("full_suite", {}).get("result")
        == {"failed": 0, "passed": 1284, "status": "passed"}
        and current_receipt.get("full_suite", {})
        .get("tested_state", {})
        .get("exact_final_commit_run")
        is True
        and current_receipt.get("full_suite", {})
        .get("tested_state", {})
        .get("base_commit")
        == current_backend_regression["subject_commit"]
        and current_focused.get("result")
        == {"failed": 0, "passed": 73, "status": "passed"},
        "current backend exact-source receipt identity or counts drifted",
        failures,
    )
    current_manifest_full = current_manifest.get("full_suite", {})
    current_manifest_focused = current_manifest.get("focused_suite", {})
    current_environment = current_manifest.get("environment", {})
    require(
        current_manifest.get("schema_version")
        == "dronedream.software-regression-attestation.v1"
        and current_manifest.get("source_commit")
        == current_backend_regression["subject_commit"]
        and current_manifest.get("generated_at")
        == current_backend_regression["generated_at"]
        and current_manifest.get("tested_state", {}).get("exact_final_commit_run")
        is True
        and current_manifest_full.get("result") == "passed"
        and current_manifest_full.get("pytest_reported_duration_seconds") == 831.79
        and current_manifest_full.get("junit", {}).get("tests") == 1284
        and current_manifest_full.get("junit", {}).get("failures") == 0
        and current_manifest_full.get("junit", {}).get("errors") == 0
        and current_manifest_focused.get("result") == "passed"
        and current_manifest_focused.get("pytest_reported_duration_seconds") == 29.73
        and current_manifest_focused.get("junit", {}).get("tests") == 73
        and current_manifest_focused.get("junit", {}).get("failures") == 0
        and current_manifest_focused.get("junit", {}).get("errors") == 0
        and current_environment.get("openai_api_key_removed_before_run") is True
        and current_environment.get("real_credentials_used") is False
        and current_environment.get("real_provider_calls") == 0
        and current_manifest.get("receipt", {}).get("file_sha256")
        == current_receipt_entry["file_sha256"]
        and current_manifest.get("receipt", {}).get("internal_sha256")
        == current_receipt_entry["internal_receipt_sha256"],
        "current backend attestation manifest or claim boundary drifted",
        failures,
    )
    current_checksums = run_git(
        repo,
        "show",
        f"{current_checksums_entry['ref_commit']}:{current_checksums_entry['path']}",
    ).decode("utf-8")
    for digest, filename in (
        (current_manifest_entry["file_sha256"], "attestation-manifest.json"),
        ("6cf663090b5d649976072aeecb31508e252b9a02affe5a0155329521025efad0", "focused-suite.log"),
        (current_focused_junit_entry["file_sha256"], "focused-suite.xml"),
        ("a6b7d84a14fdb8f1dfb98591acdaca45230a15b3a60e52bf7104489d6e067958", "full-suite.log"),
        (current_full_junit_entry["file_sha256"], "full-suite.xml"),
        (current_receipt_entry["file_sha256"], "test-receipt.json"),
    ):
        require(
            f"{digest}  {filename}" in current_checksums,
            f"current backend checksum sidecar lacks {filename}",
            failures,
        )
    for entry, expected_tests in (
        (current_full_junit_entry, 1284),
        (current_focused_junit_entry, 73),
    ):
        junit_payload = run_git(
            repo,
            "show",
            f"{entry['ref_commit']}:{entry['path']}",
        )
        try:
            junit_root = ET.fromstring(junit_payload)
            junit_suite = next(junit_root.iter("testsuite"))
        except (ET.ParseError, StopIteration):
            failures.append(f"current backend JUnit is unreadable: {entry['id']}")
        else:
            require(
                junit_suite.attrib.get("tests") == str(expected_tests)
                and junit_suite.attrib.get("failures") == "0"
                and junit_suite.attrib.get("errors") == "0"
                and junit_suite.attrib.get("skipped") == "0",
                f"current backend JUnit result drifted: {entry['id']}",
                failures,
            )

    physical_manifest_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "px4_physical_campaign_manifest"
    )
    physical_receipt_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "px4_physical_campaign_receipt"
    )
    physical_manifest = software_json.get("px4_physical_campaign_manifest", {})
    physical_receipt = software_json.get("px4_physical_campaign_receipt", {})
    require(
        physical_manifest.get("schema_version")
        == "dronedream.px4-physical-campaign-evidence.v1",
        "physical campaign schema mismatch",
        failures,
    )
    require(
        physical_manifest.get("subject_commit") == physical["subject_commit"],
        "physical campaign subject mismatch",
        failures,
    )
    require(
        physical_manifest.get("exporter_commit")
        == physical["embedded_exporter_observer_commit"],
        "physical campaign embedded exporter identifier drifted",
        failures,
    )
    require(
        physical_manifest.get("manifest_sha256")
        == physical_manifest_entry["canonical_sha256"]
        == canonical_json_sha256(physical_manifest, "manifest_sha256"),
        "physical campaign canonical manifest SHA-256 mismatch",
        failures,
    )
    require(
        physical_receipt.get("receipt_sha256")
        == physical_receipt_entry["internal_receipt_sha256"]
        == canonical_json_sha256(physical_receipt, "receipt_sha256"),
        "physical campaign canonical receipt SHA-256 mismatch",
        failures,
    )
    receipt_manifest = physical_receipt.get("manifest", {})
    require(
        receipt_manifest.get("sha256") == physical_manifest_entry["file_sha256"]
        and receipt_manifest.get("manifest_sha256")
        == physical_manifest_entry["canonical_sha256"],
        "physical receipt-to-manifest binding mismatch",
        failures,
    )
    require(
        physical_receipt.get("subject_commit") == physical["subject_commit"]
        and physical_receipt.get("runtime_id")
        == "5e15a7a5-f943-5c38-a284-1bdcc9cd528f"
        and physical_receipt.get("px4_commit")
        == "6ea3539157ca358c70a515878b77077af7d4611d",
        "physical receipt identity mismatch",
        failures,
    )
    require(
        physical_receipt.get("result")
        == {
            "status": "passed",
            "trial_count": 6,
            "passed": 6,
            "failed": 0,
            "retained_failure_probes": 4,
        },
        "physical receipt result mismatch",
        failures,
    )
    summary = physical_manifest.get("summary", {})
    require(
        summary
        == {
            "evaluation_track_coverage_max": 0.981456,
            "evaluation_track_coverage_min": 0.949113,
            "full_source_inventory_sha256": (
                "7c814fa64e669bdaa3444d4481c8e6a350a5391fe13bc1fa8508ca3b8bd7fa04"
            ),
            "pass_count": 6,
            "retained_bytes": 49237750,
            "retained_failure_probe_count": 4,
            "retained_file_count": 154,
            "rmse_m_max": 0.444452,
            "rmse_m_min": 0.332254,
            "scenario_verified_applied_count": 4,
            "source_bytes": 248354595,
            "source_file_count": 598,
            "success_count": 6,
            "trial_count": 6,
        },
        "physical campaign summary mismatch",
        failures,
    )
    runtime = physical_manifest.get("runtime_identity", {})
    require(
        runtime.get("runtime_id") == "5e15a7a5-f943-5c38-a284-1bdcc9cd528f"
        and runtime.get("px4_commit_observed")
        == "6ea3539157ca358c70a515878b77077af7d4611d"
        and runtime.get("gazebo_sim_version_observed") == "8.14.0"
        and runtime.get("gazebo_harmonic_package_observed")
        == "1.0.0-1~noble"
        and runtime.get("mavsdk_version_observed") == "3.15.3"
        and runtime.get("pyulog_version_observed") == "1.2.3"
        and runtime.get("ubuntu_version_observed") == "24.04",
        "physical campaign Runtime environment mismatch",
        failures,
    )
    trials = physical_manifest.get("trials", [])
    expected_trials = [
        ("nominal", 41001, 0.352324, 1.498899, 0.978019, "not_requested"),
        ("steady_wind", 41001, 0.441664, 1.497033, 0.949113, "verified_applied"),
        (
            "static_obstacle",
            41001,
            0.337719,
            1.497054,
            0.979810,
            "verified_applied",
        ),
        ("nominal", 41002, 0.332254, 1.496354, 0.981456, "not_requested"),
        ("steady_wind", 41002, 0.444452, 1.497318, 0.950095, "verified_applied"),
        (
            "static_obstacle",
            41002,
            0.336025,
            1.498594,
            0.979194,
            "verified_applied",
        ),
    ]
    actual_trials = [
        (
            row.get("scenario"),
            row.get("seed"),
            row.get("metrics", {}).get("rmse_m"),
            row.get("metrics", {}).get("max_error_m"),
            row.get("metrics", {}).get("evaluation_track_coverage"),
            row.get("scenario_evidence", {}).get("verification_status"),
        )
        for row in trials
    ]
    require(actual_trials == expected_trials, "physical Trial matrix drifted", failures)
    require(
        len(trials) == 6
        and all(row.get("success") is True for row in trials)
        and all(row.get("pass_flag") is True for row in trials),
        "physical Trial success/pass flags drifted",
        failures,
    )
    attempts = physical_manifest.get("failure_history", {}).get("attempts", [])
    require(
        len(attempts) == 4
        and [row.get("attempt_count") for row in attempts] == [1, 2, 3, 4]
        and all(row.get("success") is False for row in attempts),
        "physical failure-probe history drifted",
        failures,
    )
    require(
        len(attempts) == 4
        and attempts[0].get("failure_reason")
        == "sensor_noise_level must be one of: low, medium, high"
        and "detected dubious ownership" in attempts[1].get("failure_reason", "")
        and attempts[2].get("failure_code") == "UNSUPPORTED_SCENARIO_EFFECT"
        and attempts[3].get("post_fix_reprocessing", {}).get("evidence_role")
        == "post-fix-parser-diagnostic-not-success-trial"
        and attempts[3].get("post_fix_reprocessing", {}).get("sample_count") == 6778,
        "physical failure classifications drifted",
        failures,
    )

    effect_assertions = {
        "px4_physical_wind_seed_41001_applied": (
            "/world/default/wind_info",
            "fa646b1d397c40f597f5b5acd214432f3b467ddedc2c3a579bb31cdbc16b12f9",
        ),
        "px4_physical_wind_seed_41002_applied": (
            "/world/default/wind_info",
            "29f7092a32989f72fd4424e448f12a6c66dd2f30e0cf8688f16d59c8558107d8",
        ),
    }
    for source_id, (readback_source, world_sdf_sha) in effect_assertions.items():
        source = reference_by_id[source_id]
        _, parsed = git_json(repo, source["ref_commit"], source["path"])
        observations = parsed["effects"][0]["evidence"]["verification"]["observations"]
        require(
            observations[0].get("source") == readback_source
            and observations[0].get("value", {}).get("enable_wind") is True
            and observations[0].get("value", {}).get("linear_velocity_mps")
            == {"x": 0.0, "y": 2.0, "z": 0.0}
            and observations[1].get("value", {}).get("sdf_sha256") == world_sdf_sha,
            f"physical wind read-back drifted: {source_id}",
            failures,
        )
    for source_id in (
        "px4_physical_obstacle_seed_41001_applied",
        "px4_physical_obstacle_seed_41002_applied",
    ):
        source = reference_by_id[source_id]
        _, parsed = git_json(repo, source["ref_commit"], source["path"])
        entity = parsed["effects"][0]["evidence"]["created_entities"][0]
        require(
            entity.get("service") == "/world/default/create"
            and entity.get("response_data") is True
            and entity.get("sdf_sha256")
            == "9824260767a952b16c5fa1fe191de86a0dc1a43f8b6f5fe2bbba4bb8bf700d23",
            f"physical obstacle creation evidence drifted: {source_id}",
            failures,
        )

    evidence_root = (
        "artifacts/technical-report/px4-physical-campaign-v1-5f0f62c"
    )
    tree_paths = [
        line
        for line in run_git(
            repo,
            "ls-tree",
            "-r",
            "--name-only",
            physical["evidence_head"],
            "--",
            evidence_root,
        )
        .decode()
        .splitlines()
        if line
    ]
    require(
        len(tree_paths) == physical["tree_file_count"] == 159,
        "physical evidence tree file count mismatch",
        failures,
    )
    retained_items = [
        item
        for row in [*trials, *attempts]
        for item in row.get("source_inventory", [])
        if item.get("retained") is True
    ]
    retained_items.extend(
        [
            {
                "retained_path": runtime["runtime_manifest"]["path"],
                "retained_sha256": runtime["runtime_manifest"]["sha256"],
            },
            {
                "retained_path": runtime["runtime_observation"]["path"],
                "retained_sha256": runtime["runtime_observation"]["sha256"],
            },
        ]
    )
    object_mismatches = 0
    for item in retained_items:
        path = f"{evidence_root}/{item['retained_path']}"
        try:
            payload = run_git(repo, "show", f"{physical['evidence_head']}:{path}")
        except subprocess.CalledProcessError:
            object_mismatches += 1
            continue
        if sha256(payload) != item["retained_sha256"]:
            object_mismatches += 1
    require(
        len(retained_items) == 156
        and object_mismatches == physical["tree_object_mismatch_count"] == 0,
        "physical retained-object inventory mismatch",
        failures,
    )

    advanced_manifest_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "advanced_physics_manifest"
    )
    advanced_receipt_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "advanced_physics_receipt"
    )
    advanced_digest_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "advanced_physics_digest"
    )
    advanced_manifest = software_json.get("advanced_physics_manifest", {})
    advanced_receipt = software_json.get("advanced_physics_receipt", {})
    require(
        advanced_manifest.get("schema_version")
        == "dronedream.advanced-physics-real-px4-manifest.v1"
        and advanced_manifest.get("subject_commit") == advanced["subject_commit"]
        and advanced_manifest.get("exporter_commit") == advanced["exporter_commit"]
        and advanced_manifest.get("generated_at") == advanced["generated_at"]
        and advanced_manifest.get("evidence_class") == advanced["evidence_class"]
        and advanced_manifest.get("claim_label") == "PHYSICAL_SIMULATION"
        and advanced_manifest.get("physical_fidelity") is True
        and advanced_manifest.get("real_aircraft_fidelity") is False
        and advanced_manifest.get("network_calls") == 0
        and advanced_manifest.get("real_credentials_used") is False,
        "advanced-physics manifest identity or claim boundary drifted",
        failures,
    )
    require(
        advanced_manifest.get("manifest_sha256")
        == advanced_manifest_entry["canonical_sha256"]
        == canonical_json_sha256(advanced_manifest, "manifest_sha256"),
        "advanced-physics canonical manifest SHA-256 mismatch",
        failures,
    )
    require(
        advanced_receipt.get("schema_version")
        == "dronedream.advanced-physics-real-px4-receipt.v1"
        and advanced_receipt.get("subject_commit") == advanced["subject_commit"]
        and advanced_receipt.get("exporter_commit") == advanced["exporter_commit"]
        and advanced_receipt.get("receipt_sha256")
        == advanced_receipt_entry["internal_receipt_sha256"]
        == canonical_json_sha256(advanced_receipt, "receipt_sha256"),
        "advanced-physics canonical receipt or source binding mismatch",
        failures,
    )
    advanced_receipt_manifest = advanced_receipt.get("manifest", {})
    require(
        advanced_receipt_manifest
        == {
            "bytes": 446837,
            "manifest_sha256": advanced_manifest_entry["canonical_sha256"],
            "path": "advanced-physics-real-px4-v1.manifest.json",
            "sha256": advanced_manifest_entry["file_sha256"],
        },
        "advanced-physics receipt-to-manifest binding mismatch",
        failures,
    )
    require(
        advanced_receipt.get("result")
        == {
            "attempt_count": 6,
            "file_backed_preflight_failures": 1,
            "gps_readiness_boundaries": 2,
            "passing_flights": 3,
            "status": "passed",
            "successful_flights": 3,
            "terminal_only_preflights": 3,
        }
        and advanced_receipt.get("px4_commit")
        == "6ea3539157ca358c70a515878b77077af7d4611d"
        and advanced_receipt.get("network_calls") == 0
        and advanced_receipt.get("real_credentials_used") is False,
        "advanced-physics receipt result drifted",
        failures,
    )
    advanced_summary = advanced_manifest.get("summary", {})
    require(
        advanced_summary
        == {
            "attempt_count": 6,
            "authoritative_boundary_directory": "gps-readiness-boundary-attempt-2",
            "authoritative_success_directory": "success-five-effects-attempt-4",
            "file_backed_preflight_failure_count": 1,
            "full_source_inventory_sha256": (
                "125463206a7965b3a1d1a524c7181b38c3c877202e65165fbec5351fe3acaded"
            ),
            "gps_readiness_boundary_count": 2,
            "passing_flight_count": 3,
            "retained_bytes": advanced["retained_bytes"],
            "retained_file_count": advanced["retained_file_count"],
            "source_bytes": advanced["source_bytes"],
            "source_file_count": advanced["source_file_count"],
            "successful_flight_count": 3,
            "terminal_only_preflight_count": 3,
        },
        "advanced-physics summary drifted",
        failures,
    )
    success_effects = [
        "battery.mass_payload_kg",
        "scenario_type.actuator_delay",
        "sensor_degradation.baro_noise_m",
        "sensor_degradation.imu_noise_scale",
        "wind_gusts",
    ]
    gps_effects = [
        "battery.mass_payload_kg",
        "scenario_type.actuator_delay",
        "sensor_degradation.baro_noise_m",
        "sensor_degradation.gps_noise_m",
        "sensor_degradation.imu_noise_scale",
        "wind_gusts",
    ]
    advanced_protocol = advanced_manifest.get("protocol", {})
    require(
        advanced_protocol
        == {
            "campaign_seed": 42001,
            "candidate_id": "baseline-mpc-xy-p-0.95",
            "gps_readiness_boundary_effects": gps_effects,
            "job_id": "advanced-physics-real-px4-26b957e",
            "simulator": "px4_gazebo",
            "successful_flight_effects": success_effects,
            "unsupported_effects_included": False,
            "vehicle": "x500",
            "world": "default",
        },
        "advanced-physics protocol drifted",
        failures,
    )
    advanced_runtime = advanced_manifest.get("runtime_identity", {})
    require(
        advanced_runtime
        == {
            "gazebo_version_claimed": False,
            "identity_source": (
                "per-Trial firmware Git readback plus authoritative execution windows"
            ),
            "px4_commit": "6ea3539157ca358c70a515878b77077af7d4611d",
            "px4_version": "v1.16",
            "runtime_user": "dronedream",
            "wsl_runtime_id_claimed": False,
        },
        "advanced-physics Runtime identity drifted",
        failures,
    )
    require(
        advanced_manifest.get("remaining_runtime_extensions")
        == [
            "probabilistic GPS dropout",
            "battery initial state and voltage sag",
            "hard actuator failure beyond the bounded first-order delay profile",
        ],
        "advanced-physics remaining Runtime extensions drifted",
        failures,
    )
    terminal_preflights = advanced_manifest.get("terminal_only_preflights", {})
    require(
        terminal_preflights.get("attempts")
        == [
            {
                "failure": "windows_to_wsl_command_marshalling",
                "machine_verified": False,
                "raw_artifact_available": False,
                "recorded_at": "2026-07-28T20:09:24Z",
                "sequence": 1,
            },
            {
                "failure": "wsl_git_could_not_parse_windows_worktree_pointer",
                "machine_verified": False,
                "raw_artifact_available": False,
                "recorded_at": None,
                "sequence": 2,
            },
            {
                "failure": "process_probe_false_positive_from_path_text",
                "machine_verified": False,
                "raw_artifact_available": False,
                "recorded_at": None,
                "sequence": 3,
            },
        ]
        and "no invented hashes" in terminal_preflights.get("claim", ""),
        "advanced-physics terminal-only preflight history drifted",
        failures,
    )
    advanced_attempts = advanced_manifest.get("attempts", [])
    require(
        len(advanced_attempts) == 6
        and [row.get("directory") for row in advanced_attempts]
        == [
            "success-five-effects",
            "success-five-effects-attempt-2",
            "success-five-effects-attempt-3",
            "success-five-effects-attempt-4",
            "gps-readiness-boundary",
            "gps-readiness-boundary-attempt-2",
        ]
        and [row.get("role") for row in advanced_attempts]
        == [
            "file_backed_preflight_failure",
            "repeat_success",
            "repeat_success",
            "authoritative_success",
            "repeat_gps_readiness_boundary",
            "authoritative_gps_readiness_boundary",
        ],
        "advanced-physics attempt chronology drifted",
        failures,
    )
    advanced_successes = [row for row in advanced_attempts if row.get("success") is True]
    advanced_boundaries = [
        row for row in advanced_attempts if "gps_readiness_boundary" in row.get("role", "")
    ]
    require(
        len(advanced_successes) == 3
        and all(row.get("pass_flag") is True for row in advanced_successes)
        and [row.get("metrics") for row in advanced_successes]
        == [
            {
                "completion_time_s": 21.064,
                "evaluation_track_coverage": 0.952893,
                "max_error_m": 1.496421,
                "rmse_m": 0.37425,
                "score": 2.175661,
            },
            {
                "completion_time_s": 20.96,
                "evaluation_track_coverage": 0.953049,
                "max_error_m": 1.499264,
                "rmse_m": 0.368624,
                "score": 2.166256,
            },
            {
                "completion_time_s": 20.976,
                "evaluation_track_coverage": 0.954955,
                "max_error_m": 1.499631,
                "rmse_m": 0.37141,
                "score": 2.170025,
            },
        ]
        and all(
            row.get("effect_evidence", {}).get("requested_effects") == success_effects
            and row.get("effect_evidence", {}).get("applied_effects") == success_effects
            and row.get("effect_evidence", {}).get("verification_status")
            == "verified_applied"
            for row in advanced_successes
        ),
        "advanced-physics successful trajectory evidence drifted",
        failures,
    )
    require(
        len(advanced_boundaries) == 2
        and all(row.get("success") is False for row in advanced_boundaries)
        and all(row.get("pass_flag") is None for row in advanced_boundaries)
        and all(row.get("metrics") is None for row in advanced_boundaries)
        and all(
            row.get("effect_evidence", {}).get("requested_effects") == gps_effects
            and row.get("effect_evidence", {}).get("applied_effects") == gps_effects
            and row.get("effect_evidence", {}).get("verification_status")
            == "verified_applied"
            for row in advanced_boundaries
        ),
        "advanced-physics GPS readiness boundary drifted",
        failures,
    )
    require(
        advanced_attempts[0].get("failure_code") == "SIMULATION_FAILED"
        and "detected dubious ownership" in advanced_attempts[0].get("failure_reason", "")
        and advanced_attempts[3].get("authoritative") is True
        and advanced_attempts[3].get("execution_window")
        == {
            "duration_seconds": 82,
            "ended_at": "2026-07-28T20:21:16Z",
            "preexisting_process_count": 0,
            "present": True,
            "residual_process_count": 0,
            "runner_exit_code": 0,
            "runtime_user": "dronedream",
            "source_preflight": "windows_git_head_and_tracked_diff",
            "started_at": "2026-07-28T20:19:54Z",
        }
        and advanced_attempts[5].get("authoritative") is True
        and advanced_attempts[5].get("execution_window")
        == {
            "duration_seconds": 74,
            "ended_at": "2026-07-28T20:22:52Z",
            "preexisting_process_count": 0,
            "present": True,
            "residual_process_count": 0,
            "runner_exit_code": 0,
            "runtime_user": "dronedream",
            "source_preflight": "windows_git_head_and_tracked_diff",
            "started_at": "2026-07-28T20:21:38Z",
        },
        "advanced-physics file-backed failure or execution windows drifted",
        failures,
    )
    full_source_inventory: list[dict[str, Any]] = []
    advanced_retained: list[dict[str, Any]] = []
    for attempt in advanced_attempts:
        source_inventory = attempt.get("source_inventory", [])
        projected = [
            {
                "source_path": row["source_path"],
                "source_bytes": row["source_bytes"],
                "source_sha256": row["source_sha256"],
            }
            for row in source_inventory
        ]
        require(
            canonical_value_sha256(projected) == attempt.get("source_inventory_sha256"),
            f"advanced-physics attempt inventory hash drifted: {attempt.get('directory')}",
            failures,
        )
        full_source_inventory.extend(
            {
                **row,
                "source_path": f"{attempt['directory']}/{row['source_path']}",
            }
            for row in source_inventory
        )
        advanced_retained.extend(
            row for row in source_inventory if row.get("retained") is True
        )
    full_inventory_projection = [
        {
            "source_path": row["source_path"],
            "source_bytes": row["source_bytes"],
            "source_sha256": row["source_sha256"],
        }
        for row in full_source_inventory
    ]
    require(
        len(full_source_inventory) == advanced["source_file_count"]
        and sum(row["source_bytes"] for row in full_source_inventory)
        == advanced["source_bytes"]
        and canonical_value_sha256(full_inventory_projection)
        == advanced_summary["full_source_inventory_sha256"],
        "advanced-physics full source inventory drifted",
        failures,
    )
    advanced_root = (
        "artifacts/technical-report/advanced-physics-real-px4-v1-26b957e"
    )
    advanced_object_mismatches = 0
    for item in advanced_retained:
        path = f"{advanced_root}/{item['retained_path']}"
        try:
            payload = run_git(repo, "show", f"{advanced['evidence_head']}:{path}")
        except subprocess.CalledProcessError:
            advanced_object_mismatches += 1
            continue
        if (
            len(payload) != item["retained_bytes"]
            or sha256(payload) != item["retained_sha256"]
        ):
            advanced_object_mismatches += 1
    require(
        len(advanced_retained) == advanced["retained_file_count"]
        and sum(item["retained_bytes"] for item in advanced_retained)
        == advanced["retained_bytes"]
        and advanced_object_mismatches == 0,
        "advanced-physics retained-object inventory mismatch",
        failures,
    )
    tree_lines = [
        line
        for line in run_git(
            repo,
            "ls-tree",
            "-r",
            "-l",
            advanced["evidence_head"],
            "--",
            advanced_root,
        )
        .decode("utf-8")
        .splitlines()
        if line
    ]
    advanced_tree_bytes = 0
    tree_object_mismatches = 0
    for line in tree_lines:
        left, path = line.split("\t", 1)
        _, object_type, object_id, object_bytes = left.split()
        advanced_tree_bytes += int(object_bytes)
        if object_type != "blob":
            tree_object_mismatches += 1
            continue
        try:
            payload = run_git(repo, "show", f"{advanced['evidence_head']}:{path}")
        except subprocess.CalledProcessError:
            tree_object_mismatches += 1
            continue
        if git_blob_oid(payload) != object_id:
            tree_object_mismatches += 1
    require(
        len(tree_lines) == advanced["tree_file_count"] == 114
        and advanced_tree_bytes == advanced["tree_bytes"] == 9442999
        and tree_object_mismatches
        == advanced["tree_object_mismatch_count"]
        == 0,
        "advanced-physics Git tree or blob inventory mismatch",
        failures,
    )
    advanced_manifest_payload = run_git(
        repo,
        "show",
        f"{advanced['evidence_head']}:{advanced_manifest_entry['path']}",
    )
    advanced_receipt_payload = run_git(
        repo,
        "show",
        f"{advanced['evidence_head']}:{advanced_receipt_entry['path']}",
    )
    expected_digest = (
        f"{sha256(advanced_manifest_payload)}  advanced-physics-real-px4-v1.manifest.json\n"
        f"{sha256(advanced_receipt_payload)}  advanced-physics-real-px4-v1.receipt.json\n"
    ).encode("ascii")
    actual_digest = run_git(
        repo,
        "show",
        f"{advanced['evidence_head']}:{advanced_digest_entry['path']}",
    )
    require(
        actual_digest == expected_digest,
        "advanced-physics sidecar binding drifted",
        failures,
    )
    authoritative_ulog = next(
        item
        for item in advanced_retained
        if item.get("retained_path", "").endswith(
            "success-five-effects-attempt-4/px4_source.ulg.gz"
        )
    )
    ulog_payload = run_git(
        repo,
        "show",
        f"{advanced['evidence_head']}:{advanced_root}/{authoritative_ulog['retained_path']}",
    )
    require(
        authoritative_ulog.get("compression") == "gzip-level-9-mtime-0"
        and ulog_payload[:3] == b"\x1f\x8b\x08"
        and ulog_payload[4:8] == b"\x00\x00\x00\x00",
        "advanced-physics authoritative ULog compression drifted",
        failures,
    )
    gps_stdout_entry = reference_by_id["advanced_physics_gps_boundary_stdout"]
    gps_stdout = run_git(
        repo,
        "show",
        f"{gps_stdout_entry['ref_commit']}:{gps_stdout_entry['path']}",
    ).decode("utf-8")
    gps_stderr_entry = reference_by_id["advanced_physics_gps_boundary_stderr"]
    gps_stderr = run_git(
        repo,
        "show",
        f"{gps_stderr_entry['ref_commit']}:{gps_stderr_entry['path']}",
    ).decode("utf-8")
    require(
        "Waiting 30s for PX4 readiness" in gps_stdout
        and "PX4 readiness timeout after 30.0s" in gps_stderr,
        "advanced-physics GPS readiness timeout boundary drifted",
        failures,
    )

    negative_receipt = software_json.get(
        "advanced_physics_runtime_negative_control_receipt", {}
    )
    negative_lineage = software_json.get(
        "advanced_physics_runtime_negative_control_failure_lineage", {}
    )
    negative_scenario = software_json.get(
        "advanced_physics_runtime_negative_control_scenario_applied", {}
    )
    require(
        negative_control
        == {
            "implementation_commit": "fdf1250398567c6658ad5148efc1c302dede4a17",
            "evidence_head": "2f1caae6fbb5b037e55a4b339dff6c590833f019",
            "evidence_class": "REAL_PX4_GAZEBO_GPS_BATTERY_NEGATIVE_CONTROL",
            "claim_class": (
                "verified_injection_readback_and_completed_trial_with_failed_"
                "stability_acceptance"
            ),
            "trial_success": True,
            "pass_flag": False,
            "applied_effect_count": 3,
            "focused_test_count": 159,
        },
        "advanced-physics negative-control manifest metadata drifted",
        failures,
    )
    negative_physical = negative_receipt.get("physical_run", {})
    require(
        negative_receipt.get("schema_version")
        == "dronedream.advanced-physics-runtime-receipt/v1"
        and negative_physical.get("runner_exit_code") == 0
        and negative_physical.get("acceptance_exit_code") == 0
        and negative_physical.get("trial_success") is True
        and negative_physical.get("duration_seconds") == 76
        and negative_physical.get("residual_process_count") == 0
        and negative_physical.get("openai_api_key_used") is False
        and negative_physical.get("environment", {}).get("px4_firmware_commit")
        == "6ea3539157ca358c70a515878b77077af7d4611d"
        and negative_physical.get("environment", {}).get("vehicle") == "x500"
        and negative_physical.get("environment", {}).get("world") == "default",
        "advanced-physics negative-control execution boundary drifted",
        failures,
    )
    negative_effect = negative_receipt.get("effect_result", {})
    require(
        negative_effect.get("verification_status") == "verified_applied"
        and negative_effect.get("applied_effects")
        == [
            "battery.initial_percent",
            "battery.voltage_sag",
            "sensor_degradation.dropout_rate",
        ]
        and negative_effect.get("requested_dropout_rate") == 0.2
        and negative_effect.get("tick_count") == 29
        and negative_effect.get("off_tick_count") == 6
        and negative_effect.get("realized_dropout_rate")
        == 0.20689655172413793
        and negative_effect.get("gps_control_parameter") == "SIM_GPS_USED"
        and negative_effect.get("gps_baseline_value") == 10
        and negative_effect.get("gps_dropout_value") == 0
        and negative_effect.get("gps_restore_verified") is True
        and negative_effect.get("battery_track_start", {}).get("remaining_percent")
        == 92.0
        and negative_effect.get("battery_track_start", {}).get("voltage_v")
        == 16.020000457763672
        and negative_effect.get("battery_track_end", {}).get("remaining_percent")
        == 80.0
        and negative_effect.get("battery_track_end", {}).get("voltage_v")
        == 15.825000762939453,
        "advanced-physics negative-control effect read-back drifted",
        failures,
    )
    require(
        negative_receipt.get("independent_ulog_review")
        == {
            "dataset": "sensor_gps",
            "fix_3d_sample_count": 49,
            "no_gps_sample_count": 7,
            "observed_fix_types": [0, 3],
            "observed_satellites_used": [0, 10],
            "physical_transition_verified": True,
            "sample_count": 56,
        },
        "advanced-physics negative-control ULog review drifted",
        failures,
    )
    require(
        negative_receipt.get("outcome")
        == {
            "crash_flag": False,
            "instability_flag": True,
            "instability_reasons": ["position_speed_exceeded"],
            "interpretation": (
                "The requested physical effects were verified and the trial "
                "completed, but the controller outcome correctly failed the "
                "stability policy under this deterministic dropout schedule."
            ),
            "max_error_m": 1.498568,
            "maximum_observed_position_speed_mps": 31.211302,
            "pass_flag": False,
            "policy_limit_position_speed_mps": 25.0,
            "rmse_m": 0.345207,
            "timeout_flag": False,
            "track_coverage": 0.983807,
        },
        "advanced-physics negative-control outcome drifted",
        failures,
    )
    focused = negative_receipt.get("focused_test_receipt", {})
    require(
        focused.get("source_commit") == negative_control["implementation_commit"]
        and focused.get("tests") == 159
        and focused.get("passed") == 159
        and focused.get("failures") == 0
        and focused.get("errors") == 0
        and focused.get("skipped") == 0
        and focused.get("openai_api_key_used") is False
        and focused.get("junit_xml", {}).get("sha256")
        == "67d614764b213408833f50be63c0490e27c99dbcca41f349ab6281b605fc6b8c",
        "advanced-physics negative-control focused-test receipt drifted",
        failures,
    )
    receipt_artifacts = negative_receipt.get("artifacts", {})
    require(
        receipt_artifacts.get("px4_source.ulg", {}).get("sha256")
        == "dc3b156e6ae6144263e493ec59b566ba3d7772a5ffdca8345c66218afec07f90"
        and receipt_artifacts.get("scenario_effects.applied.json", {}).get("sha256")
        == "7973680f267b2643690b998b84111ffb3887f1efc2cf556b09acd1d73a24846a",
        "advanced-physics negative-control receipt artifact binding drifted",
        failures,
    )
    attempt_16 = negative_lineage.get("attempt_16", {})
    require(
        negative_lineage.get("subject_commit")
        == negative_control["implementation_commit"]
        and attempt_16.get("px4_ulog", {}).get("vehicle_command_420_count") == 2
        and attempt_16.get("px4_ulog", {}).get("vehicle_command_ack_420_count") == 0
        and "gz_bridge" in str(attempt_16.get("root_cause", ""))
        and "SimulatorMavlink failure handler is absent"
        in str(attempt_16.get("root_cause", ""))
        and negative_lineage.get("authoritative_resolution", {}).get(
            "exact_commit_attempt"
        )
        == 18
        and negative_lineage.get("authoritative_resolution", {}).get("mechanism")
        == "PX4 gz_bridge SIM_GPS_USED with exact parameter readback and MAVSDK gps_info telemetry",
        "advanced-physics negative-control failure lineage drifted",
        failures,
    )
    scenario_effects = negative_scenario.get("effects", [])
    require(
        len(scenario_effects) == 3
        and [item.get("effect_id") for item in scenario_effects]
        == [
            "sensor_degradation.dropout_rate",
            "battery.initial_percent",
            "battery.voltage_sag",
        ]
        and all(item.get("status") == "applied" for item in scenario_effects)
        and all(
            item.get("capability", {}).get("status") == "available"
            and item.get("evidence", {}).get("verification", {}).get("status")
            == "verified"
            for item in scenario_effects
        ),
        "advanced-physics negative-control scenario effect record drifted",
        failures,
    )
    junit_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "advanced_physics_runtime_negative_control_focused_junit"
    )
    junit_payload = run_git(
        repo,
        "show",
        f"{junit_entry['ref_commit']}:{junit_entry['path']}",
    )
    try:
        junit_root = ET.fromstring(junit_payload)
        junit_suite = next(junit_root.iter("testsuite"))
    except (ET.ParseError, StopIteration):
        failures.append("advanced-physics negative-control JUnit is unreadable")
    else:
        require(
            junit_suite.attrib.get("tests") == "159"
            and junit_suite.attrib.get("failures") == "0"
            and junit_suite.attrib.get("errors") == "0"
            and junit_suite.attrib.get("skipped") == "0",
            "advanced-physics negative-control JUnit result drifted",
            failures,
        )

    actuator_receipt = software_json.get(
        "advanced_physics_actuator_failure_receipt", {}
    )
    actuator_scenario = software_json.get(
        "advanced_physics_actuator_failure_scenario_applied", {}
    )
    actuator_preflight = software_json.get(
        "advanced_physics_actuator_failure_preflight_attempt_0", {}
    )
    require(
        actuator_probe
        == {
            "implementation_commit": "793f02089413f2baa8ea78387cd1e9e078f02b83",
            "evidence_head": "2da6a4fdb2af8ac711dd4eb07e7aeaf08de91b53",
            "evidence_class": "REAL_PX4_GAZEBO_ACTUATOR_FAILURE_INJECTION_READBACK",
            "claim_class": (
                "verified_sdf_and_joint_state_injection_without_trusted_"
                "flight_evaluation"
            ),
            "trial_success": False,
            "physical_effect_verified": True,
            "focused_test_count": 138,
        },
        "advanced-physics actuator-probe manifest metadata drifted",
        failures,
    )
    actuator_physical = actuator_receipt.get("physical_run", {})
    require(
        actuator_receipt.get("schema_version")
        == "dronedream.advanced-physics-actuator-failure-receipt/v1"
        and actuator_receipt.get("subject_commit")
        == actuator_probe["implementation_commit"]
        and actuator_physical.get("duration_seconds") == 82
        and actuator_physical.get("runner_exit_code") == 0
        and actuator_physical.get("acceptance_exit_code") == 0
        and actuator_physical.get("trial_success") is False
        and actuator_physical.get("physical_effect_verified") is True
        and actuator_physical.get("preexisting_process_count") == 0
        and actuator_physical.get("residual_process_count") == 0
        and actuator_physical.get("openai_api_key_used") is False
        and actuator_physical.get("environment", {}).get("runtime")
        == "DroneDreamRuntime"
        and actuator_physical.get("environment", {}).get("gazebo_sim_version")
        == "8.14.0"
        and actuator_physical.get("environment", {}).get("px4_version") == "v1.16"
        and actuator_physical.get("environment", {}).get("px4_firmware_commit")
        == "6ea3539157ca358c70a515878b77077af7d4611d"
        and actuator_physical.get("environment", {}).get("vehicle") == "x500",
        "advanced-physics actuator-probe execution boundary drifted",
        failures,
    )
    requested_actuator = actuator_receipt.get("requested_effect", {})
    actuator_effect = actuator_receipt.get("effect_result", {})
    actuator_sdf = actuator_effect.get("generated_world_sdf", {})
    actuator_joint = actuator_effect.get("gazebo_joint_state", {})
    require(
        requested_actuator
        == {
            "effect_id": "scenario_type.actuator_failure",
            "failure_mode": "stuck_stopped_at_launch",
            "target_joint_name": "rotor_2_joint",
            "target_motor_number": 2,
        }
        and actuator_effect.get("verification_status") == "verified_applied"
        and actuator_effect.get("verification_method")
        == "trial_local_sdf_generated_world_plus_gazebo_joint_state"
        and actuator_sdf.get("motor_max_rot_velocity_rad_s")
        == {"0": 1000.0, "1": 1000.0, "2": 0.0, "3": 1000.0}
        and actuator_joint.get("target_sample_count") == 641
        and actuator_joint.get("target_max_abs_velocity_rad_s") == 8.93786e-07
        and actuator_joint.get("max_failed_motor_abs_velocity_rad_s") == 0.05
        and actuator_joint.get("hard_stop_verified") is True
        and actuator_joint.get("healthy_sample_counts")
        == {"rotor_0_joint": 653, "rotor_1_joint": 653, "rotor_3_joint": 653}
        and actuator_joint.get("min_healthy_motor_abs_velocity_rad_s") == 1.0
        and actuator_joint.get("healthy_motion_verified") is True
        and all(
            99.99 < float(value) < 100.01
            for value in actuator_joint.get(
                "healthy_joint_max_abs_velocity_rad_s", {}
            ).values()
        ),
        "advanced-physics actuator-probe physical read-back drifted",
        failures,
    )
    actuator_outcome = actuator_receipt.get("trial_outcome", {})
    require(
        actuator_outcome.get("success") is False
        and actuator_outcome.get("failure_code") == "SIMULATION_FAILED"
        and actuator_outcome.get("reason")
        == "trusted evaluation window could not be established from offboard timing or telemetry"
        and actuator_outcome.get("offboard_executor_exit")
        == "completed successfully"
        and "no score or pass result is claimed"
        in str(actuator_outcome.get("interpretation", "")),
        "advanced-physics actuator-probe outcome boundary drifted",
        failures,
    )
    actuator_focused = actuator_receipt.get("focused_test_receipt", {})
    require(
        actuator_focused.get("source_commit")
        == actuator_probe["implementation_commit"]
        and actuator_focused.get("tests") == 138
        and actuator_focused.get("passed") == 138
        and actuator_focused.get("failures") == 0
        and actuator_focused.get("errors") == 0
        and actuator_focused.get("skipped") == 0
        and actuator_focused.get("openai_api_key_used") is False
        and actuator_focused.get("junit_xml", {}).get("sha256")
        == "65e027756f66e7fe7df4ccdc2e172bf821be9fbd104b71ac5199eee939a924d5",
        "advanced-physics actuator-probe focused-test receipt drifted",
        failures,
    )
    actuator_artifacts = actuator_receipt.get("artifacts", {})
    require(
        actuator_artifacts.get("px4_source.ulg", {}).get("sha256")
        == "fd01f02f7a97ee8ad3650e9687a6aa07a1197f46b76b19c1146fbe913f513f76"
        and actuator_artifacts.get("actuator_failure_joint_state.log", {}).get(
            "sha256"
        )
        == "f927dbb6561e912a80ae69e368cc65e14a5427640e5e83f8b933838e38e08e10"
        and actuator_artifacts.get("scenario_effects.applied.json", {}).get(
            "sha256"
        )
        == "8995d7b926c2745018a68159ef370e309c4b19370cbf1abca0b0e49c693d6458"
        and actuator_artifacts.get("preflight-failure-attempt-0.json", {}).get(
            "sha256"
        )
        == "72471490aa92fb132ea01fb941557c2c8dbd3f4cb77d480fa9fc14c00a97df2d",
        "advanced-physics actuator-probe artifact binding drifted",
        failures,
    )
    actuator_effect_rows = actuator_scenario.get("effects", [])
    require(
        len(actuator_effect_rows) == 1
        and actuator_effect_rows[0].get("effect_id")
        == "scenario_type.actuator_failure"
        and actuator_effect_rows[0].get("status") == "applied"
        and actuator_effect_rows[0].get("capability", {}).get("status")
        == "available"
        and actuator_effect_rows[0]
        .get("evidence", {})
        .get("verification", {})
        .get("status")
        == "verified",
        "advanced-physics actuator-probe scenario effect record drifted",
        failures,
    )
    require(
        actuator_preflight.get("subject_head_verified_by_windows_git")
        == actuator_probe["implementation_commit"]
        and actuator_preflight.get("exit_code") == 66
        and actuator_preflight.get("phase") == "preflight_before_px4_launch"
        and "WSL git could not resolve the Windows worktree .git pointer"
        == actuator_preflight.get("reason")
        and actuator_preflight.get("px4_or_gazebo_started") is False
        and actuator_preflight.get("residual_process_count") == 0
        and actuator_preflight.get("openai_api_key_used") is False,
        "advanced-physics actuator-probe preflight lineage drifted",
        failures,
    )
    actuator_junit_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "advanced_physics_actuator_failure_focused_junit"
    )
    actuator_junit_payload = run_git(
        repo,
        "show",
        f"{actuator_junit_entry['ref_commit']}:{actuator_junit_entry['path']}",
    )
    try:
        actuator_junit_root = ET.fromstring(actuator_junit_payload)
        actuator_junit_suite = next(actuator_junit_root.iter("testsuite"))
    except (ET.ParseError, StopIteration):
        failures.append("advanced-physics actuator-probe JUnit is unreadable")
    else:
        require(
            actuator_junit_suite.attrib.get("tests") == "138"
            and actuator_junit_suite.attrib.get("failures") == "0"
            and actuator_junit_suite.attrib.get("errors") == "0"
            and actuator_junit_suite.attrib.get("skipped") == "0",
            "advanced-physics actuator-probe JUnit result drifted",
            failures,
        )

    closure_manifest = software_json.get("advanced_physics_closure_manifest", {})
    closure_receipt = software_json.get("advanced_physics_closure_receipt", {})
    closure_test_receipt = software_json.get(
        "advanced_physics_closure_test_receipt", {}
    )
    require(
        advanced_closure
        == {
            "subject_commit": "f1e8fa855ebe95bf5ce208d62da7a3a46bba6228",
            "evidence_head": "83982f37899f8054e24a749af8e6469fedf48e8d",
            "evidence_class": "REAL_PX4_GAZEBO_BUNDLED_EFFECT_CLOSURE",
            "claim_class": (
                "nine_of_nine_injection_readback_coverage_with_five_"
                "performance_successful_categories"
            ),
            "verified_category_count": 9,
            "performance_successful_category_count": 5,
            "remaining_runtime_extension_count": 0,
            "all_effects_performance_successful": False,
            "real_aircraft_claim_permitted": False,
            "focused_test_count": 52,
        },
        "advanced-physics closure manifest metadata drifted",
        failures,
    )
    require(
        closure_manifest.get("schema_version")
        == "dronedream.advanced-physics-closure-manifest.v2"
        and closure_manifest.get("subject_commit")
        == advanced_closure["subject_commit"]
        and closure_manifest.get("evidence_class")
        == advanced_closure["evidence_class"]
        and closure_manifest.get("manifest_sha256")
        == "7193e21ff826560e9e9f4d30453dc122d55fbee054397ff4a52f89deca15cb9f"
        and canonical_json_sha256(closure_manifest, "manifest_sha256")
        == closure_manifest.get("manifest_sha256")
        and closure_manifest.get("remaining_runtime_extensions") == [],
        "advanced-physics closure manifest identity drifted",
        failures,
    )
    closure_categories = closure_manifest.get("coverage", [])
    expected_closure_categories = [
        ("steady_wind", True),
        ("obstacles", True),
        ("gust_and_turbulence", True),
        ("sensor_noise", False),
        ("payload_mass_and_inertia", True),
        ("actuator_first_order_delay", True),
        ("deterministic_seeded_gps_dropout", False),
        ("battery_initial_state_and_voltage_sag", False),
        ("actuator_hard_failure", False),
    ]
    require(
        [
            (
                item.get("category"),
                item.get("performance_success_for_all_retained_trials"),
            )
            for item in closure_categories
        ]
        == expected_closure_categories
        and all(bool(item.get("evidence_strength")) for item in closure_categories),
        "advanced-physics closure category matrix drifted",
        failures,
    )
    closure_summary = closure_manifest.get("summary", {})
    require(
        closure_summary
        == {
            "all_effects_performance_successful": False,
            "all_runtime_effect_categories_verified": True,
            "capability_category_count": 9,
            "categories_with_all_retained_performance_success": 5,
            "real_aircraft_claim_permitted": False,
            "source_manifest_count": 2,
            "source_receipt_count": 4,
            "verified_category_count": 9,
        },
        "advanced-physics closure summary drifted",
        failures,
    )
    closure_contract = closure_manifest.get("capability_contract", {})
    require(
        closure_contract.get("requires_runtime_extension") == []
        and closure_contract.get("physically_applied")
        == [
            "actuator_first_order_delay",
            "actuator_hard_failure",
            "battery_initial_state_and_voltage_sag",
            "deterministic_seeded_gps_dropout",
            "gust_and_turbulence",
            "obstacles",
            "payload_mass_and_inertia",
            "sensor_noise",
            "steady_wind",
        ],
        "advanced-physics closure capability contract drifted",
        failures,
    )
    source_evidence = closure_manifest.get("source_evidence", [])
    require(
        [item.get("role") for item in source_evidence]
        == [
            "constant_wind_and_obstacles",
            "gust_noise_payload_and_actuator_delay",
            "gps_dropout_and_battery",
            "hard_actuator_failure",
        ]
        and [
            item.get("receipt", {}).get("sha256") for item in source_evidence
        ]
        == [
            "8f7e1c953338ae87154b25822bf7c781921473cbcd76fd5874d79c178ef73dee",
            "99e257fb56d46d9293ba9365ccae604ddd697802370b877360541628ebd1354f",
            "2d6470fb085e638c52754f580d22a5d3d50d2f26000e584148557f3c505fdd8a",
            "5cc93ee5bfb75c53f95bdd925bb3121658d9ae93d6742d2b677d489112252cc6",
        ],
        "advanced-physics closure source bindings drifted",
        failures,
    )
    require(
        closure_receipt.get("schema_version")
        == "dronedream.advanced-physics-closure-receipt.v2"
        and closure_receipt.get("subject_commit")
        == advanced_closure["subject_commit"]
        and closure_receipt.get("receipt_sha256")
        == "6f195b2908aa8673eab3bfee56c5e6cd1254b3535c3029e652f237d8a08edc10"
        and canonical_json_sha256(closure_receipt, "receipt_sha256")
        == closure_receipt.get("receipt_sha256")
        and closure_receipt.get("network_calls") == 0
        and closure_receipt.get("openai_api_key_used") is False
        and closure_receipt.get("real_credentials_used") is False
        and closure_receipt.get("result")
        == {
            "all_effects_performance_successful": False,
            "real_aircraft_claim_permitted": False,
            "remaining_runtime_extensions": 0,
            "status": "complete_for_bundled_runtime_effect_contract",
            "verified_categories": 9,
        },
        "advanced-physics closure receipt drifted",
        failures,
    )
    closure_manifest_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "advanced_physics_closure_manifest"
    )
    closure_receipt_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "advanced_physics_closure_receipt"
    )
    closure_digest_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "advanced_physics_closure_digest"
    )
    closure_manifest_payload = run_git(
        repo,
        "show",
        f"{closure_manifest_entry['ref_commit']}:{closure_manifest_entry['path']}",
    )
    closure_receipt_payload = run_git(
        repo,
        "show",
        f"{closure_receipt_entry['ref_commit']}:{closure_receipt_entry['path']}",
    )
    closure_digest_payload = run_git(
        repo,
        "show",
        f"{closure_digest_entry['ref_commit']}:{closure_digest_entry['path']}",
    )
    require(
        closure_digest_payload
        == (
            f"{sha256(closure_manifest_payload)}  "
            "advanced-physics-closure-v2.manifest.json\n"
            f"{sha256(closure_receipt_payload)}  "
            "advanced-physics-closure-v2.receipt.json\n"
        ).encode("ascii"),
        "advanced-physics closure sidecar binding drifted",
        failures,
    )
    closure_test_result = closure_test_receipt.get("result", {})
    require(
        closure_test_receipt.get("schema_version")
        == "dronedream.advanced-physics-closure-test-receipt/v1"
        and closure_test_receipt.get("subject_commit")
        == advanced_closure["subject_commit"]
        and closure_test_receipt.get("exit_code") == 0
        and closure_test_result
        == {
            "tests": 52,
            "passed": 52,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "junit_time_seconds": 6.498,
        }
        and closure_test_receipt.get("environment", {}).get("network_calls") == 0
        and closure_test_receipt.get("environment", {}).get("px4_or_gazebo_runs")
        == 0
        and closure_test_receipt.get("artifacts", {})
        .get("focused-tests.xml", {})
        .get("sha256")
        == "2b95be8b9ce7ad3369ae7f8d0c2b8148acb691286a95269db9ae4fde28cda01a",
        "advanced-physics closure focused-test receipt drifted",
        failures,
    )
    closure_junit_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "advanced_physics_closure_focused_junit"
    )
    closure_junit_payload = run_git(
        repo,
        "show",
        f"{closure_junit_entry['ref_commit']}:{closure_junit_entry['path']}",
    )
    try:
        closure_junit_root = ET.fromstring(closure_junit_payload)
        closure_junit_suite = next(closure_junit_root.iter("testsuite"))
    except (ET.ParseError, StopIteration):
        failures.append("advanced-physics closure JUnit is unreadable")
    else:
        require(
            closure_junit_suite.attrib.get("tests") == "52"
            and closure_junit_suite.attrib.get("failures") == "0"
            and closure_junit_suite.attrib.get("errors") == "0"
            and closure_junit_suite.attrib.get("skipped") == "0",
            "advanced-physics closure JUnit result drifted",
            failures,
        )

    v10_bundle_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "technical_report_evidence_v10_bundle"
    )
    v10_manifest_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "technical_report_evidence_v10_manifest"
    )
    v10_digest_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "technical_report_evidence_v10_digest"
    )
    v10_receipt_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "technical_report_evidence_v10_test_receipt"
    )
    v10_bundle = software_json.get("technical_report_evidence_v10_bundle", {})
    v10_manifest = software_json.get("technical_report_evidence_v10_manifest", {})
    v10_receipt = software_json.get("technical_report_evidence_v10_test_receipt", {})
    require(
        evidence_v10
        == {
            "source_commit": "97492448c36bef240e468a0cd53c3ba198cb6aae",
            "freeze_commit": "a1f091f2edf1ae43233cd01e483bc3990c9aa279",
            "generated_at": "2026-07-28T23:54:28Z",
            "schema_version": "dronedream.technical-report-evidence.v10",
            "source_count": 39,
            "csv_export_count": 3,
            "compatibility_test_count": 70,
            "tamper_test_count": 7,
            "online_routing_current_for_evidence_2_9": False,
            "release_ready": False,
            "claim_class": (
                "latest_exact_byte_provenance_navigation_ledger_without_"
                "release_readiness"
            ),
        },
        "Evidence v10 metadata drifted",
        failures,
    )
    require(
        v10_bundle.get("schema_version")
        == "dronedream.technical-report-evidence.v10"
        and v10_bundle.get("source_commit") == evidence_v10["source_commit"]
        and v10_bundle.get("generated_at") == evidence_v10["generated_at"]
        and v10_bundle.get("bundle_sha256") == v10_bundle_entry["canonical_sha256"]
        and canonical_json_sha256(v10_bundle, "bundle_sha256")
        == v10_bundle_entry["canonical_sha256"],
        "Evidence v10 bundle identity or canonical digest mismatch",
        failures,
    )
    require(
        len(v10_bundle.get("sources", {})) == 39
        and v10_bundle.get("base_evidence", {}).get("schema_version")
        == "dronedream.technical-report-evidence.v9"
        and v10_bundle.get("base_evidence", {}).get("bundle_sha256")
        == "d33c308ce3b47138572c86bf7f45aa8e4a37901a0248a5d5e0d3cd71ce2bfa8a",
        "Evidence v10 source inventory or v9 base binding mismatch",
        failures,
    )
    v10_routing = v10_bundle.get("routing", {})
    require(
        v10_routing.get("artifact_contract", {}).get("evidence_schema_version")
        == "2.8"
        and v10_routing.get("artifact_contract", {}).get("prompt_template_version")
        == "1.7"
        and v10_routing.get("current_contract", {}).get("evidence_schema_version")
        == "2.9"
        and v10_routing.get("contract_current") is False
        and v10_routing.get("qualification_scope")
        == "archived_evidence_2_8_prompt_1_7"
        and v10_routing.get("case_count") == 24
        and v10_routing.get("passed_count") == 23
        and v10_routing.get("qualified") is True
        and v10_routing.get("provider_calls") == 24
        and len(v10_routing.get("failed_cases", [])) == 1
        and v10_routing.get("failed_cases", [{}])[0].get("case_id")
        == "tight_budget_expensive_matrix",
        "Evidence v10 retained online-routing boundary drifted",
        failures,
    )
    v10_budget = v10_bundle.get("harness_multi_tool_budget", {})
    require(
        v10_budget.get("contracts", {}).get("evidence_schema_version") == "2.9"
        and v10_budget.get("summary", {}).get("block_count") == 3
        and v10_budget.get("summary", {}).get("arm_run_count") == 6
        and v10_budget.get("summary", {}).get("configured_budget_parity_count") == 3
        and v10_budget.get("summary", {}).get(
            "scripted_accounted_provider_call_count"
        )
        == 12
        and v10_budget.get("runtime", {}).get("network_calls") == 0
        and v10_budget.get("runtime", {}).get("real_provider_calls") == 0
        and v10_budget.get("runtime", {}).get("real_credentials_used") is False
        and v10_budget.get("runtime", {}).get("simulator_backend") == "mock",
        "Evidence v10 offline Evidence 2.9 budget boundary drifted",
        failures,
    )
    v10_physics = v10_bundle.get("advanced_physics", {})
    v10_physics_summary = v10_physics.get("summary", {})
    require(
        v10_physics.get("subject_commit") == advanced_closure["subject_commit"]
        and v10_physics_summary.get("capability_category_count") == 9
        and v10_physics_summary.get("verified_category_count") == 9
        and v10_physics_summary.get(
            "categories_with_all_retained_performance_success"
        )
        == 5
        and v10_physics_summary.get("all_effects_performance_successful") is False
        and v10_physics_summary.get("real_aircraft_claim_permitted") is False
        and len(v10_physics.get("coverage", [])) == 9
        and sum(
            bool(row.get("all_retained_trials_passed"))
            for row in v10_physics.get("coverage", [])
        )
        == 5,
        "Evidence v10 advanced-physics coverage/qualification split drifted",
        failures,
    )
    v10_release = v10_bundle.get("release_readiness", {})
    require(
        v10_release.get("release_ready") is False
        and v10_release.get("online_routing_current_for_evidence_2_9") is False
        and v10_release.get("online_provider_refresh_requires_separate_user_approval")
        is True
        and v10_release.get("current_source_full_regression_receipt_included")
        is False
        and v10_release.get("current_source_windows_rust_gate_included") is False
        and v10_release.get("report_pdf_gate_included") is False,
        "Evidence v10 release-readiness boundary drifted",
        failures,
    )
    require(
        v10_manifest.get("schema_version")
        == "dronedream.technical-report-evidence-manifest.v2"
        and v10_manifest.get("source_commit") == evidence_v10["source_commit"]
        and v10_manifest.get("generated_at") == evidence_v10["generated_at"]
        and len(v10_manifest.get("sources", {})) == 39
        and len(v10_manifest.get("csv_exports", {})) == 3
        and v10_manifest.get("bundle", {}).get("file_sha256")
        == v10_bundle_entry["file_sha256"]
        and v10_manifest.get("bundle", {}).get("bundle_sha256")
        == v10_bundle_entry["canonical_sha256"]
        and v10_manifest.get("release_readiness") == v10_release,
        "Evidence v10 manifest binding mismatch",
        failures,
    )
    v10_lineage = v10_bundle.get("source_lineage", {})
    require(
        v10_lineage.get("evidence_v9_source_commit") == software["subject_commit"]
        and v10_lineage.get("evidence_v9_freeze_commit")
        == software["provenance_commit"]
        and v10_lineage.get("online_routing_source_commit")
        == online_routing["implementation_commit"]
        and v10_lineage.get("online_routing_freeze_commit")
        == online_routing["evidence_head"]
        and v10_lineage.get("multi_tool_budget_source_commit")
        == multi_tool_budget["source_commit"]
        and v10_lineage.get("multi_tool_budget_freeze_commit")
        == multi_tool_budget["evidence_head"]
        and v10_lineage.get("advanced_physics_subject_commit")
        == advanced_closure["subject_commit"]
        and v10_lineage.get("advanced_physics_freeze_commit")
        == advanced_closure["evidence_head"],
        "Evidence v10 source-lineage binding mismatch",
        failures,
    )
    require(
        v10_receipt.get("schema_version") == "dronedream.test-run-receipt.v2"
        and v10_receipt.get("source_commit") == evidence_v10["source_commit"]
        and v10_receipt.get("receipt_sha256")
        == v10_receipt_entry["internal_receipt_sha256"]
        and canonical_json_sha256(v10_receipt, "receipt_sha256")
        == v10_receipt_entry["internal_receipt_sha256"]
        and v10_receipt.get("full_suite", {}).get("result", {}).get("passed") == 70
        and v10_receipt.get("full_suite", {}).get("result", {}).get("failed") == 0
        and v10_receipt.get("focused_checks", [{}])[0]
        .get("result", {})
        .get("passed")
        == 7
        and v10_receipt.get("focused_checks", [{}])[0]
        .get("result", {})
        .get("failed")
        == 0,
        "Evidence v10 test receipt identity or counts drifted",
        failures,
    )
    v10_digest_payload = run_git(
        repo, "show", f"{v10_digest_entry['ref_commit']}:{v10_digest_entry['path']}"
    ).decode("ascii")
    require(
        v10_bundle_entry["file_sha256"] in v10_digest_payload
        and v10_manifest_entry["file_sha256"] in v10_digest_payload
        and len([line for line in v10_digest_payload.splitlines() if line.strip()]) == 5,
        "Evidence v10 digest sidecar inventory drifted",
        failures,
    )
    for artifact_id, expected_tests in (
        ("technical_report_evidence_v10_compatibility_junit", "70"),
        ("technical_report_evidence_v10_focused_junit", "7"),
    ):
        junit_entry = next(
            item for item in software["artifacts"] if item["id"] == artifact_id
        )
        junit_payload = run_git(
            repo, "show", f"{junit_entry['ref_commit']}:{junit_entry['path']}"
        )
        try:
            junit_root = ET.fromstring(junit_payload)
            junit_suite = next(junit_root.iter("testsuite"))
        except (ET.ParseError, StopIteration):
            failures.append(f"Evidence v10 JUnit is unreadable: {artifact_id}")
        else:
            require(
                junit_suite.attrib.get("tests") == expected_tests
                and junit_suite.attrib.get("failures") == "0"
                and junit_suite.attrib.get("errors") == "0",
                f"Evidence v10 JUnit result drifted: {artifact_id}",
                failures,
            )

    bundle_entry = next(
        item for item in software["artifacts"] if item["id"] == "technical_report_evidence_bundle"
    )
    bundle = software_json.get("technical_report_evidence_bundle", {})
    require(
        bundle.get("bundle_sha256") == bundle_entry["canonical_sha256"],
        "canonical bundle SHA-256 mismatch",
        failures,
    )
    require(
        bundle.get("source_commit") == software["subject_commit"],
        "bundle source_commit mismatch",
        failures,
    )
    require(
        bundle.get("schema_version") == "dronedream.technical-report-evidence.v9",
        "software evidence bundle is not v9",
        failures,
    )
    require(
        canonical_json_sha256(bundle, "bundle_sha256")
        == bundle_entry["canonical_sha256"],
        "software evidence bundle canonical bytes mismatch",
        failures,
    )

    software_manifest = software_json.get("technical_report_evidence_manifest", {})
    require(
        software_manifest.get("source_commit") == software["subject_commit"],
        "software evidence manifest source_commit mismatch",
        failures,
    )
    require(
        software_manifest.get("bundle", {}).get("bundle_sha256")
        == bundle_entry["canonical_sha256"],
        "software manifest canonical bundle SHA-256 mismatch",
        failures,
    )
    require(
        software_manifest.get("bundle", {}).get("file_sha256")
        == bundle_entry["file_sha256"],
        "software manifest bundle file SHA-256 mismatch",
        failures,
    )
    require(
        software_manifest.get("generated_at") == "2026-07-28T15:44:30Z"
        and bundle.get("generated_at") == software_manifest.get("generated_at"),
        "software v9 generation timestamp mismatch",
        failures,
    )
    manifest_sources = software_manifest.get("sources", {})
    require(
        len(manifest_sources) == 25,
        "software v9 source inventory must contain 25 objects",
        failures,
    )
    source_bindings = {
        "harness_ablations": "harness_contract_ablation_raw",
        "harness_outcome_campaign": "harness_fallback_outcome_campaign_raw",
        "harness_component_outcome_ablation": (
            "harness_component_outcome_ablation_raw"
        ),
        "routing_corpus": "routing_development_corpus_raw",
        "routing_predictions": "routing_prompt_1_6_archived_raw",
    }
    for manifest_id, reference_id in source_bindings.items():
        declared = manifest_sources.get(manifest_id, {})
        reference = reference_by_id.get(reference_id, {})
        require(
            declared.get("path") == reference.get("path")
            and declared.get("sha256") == reference.get("file_sha256"),
            f"software v9 source binding mismatch: {manifest_id}",
            failures,
        )

    backend_entry = next(
        item for item in software["artifacts"] if item["id"] == "backend_1204_test_receipt"
    )
    backend_source = manifest_sources.get("backend_test_receipt", {})
    require(
        backend_source.get("path") == backend_entry["path"]
        and backend_source.get("sha256") == backend_entry["file_sha256"],
        "software v9 backend receipt source binding mismatch",
        failures,
    )
    backend_receipt = software_json.get("backend_1204_test_receipt", {})
    require(
        backend_receipt.get("source_commit") == software["subject_commit"],
        "backend receipt source_commit mismatch",
        failures,
    )
    require(
        backend_receipt.get("receipt_sha256")
        == backend_entry["internal_receipt_sha256"],
        "backend internal receipt SHA-256 mismatch",
        failures,
    )
    full_suite = backend_receipt.get("full_suite", {})
    require(
        full_suite.get("result", {}).get("passed") == 1204
        and full_suite.get("result", {}).get("failed") == 0,
        "backend full-suite count mismatch",
        failures,
    )
    require(
        full_suite.get("duration_seconds") == 864.488,
        "backend full-suite receipt wall duration mismatch",
        failures,
    )
    require(
        full_suite.get("tested_state", {}).get("exact_final_commit_run") is True
        and full_suite.get("tested_state", {}).get("base_commit")
        == software["subject_commit"],
        "backend receipt must bind an exact final-commit run",
        failures,
    )
    require(
        full_suite.get("log", {}).get("sha256")
        == backend_entry["full_log_sha256"],
        "backend full-suite log SHA-256 mismatch",
        failures,
    )
    focused = backend_receipt.get("focused_checks", [])
    require(
        len(focused) == 1
        and focused[0].get("result", {}).get("passed") == 28
        and focused[0].get("result", {}).get("failed") == 0,
        "backend focused supplement mismatch",
        failures,
    )
    require(
        len(focused) == 1 and focused[0].get("duration_seconds") == 8.451,
        "backend focused receipt wall duration mismatch",
        failures,
    )
    require(
        len(focused) == 1
        and focused[0].get("log", {}).get("sha256")
        == backend_entry["focused_log_sha256"],
        "backend focused log SHA-256 mismatch",
        failures,
    )
    require(
        backend_receipt.get("validation_bridge", {}).get("full_suite_rerun_performed")
        is True
        and backend_receipt.get("validation_bridge", {}).get(
            "focused_rerun_performed"
        )
        is True
        and backend_receipt.get("validation_bridge", {}).get(
            "focused_rerun_required"
        )
        is False,
        "backend exact-run validation relationship mismatch",
        failures,
    )

    full_log_ref = reference_by_id["backend_1204_full_log"]
    focused_log_ref = reference_by_id["backend_28_focused_log"]
    full_log = run_git(
        repo,
        "show",
        f"{full_log_ref['ref_commit']}:{full_log_ref['path']}",
    ).decode("utf-16")
    focused_log = run_git(
        repo,
        "show",
        f"{focused_log_ref['ref_commit']}:{focused_log_ref['path']}",
    ).decode("utf-16")
    require(
        "1204 passed in 854.71s" in full_log,
        "backend pytest-result duration/count summary drifted",
        failures,
    )
    require(
        "28 passed in 6.98s" in focused_log,
        "backend focused pytest-result duration/count summary drifted",
        failures,
    )

    cross_artifact_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "cross_job_memory_contract_artifact"
    )
    cross_manifest_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "cross_job_memory_contract_manifest"
    )
    cross_artifact = software_json.get("cross_job_memory_contract_artifact", {})
    cross_manifest = software_json.get("cross_job_memory_contract_manifest", {})
    require(
        cross_artifact.get("artifact_sha256")
        == cross_artifact_entry["canonical_sha256"]
        == canonical_json_sha256(cross_artifact, "artifact_sha256"),
        "cross-Job memory artifact canonical SHA-256 mismatch",
        failures,
    )
    require(
        cross_manifest.get("manifest_sha256")
        == cross_manifest_entry["canonical_sha256"]
        == canonical_json_sha256(cross_manifest, "manifest_sha256"),
        "cross-Job memory manifest canonical SHA-256 mismatch",
        failures,
    )
    require(
        cross_artifact.get("manifest_sha256") == cross_manifest_entry["canonical_sha256"],
        "cross-Job memory artifact-to-manifest binding mismatch",
        failures,
    )
    cross_source_bindings = {
        "harness_cross_job_memory": cross_artifact_entry,
        "harness_cross_job_memory_manifest": cross_manifest_entry,
    }
    for source_id, artifact_entry in cross_source_bindings.items():
        declared = manifest_sources.get(source_id, {})
        require(
            declared.get("path") == artifact_entry["path"]
            and declared.get("sha256") == artifact_entry["file_sha256"],
            f"cross-Job v9 source binding mismatch: {source_id}",
            failures,
        )
    require(
        bundle.get("harness_cross_job_memory", {}).get("artifact_sha256")
        == cross_artifact_entry["canonical_sha256"]
        and bundle.get("harness_cross_job_memory", {}).get("manifest_sha256")
        == cross_manifest_entry["canonical_sha256"],
        "Evidence v9 cross-Job summary binding mismatch",
        failures,
    )
    summary = cross_artifact.get("summary", {})
    require(
        summary
        == {
            "case_count": 10,
            "failed_count": 0,
            "network_calls": 0,
            "passed_count": 10,
            "provider_calls": 0,
            "provider_identifier_leak_count": 0,
            "retrieval_negative_count": 8,
            "retrieval_positive_count": 2,
            "simulator_runs": 0,
        },
        "cross-Job memory summary drifted",
        failures,
    )
    expected_cases = [
        "same_user_exact_task_exact_scenario",
        "same_user_exact_task_shifted_scenario",
        "cross_user_isolated",
        "anonymous_user_isolated",
        "task_family_mismatch",
        "parameter_catalog_drift",
        "revoked_excluded",
        "expired_excluded",
        "contract_version_drift_excluded",
        "source_receipt_drift_excluded",
    ]
    case_rows = cross_artifact.get("case_rows", [])
    require(
        [row.get("case_id") for row in case_rows] == expected_cases
        and all(row.get("passed") is True for row in case_rows)
        and all(row.get("provider_identifiers_absent") is True for row in case_rows),
        "cross-Job memory case inventory or leak boundary drifted",
        failures,
    )
    contracts = cross_manifest.get("contracts", {})
    require(
        contracts.get("evidence_schema_version")
        == cross_job["evidence_schema_version"]
        == "2.8"
        and contracts.get("prompt_template_version")
        == cross_job["prompt_template_version"]
        == "1.7"
        and contracts.get("trace_schema_version")
        == cross_job["trace_schema_version"]
        == "1.4"
        and contracts.get("retention_days") == cross_job["retention_days"] == 90,
        "cross-Job memory contract versions or retention drifted",
        failures,
    )
    require(
        cross_manifest.get("runtime")
        == {
            "database": "sqlite_in_memory",
            "network_calls": 0,
            "provider_calls": 0,
            "real_credentials_used": False,
            "simulator_runs": 0,
        },
        "cross-Job memory runtime boundary drifted",
        failures,
    )
    require(
        cross_job["claim_class"] == "observational_not_causal"
        and "no claim of optimizer-quality benefit"
        in cross_artifact.get("claim_boundary", ""),
        "cross-Job memory claim boundary drifted",
        failures,
    )
    routing = bundle.get("routing", {})
    require(
        routing.get("contract_current") is False
        and routing.get("qualification_scope")
        == "archived_evidence_2_7_prompt_1_6"
        and routing.get("current_evidence_schema_version") == "2.8"
        and routing.get("current_prompt_template_version") == "1.7",
        "archived routing/current contract separation drifted",
        failures,
    )

    online_artifact_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "current_online_routing_artifact"
    )
    online_manifest_entry = next(
        item
        for item in software["artifacts"]
        if item["id"] == "current_online_routing_manifest"
    )
    online_artifact = software_json.get("current_online_routing_artifact", {})
    online_manifest = software_json.get("current_online_routing_manifest", {})
    require(
        online_manifest.get("manifest_sha256")
        == online_manifest_entry["canonical_sha256"]
        == canonical_json_sha256(online_manifest, "manifest_sha256"),
        "online routing manifest canonical SHA-256 mismatch",
        failures,
    )
    declared_online_artifact = online_manifest.get("artifact", {})
    require(
        declared_online_artifact.get("path") == online_artifact_entry["path"]
        and declared_online_artifact.get("sha256")
        == online_artifact_entry["file_sha256"]
        and declared_online_artifact.get("bytes") == 12818,
        "online routing artifact binding mismatch",
        failures,
    )
    require(
        online_artifact.get("evidence_schema_version")
        == online_routing["evidence_schema_version"]
        == declared_online_artifact.get("evidence_schema_version")
        == "2.8"
        and online_artifact.get("prompt_template_version")
        == online_routing["prompt_template_version"]
        == declared_online_artifact.get("prompt_template_version")
        == "1.7"
        and online_artifact.get("tool_registry_version")
        == online_routing["tool_registry_version"]
        == declared_online_artifact.get("tool_registry_version")
        == "2.1"
        and online_artifact.get("model_snapshot")
        == online_routing["model_snapshot"]
        == declared_online_artifact.get("model_snapshot")
        == "gpt-4.1-2025-04-14",
        "online routing contract or model snapshot drifted",
        failures,
    )
    expected_generation_config = {
        "response_format": "json_schema",
        "seed": 20260728,
        "temperature": 0.0,
        "top_p": 1.0,
    }
    require(
        online_artifact.get("generation_config") == expected_generation_config
        and declared_online_artifact.get("generation_config")
        == expected_generation_config,
        "online routing generation controls drifted",
        failures,
    )
    campaign = online_manifest.get("campaign", {})
    require(
        campaign.get("source_commit") == online_routing["implementation_commit"]
        and campaign.get("source_branch") == software["branch"]
        and campaign.get("provider_calls") == online_routing["provider_calls"] == 24
        and campaign.get("network_calls") == 24
        and campaign.get("duration_seconds") == 77.8
        and campaign.get("exit_code") == 0
        and campaign.get("source_tree_clean") is True
        and campaign.get("output_replaced") is False,
        "online routing campaign execution boundary drifted",
        failures,
    )
    credential_boundary = online_manifest.get("credential_handling", {})
    require(
        credential_boundary.get("api_key_persisted") is False
        and credential_boundary.get("api_key_printed") is False
        and credential_boundary.get("provider_request_ids_persisted") is False
        and credential_boundary.get("secret_values_in_artifact") is False,
        "online routing credential boundary drifted",
        failures,
    )
    online_result = online_manifest.get("result", {})
    expected_online_failure = {
        "acceptable_tools": ["multi_fidelity_mobo", "optimizer_portfolio"],
        "case_id": "tight_budget_expensive_matrix",
        "category": "tight_budget",
        "selected_tool": "turbo",
    }
    require(
        online_result.get("case_count") == 24
        and online_result.get("passed_count") == 23
        and online_result.get("pass_rate") == 23 / 24
        and online_result.get("qualified") is True
        and online_result.get("failed_requirements") == []
        and online_result.get("failed_cases") == [expected_online_failure]
        and online_result.get("best_constant_pass_rate") == 14 / 24
        and online_result.get("absolute_lift_over_best_constant") == 9 / 24
        and online_result.get("minimum_category_pass_rate") == 2 / 3,
        "online routing qualification summary drifted",
        failures,
    )
    predictions = online_artifact.get("predictions", {})
    require(
        len(predictions) == 24
        and predictions.get("tight_budget_expensive_matrix", {}).get(
            "selected_tool"
        )
        == "turbo",
        "online routing prediction inventory or failed case drifted",
        failures,
    )
    corpus_ref = reference_by_id["routing_development_corpus_raw"]
    corpus_rows = [
        json.loads(line)
        for line in run_git(
            repo,
            "show",
            f"{corpus_ref['ref_commit']}:{corpus_ref['path']}",
        )
        .decode("utf-8")
        .splitlines()
        if line.strip()
    ]
    failed_case_ids = [
        str(row["case_id"])
        for row in corpus_rows
        if predictions.get(str(row["case_id"]), {}).get("selected_tool")
        not in row["acceptable_tools"]
    ]
    require(
        len(corpus_rows) == 24
        and set(predictions) == {str(row["case_id"]) for row in corpus_rows}
        and failed_case_ids == ["tight_budget_expensive_matrix"],
        "online routing independent corpus regrade drifted",
        failures,
    )
    qualification_ref = reference_by_id["online_routing_qualification_contract"]
    qualification_source = run_git(
        repo,
        "show",
        f"{qualification_ref['ref_commit']}:{qualification_ref['path']}",
    ).decode("utf-8")
    require(
        "HARNESS_ROUTING_MIN_PASS_RATE = 0.75" in qualification_source
        and "HARNESS_ROUTING_MIN_CATEGORY_PASS_RATE = 2 / 3"
        in qualification_source
        and "HARNESS_ROUTING_MIN_LIFT_OVER_BEST_CONSTANT = 0.15"
        in qualification_source,
        "online routing qualification thresholds drifted",
        failures,
    )
    require(
        online_routing["claim_class"]
        == (
            "retained_online_development_routing_qualification_not_current_"
            "for_evidence_2_9"
        )
        and online_routing.get("contract_current") is False
        and online_routing.get("qualification_scope")
        == "archived_evidence_2_8_prompt_1_7"
        and "does not establish causal optimizer-outcome benefit"
        in online_manifest.get("claim_boundary", ""),
        "online routing claim boundary drifted",
        failures,
    )

    multi_entries = {item["id"]: item for item in software["artifacts"]}
    multi_artifact_entry = multi_entries["multi_tool_budget_artifact"]
    multi_manifest_entry = multi_entries["multi_tool_budget_manifest"]
    multi_csv_entry = multi_entries["multi_tool_budget_csv"]
    multi_receipt_entry = multi_entries["multi_tool_budget_generation_receipt"]
    multi_artifact = software_json.get("multi_tool_budget_artifact", {})
    multi_manifest = software_json.get("multi_tool_budget_manifest", {})
    multi_receipt = software_json.get("multi_tool_budget_generation_receipt", {})
    require(
        multi_artifact.get("artifact_sha256")
        == multi_artifact_entry["canonical_sha256"]
        == canonical_json_sha256(multi_artifact, "artifact_sha256"),
        "Evidence 2.9 artifact canonical SHA-256 mismatch",
        failures,
    )
    require(
        multi_manifest.get("manifest_sha256")
        == multi_manifest_entry["canonical_sha256"]
        == canonical_json_sha256(multi_manifest, "manifest_sha256"),
        "Evidence 2.9 manifest canonical SHA-256 mismatch",
        failures,
    )
    require(
        multi_artifact.get("source_commit")
        == multi_manifest.get("source_commit")
        == multi_tool_budget["source_commit"]
        and multi_artifact.get("generated_at")
        == multi_manifest.get("generated_at")
        == multi_tool_budget["generated_at"],
        "Evidence 2.9 source or generation binding drifted",
        failures,
    )
    multi_summary = multi_artifact.get("summary", {})
    require(
        multi_artifact.get("contracts", {}).get("evidence_schema_version")
        == multi_manifest.get("contracts", {}).get("evidence_schema_version")
        == multi_tool_budget["evidence_schema_version"]
        == "2.9"
        and multi_summary.get("block_count")
        == multi_summary.get("configured_budget_parity_count")
        == multi_tool_budget["seed_blocks"]
        == 3
        and multi_summary.get("arm_run_count") == multi_tool_budget["arm_runs"] == 6
        and multi_summary.get("scripted_accounted_provider_call_count")
        == multi_summary.get("scripted_decision_call_count")
        == multi_tool_budget["accounted_calls"]
        == 12
        and multi_summary.get("scripted_verified_generation_count") == 6
        and multi_summary.get("scripted_multi_tool_generation_count") == 3,
        "Evidence 2.9 equal-budget or accounting summary drifted",
        failures,
    )
    require(
        multi_artifact.get("real_provider_calls")
        == multi_artifact.get("network_calls")
        == multi_tool_budget["provider_calls"]
        == multi_tool_budget["network_calls"]
        == 0
        and multi_artifact.get("real_credentials_used") is False
        and multi_artifact.get("physical_fidelity") is False
        and multi_manifest.get("runtime", {}).get("simulator_backend")
        == multi_tool_budget["simulator_backend"]
        == "mock",
        "Evidence 2.9 offline mock boundary drifted",
        failures,
    )
    failed_attempt = multi_receipt.get("failed_attempt", {})
    successful_attempt = multi_receipt.get("successful_attempt", {})
    require(
        failed_attempt.get("exit_code") == 1
        and failed_attempt.get("error_type") == "ModuleNotFoundError"
        and failed_attempt.get("jobs_started") == 0
        and failed_attempt.get("provider_calls") == 0
        and failed_attempt.get("network_calls") == 0
        and failed_attempt.get("simulator_calls") == 0
        and successful_attempt.get("source_commit")
        == multi_tool_budget["source_commit"]
        and successful_attempt.get("artifact_file_sha256")
        == multi_artifact_entry["file_sha256"]
        and successful_attempt.get("manifest_file_sha256")
        == multi_manifest_entry["file_sha256"]
        and successful_attempt.get("csv_file_sha256")
        == multi_csv_entry["file_sha256"]
        and multi_receipt_entry["file_sha256"]
        == sha256(
            run_git(
                repo,
                "show",
                f"{multi_receipt_entry['ref_commit']}:{multi_receipt_entry['path']}",
            )
        ),
        "Evidence 2.9 retained failure or successful receipt binding drifted",
        failures,
    )
    require(
        multi_tool_budget["claim_class"]
        == "offline_scripted_mock_equal_budget_plan_history_and_accounting_contract"
        and "do not establish LLM quality"
        in multi_manifest.get("claim_boundary", ""),
        "Evidence 2.9 claim boundary drifted",
        failures,
    )

    website_artifacts = {item["id"]: item for item in website["artifacts"]}
    website_artifact = website_artifacts["website_release_truth_validation_receipt"]
    try:
        website_payload, website_receipt = git_json(
            repo, website_artifact["ref_commit"], website_artifact["path"]
        )
    except (subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError):
        failures.append("unreadable website validation receipt")
        website_payload, website_receipt = b"", {}
    website_actual = sha256(website_payload)
    require(
        website_actual == website_artifact["file_sha256"],
        f"website receipt SHA-256 mismatch: {website_actual}",
        failures,
    )
    require(
        website_receipt.get("subject", {}).get("sourceCommit")
        == website_artifact["subject_commit"],
        "website release-truth receipt subject mismatch",
        failures,
    )
    require(
        len(website_payload) == website_artifact["file_bytes"],
        "website receipt byte count mismatch",
        failures,
    )
    checks = website_receipt.get("automatedValidation", {})
    require(
        checks.get("focusedPublicSiteTests", {}).get("passed") == 13
        and checks.get("focusedPublicSiteTests", {}).get("failed") == 0,
        "website focused PublicSite test count mismatch",
        failures,
    )
    require(
        checks.get("frontendTests", {}).get("testFiles") == 50
        and checks.get("frontendTests", {}).get("passed") == 325
        and checks.get("frontendTests", {}).get("failed") == 0,
        "website frontend test count mismatch",
        failures,
    )
    require(
        all(
            checks.get(name, {}).get("result") == "pass"
            for name in ("typecheck", "lint", "applicationBuild")
        ),
        "website typecheck/lint/build receipt mismatch",
        failures,
    )
    require(
        checks.get("deploymentContract", {}).get("tests") == 11
        and checks.get("deploymentContract", {}).get("subtests") == 22
        and checks.get("deploymentContract", {}).get("passed") == 11,
        "website deployment test count mismatch",
        failures,
    )
    browser_matrix = website_receipt.get("publicSiteBrowserValidation", {}).get(
        "matrix", {}
    )
    require(
        browser_matrix.get("checks") == 100
        and browser_matrix.get("passed") == 100
        and browser_matrix.get("failed") == 0,
        "website browser-matrix receipt mismatch",
        failures,
    )
    artifact_summary = website_receipt.get("sharedWebsiteArtifact", {})
    require(
        artifact_summary.get("result") == "pass"
        and artifact_summary.get("sourceCommit") == website_artifact["subject_commit"]
        and artifact_summary.get("buildManifestSha256")
        == website_artifact["shared_build_manifest_sha256"]
        and artifact_summary.get("sha256SumsSha256")
        == website_artifact["shared_sha256sums_sha256"]
        and artifact_summary.get("verifiedSha256SumsEntries") == 118
        and artifact_summary.get("artifactFilesIncludingSha256Sums") == 119,
        "website shared-artifact receipt mismatch",
        failures,
    )
    require(
        website_receipt.get("environment", {}).get("deploymentPerformed") is False
        and len(website_receipt.get("remainingExternalGates", [])) > 0
        and "unsigned preview candidate"
        in website_receipt.get("currentReleaseTruth", {}).get("websiteClaim", ""),
        "website external-gate boundary mismatch",
        failures,
    )
    verified_artifacts.append({"id": website_artifact["id"], "sha256": website_actual})

    typography_artifact = website_artifacts["website_typography_validation_receipt"]
    try:
        typography_payload, typography_receipt = git_json(
            repo, typography_artifact["ref_commit"], typography_artifact["path"]
        )
    except (subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError):
        failures.append("unreadable website typography validation receipt")
        typography_payload, typography_receipt = b"", {}
    typography_actual = sha256(typography_payload)
    require(
        typography_actual == typography_artifact["file_sha256"],
        f"website typography receipt SHA-256 mismatch: {typography_actual}",
        failures,
    )
    require(
        len(typography_payload) == typography_artifact["file_bytes"],
        "website typography receipt byte count mismatch",
        failures,
    )
    typography_subject = typography_receipt.get("subject", {})
    require(
        typography_subject.get("sourceCommit") == website["subject_commit"]
        and typography_subject.get("sourceParent") == website_artifact["ref_commit"]
        and typography_subject.get("previousWebsiteReceiptSha256")
        == typography_artifact["previous_receipt_sha256"],
        "website typography subject/ancestor binding mismatch",
        failures,
    )
    typography_checks = typography_receipt.get("automatedValidation", {})
    require(
        typography_checks.get("focusedPublicSiteTests", {}).get("passed") == 13
        and typography_checks.get("focusedPublicSiteTests", {}).get("failed") == 0
        and typography_checks.get("frontendTests", {}).get("testFiles") == 50
        and typography_checks.get("frontendTests", {}).get("passed") == 325
        and typography_checks.get("frontendTests", {}).get("failed") == 0,
        "website typography focused/frontend test count mismatch",
        failures,
    )
    require(
        all(
            typography_checks.get(name, {}).get("result") == "pass"
            for name in ("typecheck", "lint", "applicationBuild")
        )
        and typography_checks.get("deploymentContract", {}).get("passed") == 11
        and typography_checks.get("deploymentContract", {}).get("subtests") == 22
        and typography_checks.get("performance", {}).get("passed") == 5
        and typography_checks.get("performance", {}).get("failed") == 0,
        "website typography build/deployment/performance receipt mismatch",
        failures,
    )
    desktop = typography_receipt.get("desktopTypography", {})
    english = desktop.get("downloadBody", {}).get("english", {})
    chinese = desktop.get("downloadBody", {}).get("simplifiedChinese", {})
    require(
        desktop.get("result") == "pass"
        and desktop.get("typographyFailures") == 0
        and english.get("lines") == 2
        and english.get("finalLineFill") == 0.895
        and chinese.get("lines") == 2
        and chinese.get("finalLineFill") == 0.835,
        "website desktop typography receipt mismatch",
        failures,
    )
    require(
        typography_receipt.get("mobileLayout", {}).get("result") == "pass"
        and typography_receipt.get("mobileLayout", {}).get("layoutViolations") == 0,
        "website mobile layout receipt mismatch",
        failures,
    )
    typography_artifact_summary = typography_receipt.get("sharedWebsiteArtifact", {})
    require(
        typography_artifact_summary.get("result") == "pass"
        and typography_artifact_summary.get("sourceCommit") == website["subject_commit"]
        and typography_artifact_summary.get("buildManifestSha256")
        == typography_artifact["shared_build_manifest_sha256"]
        and typography_artifact_summary.get("sha256SumsSha256")
        == typography_artifact["shared_sha256sums_sha256"]
        and typography_artifact_summary.get("verifiedSha256SumsEntries") == 118,
        "website typography shared-artifact receipt mismatch",
        failures,
    )
    require(
        typography_receipt.get("environment", {}).get("deploymentPerformed") is False
        and len(typography_receipt.get("remainingExternalGates", [])) > 0
        and "No GitHub Pages deployment was triggered."
        in typography_receipt.get("actionsNotPerformed", []),
        "website typography external-gate boundary mismatch",
        failures,
    )
    verified_artifacts.append(
        {"id": typography_artifact["id"], "sha256": typography_actual}
    )

    require(
        manifest.get("merge_prerequisites") == [],
        "stale report merge prerequisite remains",
        failures,
    )

    result = {
        "schema_version": manifest["schema_version"],
        "status": "passed" if not failures else "failed",
        "verified_commits": commit_fields,
        "verified_artifacts": verified_artifacts,
        "verified_sources": verified_sources,
        "failures": failures,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
