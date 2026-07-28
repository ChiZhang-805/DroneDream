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
- cross-Job memory implementation: `abb9002746e061af44a164fe749243d68d098e10`
- v9 software subject: `c1222c9215e01a56351f6588af0d2b8694bca831`
- v9 receipt-only evidence head: `8102ffecb37b1f1b0e25c80d6b02db05325ca986`
- online-routing implementation: `aeffaae01a8106f74ff811b39ec26d9d2203d1f6`
- multi-tool budget source: `136a1e3293efa6e53f3648e21fa8f7c6b5158d6f`
- current software/evidence head: `2f1caae6fbb5b037e55a4b339dff6c590833f019`
- physical-campaign subject: `86273db6d827a790cb0a8b1472256b23e0a629d2`
- physical-campaign evidence head: `3b09951bbea2e5f1c64197b0347a0ed529172192`
- advanced-physics subject: `26b957efd985d0ac37702a8d2518e87ab65347c3`
- advanced-physics exporter: `06cfdeb4438be59a24510738ab135b06fdde373a`
- advanced-physics evidence head: `d14bf9c0d453599b2bc9733be8c4159fef67c220`
- GPS/battery negative-control implementation: `fdf1250398567c6658ad5148efc1c302dede4a17`
- GPS/battery negative-control evidence head: `2f1caae6fbb5b037e55a4b339dff6c590833f019`

The website chain is:

- release-truth source: `fd7e7702dd2e8d86cedda86790b5d93b048463da`
- release-truth receipt-only attestation: `87e049cc426bec0f16ace8130bac672dbb778f22`
- latest typography source: `87105531e0f591662c724dcbbe96f3adbfa4a321`
- latest receipt-only attestation: `96aba5de2ff20ebe8f201f958c996c5685189619`

The report has no mutable cross-branch merge prerequisite; it consumes both
chains only through immutable commit/path/SHA references.

## Evidence boundary

The frozen backend receipt records 1,204 tests on the exact software subject
commit and explicitly sets `exact_final_commit_run=true`. The pytest log records
854.71 seconds while the receipt wall interval is 864.488 seconds. A 28-check
focused supplement records 6.98 seconds in its pytest log and 8.451 seconds in
the receipt; it supplements, rather than bridges from, the exact full run. The
receipt does not cover Ruff, mypy, or the Windows Rust desktop gate.
The Rust gate was not run because Visual Studio C++ Build Tools and `link.exe`
were unavailable.

Evidence v9 publishes the current Evidence 2.8 / Prompt 1.7 / Decision Trace
1.4 cross-Job memory contract. Its deterministic in-memory SQLite evaluation
passes 10/10 fixtures: two positive retrievals and eight isolation/lifecycle
negatives, with zero provider, network, or simulator calls and zero
provider-identifier leaks. Only terminal `verified_complete` decision/cohort
evidence may materialize; retrieval remains within one authenticated user,
across a different source Job, and within the exact structural task family.
Retention is 90 days, revocation and deletion cascade are enforced, contract
or receipt drift fails closed, and at most six anonymous closed-structure
observations reach the provider projection. This is
`observational_not_causal`, not evidence of provider effect, optimizer gain,
physical fidelity, real-aircraft performance, or safety improvement.

The current online-routing freeze binds Evidence 2.8 / Prompt 1.7 / Tool 2.1,
`gpt-4.1-2025-04-14`, temperature 0, top-p 1, seed 20260728, and 24 provider
calls. Independent regrading finds 23/24 acceptable selections (95.83%) and
one retained failure, `tight_budget_expensive_matrix`, which selected TuRBO
instead of multi-fidelity MOBO or the optimizer portfolio. The result qualifies
the exact current development contract: it exceeds the 75% overall threshold,
the 15-percentage-point lift threshold by recording 37.5 percentage points
over the best constant, and the two-thirds category threshold. It does not
show causal prompt lift, provider determinism from the seed, optimizer gain,
simulator or flight improvement, or broad model generalization.

