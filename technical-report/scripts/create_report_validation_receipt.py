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
    "technical-report/.gitignore",
    "technical-report/README.md",
    "technical-report/body.tex",
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
    log_path = args.log.resolve()
    manifest_path = args.manifest.resolve()
    for path in (pdf, audit_path, log_path, manifest_path):
        require(path.is_file(), f"missing validation input: {path}")

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
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
    require(pages == 13 and audit["pages"] == 13, "report must contain 13 pages")
    require(
        policy["total"] == 44 and policy["passed"] == 44 and policy["failed"] == 0,
        "explanatory-body last-line policy did not pass 44/44",
    )
    require(not audit["paragraph_geometry"]["unlocated"], "unlocated paragraphs")
    require(
        not audit["paragraph_geometry"]["cross_page_splits"],
        "cross-page paragraph split",
    )
    require(not audit["bottom_failures"], "page-bottom audit failed")
    require(audit["gray_text_run_count"] == 0, "unexpected gray text")
    require(args.visual_review_passed, "visual review attestation was not supplied")

    receipt = {
        "schema_version": "dronedream.technical-report-validation-receipt.v2",
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
            "reasonable_exceptions": audit["paragraph_policy"]["reasonable_exceptions"],
            "unlocated": audit["paragraph_geometry"]["unlocated"],
            "cross_page_splits": audit["paragraph_geometry"]["cross_page_splits"],
            "bottom_failures": audit["bottom_failures"],
            "gray_text_runs": audit["gray_text_run_count"],
            "internal_links": audit["links"]["internal"],
            "external_links": audit["links"]["external"],
        },
        "compile_log": {
            "sha256": sha256_file(log_path),
            "warning_counts": warning_counts,
            "underfull_boxes": len(re.findall(r"Underfull \\[hv]box", log_text)),
        },
        "visual_review": {
            "status": "passed",
            "render_dpi": 150,
            "inspected_pages": list(range(1, 14)),
            "page_bottoms_inspected": list(range(1, 14)),
            "defects_fixed": [
                {
                    "page": 3,
                    "issue": (
                        "Outcome Memory label was clipped in the migrated architecture figure."
                    ),
                    "resolution": (
                        "Regenerated the report-owned figure with fitted "
                        "text and verified the replacement render."
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
            "receipt": ("python technical-report/scripts/create_report_validation_receipt.py"),
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
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
