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
    commit_fields = [
        software["subject_commit"],
        software["provenance_commit"],
        software["branch_head"],
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
        website["subject_commit"],
        website["attestation_commit"],
        failures,
    )

    software_json: dict[str, dict[str, Any]] = {}
    for artifact in software["artifacts"]:
        try:
            payload, parsed = git_json(repo, artifact["ref_commit"], artifact["path"])
        except (subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError):
            failures.append(f"unreadable software artifact: {artifact['id']}")
            continue
        actual = sha256(payload)
        require(
            actual == artifact["file_sha256"],
            f"SHA-256 mismatch for {artifact['id']}: {actual}",
            failures,
        )
        software_json[artifact["id"]] = parsed
        verified_artifacts.append({"id": artifact["id"], "sha256": actual})

    source_reference_ids: set[str] = set()
    for source in software.get("source_references", []):
        source_id = str(source["id"])
        require(
            source_id not in source_reference_ids,
            f"duplicate software source reference: {source_id}",
            failures,
        )
        source_reference_ids.add(source_id)
        require(
            source["ref_commit"] == software["branch_head"],
            f"source reference is not pinned to software head: {source_id}",
            failures,
        )
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

    backend_receipt = software_json.get("backend_1139_test_receipt", {})
    require(
        backend_receipt.get("source_commit") == software["subject_commit"],
        "backend receipt source_commit mismatch",
        failures,
    )
    full_suite = backend_receipt.get("full_suite", {})
    require(
        full_suite.get("result", {}).get("passed") == 1139
        and full_suite.get("result", {}).get("failed") == 0,
        "backend full-suite count mismatch",
        failures,
    )
    require(
        full_suite.get("duration_seconds") == 759.17,
        "backend full-suite duration mismatch",
        failures,
    )
    require(
        full_suite.get("tested_state", {}).get("exact_final_commit_run") is False,
        "backend receipt must preserve exact_final_commit_run=false",
        failures,
    )
    focused = backend_receipt.get("focused_checks", [])
    require(
        len(focused) == 1
        and focused[0].get("result", {}).get("passed") == 59
        and focused[0].get("result", {}).get("failed") == 0,
        "backend focused bridge mismatch",
        failures,
    )

    website_artifact = website["artifacts"][0]
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
        website_receipt.get("subject_commit") == website["subject_commit"],
        "website receipt subject mismatch",
        failures,
    )
    require(
        website_receipt.get("summarySha256") == website_artifact["summary_sha256"],
        "website summary SHA-256 mismatch",
        failures,
    )
    checks = website_receipt.get("summary", {}).get("checks", {})
    require(
        checks.get("frontendTests", {}).get("tests") == "322/322",
        "website frontend test count mismatch",
        failures,
    )
    require(
        all(
            checks.get(name, {}).get("result") == "pass"
            for name in ("typecheck", "lint", "frontendBuild")
        ),
        "website typecheck/lint/build receipt mismatch",
        failures,
    )
    require(
        checks.get("deploymentContract", {}).get("tests") == "9/9",
        "website deployment test count mismatch",
        failures,
    )
    artifact_summary = website_receipt.get("summary", {}).get("artifact", {})
    require(
        artifact_summary.get("fileCount") == 117
        and artifact_summary.get("deterministicAcrossTwoBuilds") is True,
        "website deterministic build receipt mismatch",
        failures,
    )
    verified_artifacts.append({"id": website_artifact["id"], "sha256": website_actual})

    prerequisites = manifest.get("merge_prerequisites", [])
    require(
        any(
            item.get("pull_request") == 88 and item.get("required_before_report_merge") is True
            for item in prerequisites
        ),
        "website PR #88 prerequisite missing",
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
