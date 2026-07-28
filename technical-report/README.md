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

- branch: `codex/software`
- subject: `742b12467efc9b37b7e4a2fa3ac73b7578f21385`
- evidence publication/head: `1bf83ccd83913c5e66c2916e5250ccf5b27cad6f`

The website chain is:

- subject: `a64f995093e13c74318219cd0f91ad2d03016f31`
- attestation: `943f3b65187247fe67eed76bc698b262adb06994`
- prerequisite: [Draft PR #88](https://github.com/ChiZhang-805/DroneDream/pull/88)

PR #88 must merge before the report PR may merge.

## Evidence boundary

The frozen backend receipt records 1,147 tests in 788.78 seconds on the exact
software subject commit and explicitly sets `exact_final_commit_run=true`.
An 81-check focused supplement passed in 151.96 seconds on the same subject;
the receipt states that it supplements, rather than bridges from, the exact
full run. It does not receipt Ruff, mypy, or the Windows Rust desktop gate.
The Rust gate was not run because Visual Studio C++ Build Tools and `link.exe`
were unavailable.

The v7 routing evidence preserves all three Evidence 2.7 provider freezes.
The two Prompt 1.5 freezes independently regrade to 19/24 (unqualified) and
21/24 (qualified); the current Prompt 1.6 freeze regrades to 24/24. These are
unpaired stochastic calls. The current result qualifies the frozen
development-routing contract and is not a causal prompt-lift estimate or a
simulator-outcome claim.

The website receipt records 322/322 frontend tests, typecheck, lint, build,
nine deployment-contract tests, and deterministic 117-file output across two
builds.

Verify both dependency chains without checking out or copying their raw
evidence:

```powershell
python technical-report/scripts/verify_evidence_reference_manifest.py
```

The report-owned `claim-evidence-ledger.json` binds publication-facing
counts, rates, scenario rows, contract versions, phase-role counts, and the
PX4/Gazebo qualification boundary to those immutable source IDs. It contains
report assertions and references, not copied backend evidence. Verify every
declared projection against Git object bytes:

```powershell
python technical-report/scripts/verify_claim_evidence.py `
  --repository . `
  --ledger technical-report/claim-evidence-ledger.json `
  --manifest technical-report/evidence-reference-manifest.json `
  --body technical-report/body.tex `
  --output technical-report/output/claim-evidence-audit.json
```

## Build and audit

The build requires XeLaTeX, Pandoc, Poppler (`pdftoppm`), and Python with
`matplotlib`, `numpy`, `Pillow`, `pdfplumber`, and `pypdf`. When a Codex runtime
`pdftoppm` wrapper is present,
the script resolves the actual bundled Poppler executable from that wrapper's
dependency root; `-PdfToPpm <path>` remains available for an explicit override.

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File technical-report/scripts/build_report.ps1
```

The script regenerates Figures 2--6 from the frozen evidence bundle in an
ignored build directory and requires their rendered pixels to match the
tracked PNGs. It then performs two XeLaTeX passes, rejects warning gates,
renders all 13 pages, runs the structural/paragraph/link audit, and publishes
the validated PDF, layout audit, and claim-evidence audit to
`technical-report/output/`.
The claim gate fails the build when a declared report projection drifts from
its frozen JSON pointer, source assertion, or computed phase-role count. The
paragraph gate requires all explanatory prose, including the abstract, to end
with a rendered line at least 80% as wide as its usable body line. Headings,
lists, display formulas, code blocks, figure/table captions, and references
are inventoried as reasonable exceptions instead of being silently pooled
with body prose. Intermediate files remain under the ignored
`technical-report/build/` directory.

The audit and receipt writers emit UTF-8 JSON with LF newlines as exact bytes,
independent of the host operating system. After visually reviewing the final
13-page render, create the artifact-layer receipt:

```powershell
python technical-report/scripts/create_report_validation_receipt.py `
  --repository . `
  --subject-commit <source-commit> `
  --pdf technical-report/output/DroneDream_AURORA_Technical_Report.pdf `
  --audit technical-report/output/latex-audit.json `
  --claim-audit technical-report/output/claim-evidence-audit.json `
  --claim-ledger technical-report/claim-evidence-ledger.json `
  --log technical-report/build/main.log `
  --manifest technical-report/evidence-reference-manifest.json `
  --output technical-report/validation-receipts/<source-commit>.json `
  --visual-review-passed
```

After the artifact layer is committed, verify the hashes against Git object
bytes rather than the mutable working-tree representation:

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

Regenerate the five evidence-backed charts only when their frozen data or
presentation contract changes:

```powershell
python technical-report/scripts/generate_data_figures.py `
  --repository . `
  --manifest technical-report/evidence-reference-manifest.json `
  --output-directory technical-report/media/media
```

## Commit layering

The release uses two layers to avoid self-reference:

1. Commit the report source, media, scripts, README, and dependency manifest.
2. Build from that source commit, then commit the final PDF, audit artifacts,
   and validation receipt that names and hashes the source commit.

Any integration of this report must retain software subject
`742b12467efc9b37b7e4a2fa3ac73b7578f21385` and evidence head
`1bf83ccd83913c5e66c2916e5250ccf5b27cad6f` as immutable dependencies.

## Website handoff

The website receives only the final validated PDF and its SHA-256. Report
source, generators, manifests, ledgers, audits, and receipts remain owned by
`technical-report/` and must not be copied into the website branch.