Evidence v9 also preserves all three older Evidence 2.7 provider freezes as
archived (`contract_current=false`) observations.
The two Prompt 1.5 freezes independently regrade to 19/24 (unqualified) and
21/24 (qualified); the Prompt 1.6 freeze regrades to 24/24. These are unpaired
stochastic calls. The archived result qualifies only the historical
development-routing contract and is not a causal prompt-lift estimate or a
simulator-outcome claim.

Evidence 2.9 is a separate offline equal-budget, multi-tool plan-history and
accounting closure. Across three scripted seed blocks it records six arm runs,
six verified generations including three multi-tool generations, and 12/12
decision/accounted calls. It uses `MockSimulator`, zero provider/network calls,
and no real credentials. The retained first repository-root attempt failed with
`ModuleNotFoundError(app)` before producing any Job or external call; source
`136a1e3293efa6e53f3648e21fa8f7c6b5158d6f` fixed and regression-locked the CLI.
This evidence does not measure real-LLM planning quality, optimizer superiority,
physical fidelity, flight performance, or a causal Harness benefit.

The dedicated physical campaign records 6/6 successful and passing x500
PX4/Gazebo Trials across two seeds and nominal, steady-wind, and
static-obstacle scenarios. It binds the exact Runtime and environment,
RMSE/max-error/coverage ranges, two wind read-backs, two obstacle-create
acknowledgements, 598 inventoried source files, 154 retained files, and four
chronological failure probes. This proves the retained execution matrix and
scenario injection only. It does not prove optimizer superiority, broad
reliability, collision avoidance, signed customer-Runtime acceptance,
real-aircraft safety, or sim-to-real transfer.

The physical manifest and receipt embed exporter/observer identifier
`5f0f62c789680e5e2d34c6513727199fabbd50d0`, while the handoff names
`c373dc9e4964301a051d14d8e76d249481719c96`; neither resolves in the fetched
repository. The verifier instead binds the reachable source chain
`c373dc992d43ff921ea8a1db07fcc26591955576` to
`5f0f62c707c541aed7918e56a0170a7f67bd6ffb` to the evidence head, and
retains the non-resolving declarations as a provenance defect.

The separate advanced-physics bundle records three successful and passing
same-seed x500 trajectories after five effects were requested, applied, and
verified: payload mass, first-order actuator delay, barometer noise, scaled IMU
noise, and wind gusts. Two additional GPS-noise attempts apply and verify all
six requested effects but end at a 30.0-second PX4 readiness timeout; they prove
injection/read-back only and remain failed, metric-free boundary attempts. One
file-backed attempt retains the PX4 dubious-ownership failure. Three still
earlier terminal preflights have no raw files and remain explicitly
non-machine-verified narrative history.

The bundle references 114 committed files / 9,442,999 bytes while its manifest
inventories 1,205 source files / 305,040,238 bytes and retains the minimum
sufficient 111 files / 8,994,710 bytes. Every retained file, internal canonical
hash, sidecar line, Git blob, and the deterministic `mtime=0` gzip ULog is
rechecked by the report verifier. The bundle claims PX4 SITL v1.16 at commit
`6ea3539157ca358c70a515878b77077af7d4611d`, x500, and the default world; it
does not claim a Gazebo version or WSL Runtime identifier. Its three same-seed
successes do not establish broad reliability, safety, real-aircraft behavior,
sim-to-real transfer, customer acceptance, or optimizer superiority. Remaining
evidence gaps are probability-law behavior across seeds, dropout endurance,
depleted-battery stability, combined-fault qualification, and hard actuator
failure beyond the bounded first-order delay profile.

