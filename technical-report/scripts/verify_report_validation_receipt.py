from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from pypdf import PdfReader


def git_bytes(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def git_text(repo: Path, *args: str) -> str:
    return git_bytes(repo, *args).decode("utf-8").strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def require_lf_json(payload: bytes, label: str) -> dict[str, Any]:
    require(not payload.startswith(b"\xef\xbb\xbf"), f"{label} contains a BOM")
    require(b"\r" not in payload, f"{label} is not LF-only")
    require(payload.endswith(b"\n"), f"{label} lacks a final newline")
    value = json.loads(payload.decode("utf-8"))
    require(isinstance(value, dict), f"{label} root is not an object")
    return value


def source_tree_digest(repo: Path, subject_commit: str) -> dict[str, Any]:
    listing = git_text(
        repo,
        "ls-tree",
        "-r",
        "--full-tree",
        subject_commit,
        "--",
        "technical-report",
    )
    records: list[dict[str, str]] = []
    canonical_lines: list[str] = []
    for line in listing.splitlines():
        metadata, path = line.split("\t", 1)
        mode, object_type, object_id = metadata.split()
        if path.startswith("technical-report/output/"):
            continue
        if path.startswith("technical-report/validation-receipts/"):
            continue
        records.append(
            {
                "path": path,
                "mode": mode,
                "type": object_type,
                "git_object": object_id,
            }
        )
        canonical_lines.append(f"{mode}\0{object_type}\0{object_id}\0{path}\n")
    canonical = "".join(canonical_lines).encode("utf-8")
    return {
        "file_count": len(records),
        "canonical_sha256": sha256_bytes(canonical),
        "files": records,
    }


def commit_file(repo: Path, commit: str, path: str) -> bytes:
    return git_bytes(repo, "show", f"{commit}:{path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()

    repo = args.repository.resolve()
    artifact_commit = git_text(repo, "rev-parse", args.commit).lower()
    receipt_path = PurePosixPath(args.receipt).as_posix()
    require(
        receipt_path.startswith("technical-report/validation-receipts/"),
        "receipt must be under technical-report/validation-receipts",
    )
    receipt_bytes = commit_file(repo, artifact_commit, receipt_path)
    receipt = require_lf_json(receipt_bytes, "receipt")
    schema_version = receipt["schema_version"]
    require(
        schema_version
        in {
            "dronedream.technical-report-validation-receipt.v2",
            "dronedream.technical-report-validation-receipt.v3",
        },
        "unsupported receipt schema",
    )
    require(
        receipt["serialization"]
        == {
            "json_encoding": "utf-8",
            "json_newline": "lf",
            "final_newline": True,
        },
        "receipt serialization contract is invalid",
    )

    subject_commit = str(receipt["subject_commit"]).lower()
    require(
        PurePosixPath(receipt_path).stem == subject_commit,
        "receipt filename does not equal its subject commit",
    )
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", subject_commit, artifact_commit],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    require(ancestry.returncode == 0, "subject is not an artifact ancestor")
    require(
        receipt["source_tree"] == source_tree_digest(repo, subject_commit),
        "source-tree digest does not match the subject commit",
    )

    manifest_record = receipt["evidence_reference_manifest"]
    manifest_path = str(manifest_record["path"])
    manifest_bytes = commit_file(repo, subject_commit, manifest_path)
    require(
        sha256_bytes(manifest_bytes) == manifest_record["sha256"],
        "evidence-reference manifest hash mismatch",
    )

    claim_summary: dict[str, Any] | None = None
    if schema_version == "dronedream.technical-report-validation-receipt.v3":
        claim_record = receipt["claim_evidence"]
        ledger_record = claim_record["ledger"]
        ledger_bytes = commit_file(
            repo,
            subject_commit,
            str(ledger_record["path"]),
        )
        require_lf_json(ledger_bytes, "claim ledger")
        require(
            sha256_bytes(ledger_bytes) == ledger_record["sha256"],
            "committed claim ledger hash mismatch",
        )
        claim_audit_record = claim_record["audit"]
        claim_audit_bytes = commit_file(
            repo,
            artifact_commit,
            str(claim_audit_record["path"]),
        )
        claim_audit = require_lf_json(claim_audit_bytes, "claim audit")
        require(
            sha256_bytes(claim_audit_bytes) == claim_audit_record["sha256"],
            "committed claim audit hash mismatch",
        )
        require(
            claim_audit["status"] == "passed"
            and claim_audit["claim_total"] == claim_audit_record["claims"]
            and claim_audit["claim_passed"] == claim_audit_record["passed"]
            and claim_audit["claim_failed"] == claim_audit_record["failed"] == 0
            and claim_audit["assertion_total"] == claim_audit_record["assertions"]
            and claim_audit["ledger"]["sha256"] == ledger_record["sha256"]
            and claim_audit["evidence_reference_manifest"]["sha256"] == manifest_record["sha256"],
            "committed claim-evidence audit summary mismatch",
        )
        require(
            claim_audit["verified_sources"] == claim_audit_record["verified_sources"],
            "committed claim source inventory mismatch",
        )
        claim_summary = {
            "claim_audit_sha256": sha256_bytes(claim_audit_bytes),
            "claims": claim_audit["claim_total"],
            "claim_assertions": claim_audit["assertion_total"],
            "verified_claim_sources": len(claim_audit["verified_sources"]),
        }

    pdf_record = receipt["pdf"]
    pdf_bytes = commit_file(repo, artifact_commit, str(pdf_record["path"]))
    require(
        sha256_bytes(pdf_bytes) == pdf_record["sha256"],
        "committed PDF hash mismatch",
    )
    require(
        len(pdf_bytes) == pdf_record["bytes"],
        "committed PDF byte count mismatch",
    )
    require(
        len(PdfReader(io.BytesIO(pdf_bytes)).pages) == pdf_record["pages"] == 13,
        "committed PDF page count mismatch",
    )

    audit_record = receipt["audit"]
    audit_bytes = commit_file(repo, artifact_commit, str(audit_record["path"]))
    audit = require_lf_json(audit_bytes, "audit")
    require(
        sha256_bytes(audit_bytes) == audit_record["sha256"],
        "committed audit hash mismatch",
    )
    policy = audit["paragraph_policy"]["explanatory_body"]
    require(
        policy["total"] == 40 and policy["passed"] == 40 and policy["failed"] == 0,
        "committed audit does not pass the 40/40 explanatory-body gate",
    )
    require(not audit["bottom_failures"], "committed audit has bottom failures")
    require(
        not audit["paragraph_geometry"]["unlocated"],
        "committed audit has unlocated paragraphs",
    )
    require(
        not audit["paragraph_geometry"]["cross_page_splits"],
        "committed audit has cross-page paragraph splits",
    )

    result = {
        "status": "passed",
        "artifact_commit": artifact_commit,
        "subject_commit": subject_commit,
        "receipt_path": receipt_path,
        "receipt_sha256": sha256_bytes(receipt_bytes),
        "pdf_sha256": sha256_bytes(pdf_bytes),
        "audit_sha256": sha256_bytes(audit_bytes),
        "pages": len(PdfReader(io.BytesIO(pdf_bytes)).pages),
        "explanatory_body_passed_80": policy["passed"],
    }
    if claim_summary is not None:
        result.update(claim_summary)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
