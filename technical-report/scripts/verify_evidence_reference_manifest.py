from __future__ import annotations

import hashlib
import json
import subprocess
import sys
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
    cross_job = software["cross_job_memory"]
    online_routing = software["online_routing"]
    multi_tool_budget = software["multi_tool_budget"]
    commit_fields = [
        software["subject_commit"],
        software["provenance_commit"],
        software["branch_head"],
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
    require(
        advanced["evidence_head"] == software["branch_head"],
        "advanced-physics evidence head must bind the latest software head",
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
        == "current_contract_development_routing_qualification"
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
