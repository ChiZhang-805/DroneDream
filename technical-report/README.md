# DroneDream AURORA technical report

This directory is the repository-owned source and validation boundary for the
AURORA technical report. It was migrated byte-for-byte from the read-only
handoff source before path and frozen-evidence corrections were applied. The
original source hashes are retained in
`evidence-reference-manifest.json`.

## Ownership boundary

The report branch owns only this `technical-report/` directory. Backend source,
the evidence exporter, test fixtures, raw evaluation artifacts, test logs,
frontend source, and website receipts remain owned by their producing
branches. This directory references those artifacts by immutable Git commit,
path, and SHA-256; it does not copy them.

The software chain is:

- subject: `0429b4244fc1fd912bd211e80821ebdbabb8ae5d`
- provenance: `738157c586561ec1e5466a997cd04758263c967b`
- branch head: `a0040d49e9f089513b30b24e807a8f39c3bbf458`

The website chain is:

- subject: `a64f995093e13c74318219cd0f91ad2d03016f31`
- attestation: `943f3b65187247fe67eed76bc698b262adb06994`
- prerequisite: [Draft PR #88](https://github.com/ChiZhang-805/DroneDream/pull/88)

PR #88 must merge before the report PR may merge.

## Evidence boundary

The frozen backend receipt records 1,139 tests in 759.17 seconds on a
pre-commit worktree and explicitly sets `exact_final_commit_run=false`. It
also records a 59-check focused bridge on the software subject commit. It does
not receipt Ruff, mypy, or the Windows Rust desktop gate. The Rust gate was
not run because Visual Studio C++ Build Tools and `link.exe` were unavailable.

The website receipt records 322/322 frontend tests, typecheck, lint, build,
nine deployment-contract tests, and deterministic 117-file output across two
builds.

Verify both dependency chains without checking out or copying their raw
evidence:

```powershell
python technical-report/scripts/verify_evidence_reference_manifest.py
```

## Build and audit

The build requires XeLaTeX, Pandoc, Poppler (`pdftoppm`), and Python with
`pdfplumber` and `pypdf`.

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File technical-report/scripts/build_report.ps1
```

The script performs two XeLaTeX passes, rejects warning gates, renders all 13
pages, runs the structural/paragraph/link audit, and publishes the validated
PDF and portable audit to `technical-report/output/`. The paragraph gate
requires all explanatory prose, including the abstract, to end with a
rendered line at least 80% as wide as its usable body line. Headings, lists,
display formulas, code blocks, figure/table captions, and references are
inventoried as reasonable exceptions instead of being silently pooled with
body prose. Intermediate files remain under the ignored
`technical-report/build/` directory.

The audit and receipt writers emit UTF-8 JSON with LF newlines as exact bytes,
independent of the host operating system. After the artifact layer is
committed, verify the hashes against Git object bytes rather than the mutable
working-tree representation:

```powershell
python technical-report/scripts/verify_report_validation_receipt.py `
  --repository . `
  --commit HEAD `
  --receipt technical-report/validation-receipts/<subject-commit>.json
```

The architecture schematic is regenerated deterministically when its labels
or topology change:

```powershell
python technical-report/scripts/generate_architecture_figure.py `
  --output technical-report/media/media/image3.png
```

## Commit layering

The release uses two layers to avoid self-reference:

1. Commit the report source, media, scripts, README, and dependency manifest.
2. Build from that source commit, then commit the final PDF, audit artifacts,
   and validation receipt that names and hashes the source commit.

The report PR targets `codex/aurora-completion-20260728`, not `main`.