A later exact-commit negative-control Trial separately verifies deterministic
GPS denial/recovery plus battery initial-state and voltage-sag injection. Its
runner and acceptance commands exit zero, all three effects are applied and
verified, and the trajectory completes without crash or timeout. The result is
nevertheless not a pass: position speed reaches 31.211302 m/s against the
25 m/s policy gate. This Trial therefore remains excluded from both the 3/3
advanced-effects pass numerator and the 6/6 scenario-matrix pass numerator.
The report manifest binds its receipt, failure lineage, ULog, applied-scenario
record, and 159-test JUnit by path, commit, and SHA-256 without copying the
upstream attempt directory.

The latest typography receipt records 13/13 focused PublicSite checks, 325/325
frontend tests across 50 files, typecheck, lint, application and shared builds,
11/11 deployment tests with 22/22 subtests, and 5/5 performance routes. Desktop
English and Chinese download copy each occupies two lines with final-line fills
of 0.895 and 0.835; the mobile layout-only audit reports zero violations. Its
subject explicitly binds the preceding release-truth receipt, which separately
records 100/100 four-browser checks and 118 checksum entries across 119
shared-artifact files. No deployment occurred. TLS, dual-target publication,
production Supabase/payment, and the two different unsigned public installer
bytes remain external gates.

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

The A4 layout uses a 10-point body with 12-point leading, 24 mm side margins,
and a 25 mm top / 20 mm bottom geometry. The first-page hierarchy, upper-left
brand lockup, rounded abstract frame, and body rhythm were quantitatively
checked against the JoyAI-RA 0.1 report while preserving DroneDream's purple
identity and a roomier 21-page evidence narrative.

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File technical-report/scripts/build_report.ps1
```

The script regenerates Figures 2--6 from the frozen evidence bundle in an
ignored build directory and requires their rendered pixels to match the
tracked PNGs. It then performs two XeLaTeX passes, rejects warning gates,
renders all 21 pages, runs the structural/paragraph/link audit, and publishes
the validated PDF, layout audit, and claim-evidence audit to
`technical-report/output/`.
The claim gate fails the build when a declared report projection drifts from
its frozen JSON pointer, source assertion, or computed phase-role count. The
paragraph gate requires all explanatory prose, including the abstract, to end
with a rendered line at least 80% as wide as its usable body line. Short list
items of no more than three rendered lines are audited separately, and their
final lines must fill at least 90% of the usable list width. Longer explanatory
list items remain visible in a separate exception inventory instead of being
misclassified as short-list failures.
The page-bottom gate independently requires the lowest rendered body content
on every page to finish within one 12-point body line of the audited bottom
target; substantive technical explanation, table spacing, and figure sizing
must resolve excess space rather than hidden text or forced last-line
justification.
Headings, display formulas, code blocks, figure/table captions, and references
are inventoried as reasonable exceptions instead of being silently pooled
with body prose. Intermediate files remain under the ignored
`technical-report/build/` directory.

The audit and receipt writers emit UTF-8 JSON with LF newlines as exact bytes,
independent of the host operating system. After visually reviewing the final
21-page render, create the artifact-layer receipt:

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

Any integration of this report must retain v9 software subject
`c1222c9215e01a56351f6588af0d2b8694bca831`, v9 receipt head
`8102ffecb37b1f1b0e25c80d6b02db05325ca986`, online-routing implementation
`aeffaae01a8106f74ff811b39ec26d9d2203d1f6`, multi-tool source
`136a1e3293efa6e53f3648e21fa8f7c6b5158d6f`, current evidence head
`15603c6f3c1e421dc20802ed0b8dfcfaf7ac49e8`, physical-campaign subject
`86273db6d827a790cb0a8b1472256b23e0a629d2`, and physical evidence head
`3b09951bbea2e5f1c64197b0347a0ed529172192` as immutable dependencies.

## Website handoff

The website receives only the final validated PDF and its SHA-256. Report
source, generators, manifests, ledgers, audits, and receipts remain owned by
`technical-report/` and must not be copied into the website branch.
