from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from pypdf import PdfReader

SOURCE_PATHS = (
    "technical-report/.gitattributes",
    "technical-report/.gitignore",
    "technical-report/README.md",
    "technical-report/body.tex",
    "technical-report/claim-evidence-ledger.json",
    "technical-report/evidence-reference-manifest.json",
    "technical-report/main.tex",
    "technical-report/media",
    "technical-report/scripts",
)
WARNING_PATTERNS = {
    "overfull": re.compile(r"Overfull", re.IGNORECASE),
    "latex_warning": re.compile(r"LaTeX Warning", re.IGNORECASE),
    "package_warning": re.compile(r"Package .* Warning", re.IGNORECASE),
    "undefined_control_sequence": re.compile(
        r"undefined control sequence",
        re.IGNORECASE,
    ),
    "undefined_references": re.compile(
        r"undefined references",
        re.IGNORECASE,
    ),
}


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def write_json_lf(path: Path, value: object) -> None:
    """Write canonical UTF-8 JSON without platform newline translation."""
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(payload.encode("utf-8"))


def source_tree_digest(repo: Path, subject_commit: str) -> dict[str, Any]:
    listing = git(
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
        "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
        "files": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--subject-commit", required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--claim-audit", type=Path, required=True)
    parser.add_argument("--claim-ledger", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--visual-review-passed", action="store_true")
    args = parser.parse_args()

    repo = args.repository.resolve()
    subject_commit = args.subject_commit.lower()
    head = git(repo, "rev-parse", "HEAD").lower()
    require(head == subject_commit, "HEAD does not equal the report subject commit")

    dirty_source = git(repo, "status", "--porcelain", "--", *SOURCE_PATHS)
    require(not dirty_source, f"report source is dirty:\n{dirty_source}")

    pdf = args.pdf.resolve()
    audit_path = args.audit.resolve()
    claim_audit_path = args.claim_audit.resolve()
    claim_ledger_path = args.claim_ledger.resolve()
    log_path = args.log.resolve()
    manifest_path = args.manifest.resolve()
    for path in (
        pdf,
        audit_path,
        claim_audit_path,
        claim_ledger_path,
        log_path,
        manifest_path,
    ):
        require(path.is_file(), f"missing validation input: {path}")

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    claim_audit = json.loads(claim_audit_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    warning_counts = {
        name: len(pattern.findall(log_text)) for name, pattern in WARNING_PATTERNS.items()
    }
    require(
        all(count == 0 for count in warning_counts.values()),
        f"warning gate failed: {warning_counts}",
    )

    pages = len(PdfReader(pdf).pages)
    policy = audit["paragraph_policy"]["explanatory_body"]
    short_list_policy = audit["paragraph_policy"]["short_list_items"]
    require(pages == 18 and audit["pages"] == 18, "report must contain 18 pages")
    require(
        policy["total"] == 54 and policy["passed"] == 54 and policy["failed"] == 0,
        "explanatory-body last-line policy did not pass 54/54",
    )
    require(
        short_list_policy["total"] == 12
        and short_list_policy["passed"] == 12
        and short_list_policy["failed"] == 0
        and len(short_list_policy["above_3_lines"]) == 20,
        "short-list last-line policy did not pass 12/12; long-list inventory drifted",
    )
    require(not audit["paragraph_geometry"]["unlocated"], "unlocated paragraphs")
    require(
        not audit["paragraph_geometry"]["cross_page_splits"],
        "cross-page paragraph split",
    )
    require(not audit["bottom_failures"], "page-bottom audit failed")
    require(audit["gray_text_run_count"] == 0, "unexpected gray text")
    require(
        claim_audit["status"] == "passed"
        and claim_audit["claim_failed"] == 0
        and claim_audit["claim_passed"] == claim_audit["claim_total"]
        and claim_audit["claim_total"] >= 13
        and claim_audit["assertion_total"] >= 80,
        "claim-evidence audit did not pass its complete declared scope",
    )
    require(
        claim_audit["ledger"]["sha256"] == sha256_file(claim_ledger_path),
        "claim-evidence ledger hash mismatch",
    )
    require(
        claim_audit["evidence_reference_manifest"]["sha256"] == sha256_file(manifest_path),
        "claim audit evidence-reference manifest hash mismatch",
    )
    require(args.visual_review_passed, "visual review attestation was not supplied")

    receipt = {
        "schema_version": "dronedream.technical-report-validation-receipt.v6",
        "subject_commit": subject_commit,
        "parent_software_head": manifest["software"]["branch_head"],
        "branch": git(repo, "branch", "--show-current"),
        "serialization": {
            "json_encoding": "utf-8",
            "json_newline": "lf",
            "final_newline": True,
        },
        "source_tree": source_tree_digest(repo, subject_commit),
        "evidence_reference_manifest": {
            "path": "technical-report/evidence-reference-manifest.json",
            "sha256": sha256_file(manifest_path),
            "software_subject": manifest["software"]["subject_commit"],
            "software_provenance": manifest["software"]["provenance_commit"],
            "software_head": manifest["software"]["branch_head"],
            "website_subject": manifest["website"]["subject_commit"],
            "website_attestation": manifest["website"]["attestation_commit"],
            "website_prerequisite": 88,
        },
        "pdf": {
            "path": "technical-report/output/DroneDream_AURORA_Technical_Report.pdf",
            "sha256": sha256_file(pdf),
            "bytes": pdf.stat().st_size,
            "pages": pages,
        },
        "audit": {
            "path": "technical-report/output/latex-audit.json",
            "sha256": sha256_file(audit_path),
            "audited_blocks": audit["paragraph_geometry"]["audited"],
            "explanatory_body": {
                "total": policy["total"],
                "passed_80": policy["passed"],
                "failed_80": policy["failed"],
                "failure_locations": policy["failure_locations"],
            },
            "short_list_items": {
                "total": short_list_policy["total"],
                "passed_90": short_list_policy["passed"],
                "failed_90": short_list_policy["failed"],
                "maximum_lines": short_list_policy["maximum_lines"],
                "failure_locations": short_list_policy["failure_locations"],
                "above_3_lines": short_list_policy["above_3_lines"],
            },
            "reasonable_exceptions": audit["paragraph_policy"]["reasonable_exceptions"],
            "unlocated": audit["paragraph_geometry"]["unlocated"],
            "cross_page_splits": audit["paragraph_geometry"]["cross_page_splits"],
            "bottom_failures": audit["bottom_failures"],
            "gray_text_runs": audit["gray_text_run_count"],
            "internal_links": audit["links"]["internal"],
            "external_links": audit["links"]["external"],
        },
        "claim_evidence": {
            "ledger": {
                "path": "technical-report/claim-evidence-ledger.json",
                "sha256": sha256_file(claim_ledger_path),
            },
            "audit": {
                "path": "technical-report/output/claim-evidence-audit.json",
                "sha256": sha256_file(claim_audit_path),
                "claims": claim_audit["claim_total"],
                "passed": claim_audit["claim_passed"],
                "failed": claim_audit["claim_failed"],
                "assertions": claim_audit["assertion_total"],
                "verified_sources": claim_audit["verified_sources"],
            },
        },
        "compile_log": {
            "sha256": sha256_file(log_path),
            "warning_counts": warning_counts,
            "underfull_boxes": len(re.findall(r"Underfull \\[hv]box", log_text)),
        },
        "visual_review": {
            "status": "passed",
            "render_dpi": 150,
            "inspected_pages": list(range(1, 19)),
            "page_bottoms_inspected": list(range(1, 19)),
            "defects_fixed": [
                {
                    "page": 1,
                    "issue": (
                        "The DroneDream lockup was centered instead of aligned to the upper-left report margin."
                    ),
                    "resolution": (
                        "Left-aligned the lockup, enlarged the title and Abstract heading, and rechecked the full page."
                    ),
                },
                {
                    "page": 7,
                    "issue": (
                        "Table 3 split across pages and Figure 3 labels were vertically crowded near the zero bar."
                    ),
                    "resolution": (
                        "Made Table 3 indivisible, increased Figure 3 height and row spacing, and offset the zero label."
                    ),
                },
                {
                    "page": 18,
                    "issue": (
                        "References used two columns and retained an explanatory paragraph below the heading."
                    ),
                    "resolution": (
                        "Removed the paragraph and rendered all references in one readable column."
                    ),
                }
            ],
            "remaining_blocking_defects": [],
        },
        "reproduction": {
            "build": (
                "powershell -NoProfile -ExecutionPolicy Bypass "
                "-File technical-report/scripts/build_report.ps1"
            ),
            "receipt": (
                "python technical-report/scripts/create_report_validation_receipt.py "
                "--repository . --subject-commit <source-commit> "
                "--pdf technical-report/output/DroneDream_AURORA_Technical_Report.pdf "
                "--audit technical-report/output/latex-audit.json "
                "--claim-audit technical-report/output/claim-evidence-audit.json "
                "--claim-ledger technical-report/claim-evidence-ledger.json "
                "--log technical-report/build/main.log "
                "--manifest technical-report/evidence-reference-manifest.json "
                "--output technical-report/validation-receipts/<source-commit>.json "
                "--visual-review-passed"
            ),
            "claim_evidence": (
                "python technical-report/scripts/verify_claim_evidence.py "
                "--repository . "
                "--ledger technical-report/claim-evidence-ledger.json "
                "--manifest technical-report/evidence-reference-manifest.json "
                "--body technical-report/body.tex "
                "--output technical-report/output/claim-evidence-audit.json"
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json_lf(args.output, receipt)
    print(
        json.dumps(
            {
                "status": "passed",
                "subject_commit": subject_commit,
                "pdf_sha256": receipt["pdf"]["sha256"],
                "audit_sha256": receipt["audit"]["sha256"],
                "claim_audit_sha256": receipt["claim_evidence"]["audit"]["sha256"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
