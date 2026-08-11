# DroneDream Build and Cleanup Experience

This is the single authoritative human-readable log for building, validating,
and cleaning the Universal, SIM, LAB, and FIELD Windows applications. Do not
create parallel lesson, attempt, or troubleshooting Markdown files.

## Non-negotiable rules

- The eventual authoritative source root is `Z:\DroneDream-Workspace\main`.
- Preserve source, uncommitted work, edition-owned behavior, and recovery
  evidence until the replacement has been built and independently validated.
- Build outputs, dependency caches, Cargo targets, and failed-attempt files must
  stay outside the source tree unless a reviewed build contract explicitly
  requires a generated path.
- Every failed attempt records its exact source commit/tree, command, error,
  root cause, repair, generated paths, and cleanup result here.
- A failed or superseded attempt is cleaned only by exact path after useful
  diagnostics have been retained.
- Never use a real OpenAI API credential during build or validation without a
  separate purpose, scale/cost statement, and explicit approval.
- Do not edit or rebuild the frozen Technical Report as part of software work.
- Do not publish, deploy, push, or replace public release assets during local
  build validation.

## Acceptance target

The task is complete only when one authoritative source directory can
reproducibly build all four edition installers, every installer and installed
application passes its edition identity, launch, UI, coexistence, uninstall,
and safety checks, and all redundant source roots and failed build outputs have
been removed without losing recovery evidence.

## Baseline — 2026-08-11

- `Z:\DroneDream-Workspace\main` is clean at
  `a4d6e7762050cc2e7a249b8431d3c05a27be1ce8` before this log is added.
- The controlled Universal, SIM, LAB, and FIELD worktrees are clean but have
  independently developed histories and are not yet integrated into `main`.
- The legacy root `Z:\DroneDream` is dirty at
  `85be48fb21c4e38d6468a0644b72106633ab8602`, with 645 changed or untracked
  paths protected by the existing migration archives and ledgers.
- No legacy source root is authorized for deletion until the useful content is
  integrated and all four builds pass from the authoritative source root.
- Known migration blockers include SIM identity disagreement, LAB/FIELD ordinary
  build-path identity fallbacks, Runtime edition-profile defaults, and FIELD
  fail-closed hardware readiness truthfulness.
- Zero-output contract checks pass for Universal, LAB, and FIELD. The latest
  SIM plan also passes, but correctly reports that its historical exact
  worktree at `C:\Users\zju20\ddss3` still exists.
- Node, Rust 1.97, LLVM-MinGW, the approved updater-key path, GitHub
  authentication, and both approved public frontend build variables are
  available. No credential value is copied into this document or the source
  tree.

## Attempt log

### A1 - isolated dependency and frontend validation

- Scope: the four clean product worktrees, with four lockfile-derived dependency
  sets under `C:\Users\zju20\AppData\Local\DroneDream\codex-dependencies\core-four-exe-20260811-a1`.
- Initial command error: a Vitest-only `--reporter=dot` option was mistakenly
  passed to TypeScript and ESLint. It caused immediate option-parser exits and
  did not indicate a product defect. The corrected commands pass typecheck and
  lint in all four editions; the superseded logs were overwritten by the
  correct reruns.
- Universal: 88 test files and 582 tests pass. Its shared software layout and
  LAB layout checks pass when run serially.
- SIM: 74 of 75 test files pass, with 500 of 501 tests passing. The one shared
  `PublicSite` test fails; the dedicated 24-case SIM startup layout passes. The
  broader software-layout check also exposes a missing expected `ECE498BH`
  external entry and remains an open product-integration defect.
- LAB: typecheck, lint, focused LAB UI tests, and headed LAB layout pass. One
  `JobDetail` test that timed out under four-way contention passes immediately
  when rerun alone. The shared `PublicSite` test remains a deterministic failure.
- FIELD: typecheck and lint pass. One sidebar test that timed out under four-way
  contention passes immediately when rerun alone. The shared `PublicSite` test
  remains a deterministic failure.
- Lesson: do not run fixed-port headed layout scripts in parallel, and do not
  pass test-runner arguments through unrelated npm scripts. Serial headed UI
  checks are the authoritative result.
- Cleanup: the two superseded Universal port-conflict logs are deleted after
  this record; unresolved SIM/PublicSite diagnostics remain until their fixes
  pass and then will be removed with the rest of attempt A1.

### A2 - shared Python suite time-budget correction

- Source: clean Universal worktree commit
  `f6370eff0f2501e90cdcf5d0b716f371a8454fc5`.
- Command: `python -m pytest -q backend\tests distribution\tests`, with output
  retained outside the source tree in the A1 diagnostic root.
- Result: no assertion failure was observed through 41 percent, but the outer
  command runner terminated the process at its 20-minute execution limit.
  The Python process was active and consuming CPU shortly before termination.
- Root cause: the combined suite exceeds the command runner's single-call time
  budget; this is an orchestration failure, not evidence of a product failure.
- Repair: run backend and distribution tests in bounded deterministic shards,
  each with its own result and log, then require every shard to pass.
- Cleanup: the incomplete combined-run log is retained until the sharded rerun
  passes, after which it is superseded diagnostic material and will be deleted
  with the remaining A1 attempt root.

### A3 - frozen technical-report evidence isolation

- Source: clean Universal worktree commit
  `f6370eff0f2501e90cdcf5d0b716f371a8454fc5`; Python shard 3 of 8.
- Result: 269 tests pass and eight tests in
  `backend/tests/test_technical_report_evidence_v10.py` fail for the same
  fail-closed reason: `harness_routing_eval_v1.jsonl` no longer matches its
  byte identity at frozen report commit
  `ef00362927475b2fc411a4d82084bbbae8846582`.
- Root cause: the software branch continued evolving after the technical
  report's evidence freeze. The report validator correctly refuses to silently
  reinterpret the frozen report using later fixture bytes.
- Repair and scope: do not edit the frozen report, its claim, or its evidence
  contract without a separate explicit report-update request. Re-run the same
  shard excluding only this report-specific test file and require all remaining
  software tests to pass. Preserve the report failure log as boundary evidence.
- Cleanup: no source or report file was generated or changed by the failed
  test. Its temporary pytest directory is owned by pytest/Windows cleanup; the
  external diagnostic log remains until final acceptance.

### A4 - PowerShell subprocess encoding portability

- Source: clean Universal worktree commit
  `f6370eff0f2501e90cdcf5d0b716f371a8454fc5`; Python shard 6 of 8.
- Result: 281 tests pass. Three assertions in
  `distribution/tests/test_shared_windows_build_contract.py` fail after their
  Python reader threads encounter `UnicodeDecodeError` and return `None` for
  stderr.
- Root cause: the test helper explicitly decodes PowerShell 5.1 output as
  UTF-8 but does not set the spawned PowerShell process output encoding.
  Rejection paths on this Chinese Windows host include local-code-page bytes.
  The tested scripts still return the expected nonzero status; the test cannot
  inspect their message because its own decoder failed.
- Repair: in the eventual authoritative core, make the test helper establish an
  explicit UTF-8 PowerShell output protocol before executing its supplied
  script, then rerun the complete test file. Do not dirty the current clean
  product worktree before its reproducible baseline build.
- Cleanup: the failure produced no product artifact. The external shard log is
  retained until the repaired authoritative-core test passes.

### A5 - Universal clean baseline build

- Source: clean Universal worktree commit
  `f6370eff0f2501e90cdcf5d0b716f371a8454fc5`.
- Result: the Universal NSIS installer built successfully in 219.6 seconds at
  `C:\Users\zju20\AppData\Local\DroneDream\codex-builds\core-four-exe-20260811-a1\universal\build\DroneDream-Universal-1.0.0.exe`.
  The installer is 12,282,928 bytes with SHA-256
  `c8a7faba7f7606ac8b3811119decaddeb4cfd5a03447c17d9bb2efbd0f11dcff`.
- Verified contracts: the frontend production bundle, statically linked LLVM
  runtime, bundled WebView2 loader and bootstrapper, NSIS path guard, English
  and Simplified Chinese installer locales, updater signature, checksum, build
  receipt, and source-bound handoff manifest all pass. Windows PE version
  resources report product/file version `1.0.0`.
- Boundary: the receipt deliberately reports `releaseReady=false` and
  `built-awaiting-isolated-lifecycle-validation`; a successful build is not a
  substitute for isolated install, launch, coexistence, upgrade, and uninstall
  acceptance.
- Cleanup: after the installer and its receipt/checksum/signature/handoff files
  were independently hashed, the exact external Universal Cargo target (about
  1.45 GB) and generated `frontend/dist`, Tauri `gen`/`target`, and TypeScript
  incremental files were removed. The source worktree remains tracked-clean;
  only the two reviewed external dependency junctions remain.

### A6 - SIM clean baseline build

- Source: clean SIM worktree commit
  `81921d4e840e7a2add519c595800f43e42837c5f` with the SIM-specific frontend
  overlay, engine-pack profile, and public desktop identity contract.
- Result: `DroneDream-Sim-1.0.0.exe` built successfully in 193.6 seconds. The
  installer is 12,066,977 bytes with SHA-256
  `f358f9808accccb0d2711b63859801cd3cebb8682edcd2d995546e0ee9abd894`.
  Its Windows resources identify `DroneDream · SIM`, version `1.0.0`.
- Verified contracts: production frontend bundling, static LLVM/WebView2
  runtime, NSIS path guard, English and Simplified Chinese locales, updater
  signature, and checksum all pass. The checksum sidecar independently matches
  the installer bytes.
- Cleanup: after retaining the EXE/checksum/signature trio, the exact SIM Cargo
  target and generated frontend/Tauri/Python cache paths were removed. The SIM
  source worktree is tracked-clean and retains only its two external dependency
  junctions.

### A7 - LAB output-boundary rejection and correction

- Source: clean LAB worktree commit
  `e181baa1114e1c37b294eeec86a693399c8a6aaa`.
- Failed attempt: the first external runner supplied
  `C:\Users\zju20\AppData\Local\DroneDream\lab-build-attempts\core-four-exe-20260811-a1`
  as `OutputRoot`. The LAB build contract rejected it in 0.3 seconds because an
  owned preview output must be a strict descendant of
  `%LOCALAPPDATA%\DroneDream\codex-cache\lab-build-attempts`.
- Root cause: the orchestration runner preserved the intended logical folder
  name but omitted the contractually required `codex-cache` path component.
  This is a runner-path error; no frontend, Rust, NSIS, or product compilation
  had started.
- The corrected `a2` path reached the next fail-closed readiness gate and then
  stopped in 2.9 seconds because local branch `codex/software-lab` had no
  configured upstream. A read-only `ls-remote` proved that
  `origin/codex/software-lab` exists at the exact same commit; fetching that one
  remote-tracking ref and assigning it as the upstream made the LAB YELLOW
  readiness audit requestable with the pinned `gnullvm` toolchain. No source
  bytes changed and no remote write occurred.
- Repair: use a fresh `a2` child under the exact owned output base, keep the
  Cargo target separately external, and copy only the successful installer,
  updater signature, and LAB receipt into the durable diagnostic handoff root.
- Cleanup: the rejected attempt created no output root, Cargo target, product
  artifact, or source-tree file. The second attempt created only an empty owned
  output directory, which was verified as plain and empty and deleted exactly.
  Both small result/log pairs are retained only until the corrected attempt
  passes, after which they are superseded and must be deleted.

### A8 - LAB corrected baseline build

- Source: clean LAB worktree commit
  `e181baa1114e1c37b294eeec86a693399c8a6aaa`, tracking the byte-identical
  `origin/codex/software-lab` readiness reference.
- Result: the third attempt passed in 224.3 seconds and handed off
  `DroneDream-Lab-1.0.0.exe`. The installer is 12,561,865 bytes with SHA-256
  `cc7782c38d4242e41249c5c0faff90f74d40ab69671d31147170f7c26f4bcdf4`;
  its Windows identity is `DroneDream · LAB`, version `1.0.0`.
- Verified contracts: LAB YELLOW readiness selected the pinned `gnullvm`
  toolchain, the LAB frontend and hardware-workspace bundle built, static
  LLVM/WebView2 checks passed, and the source-bound updater signature and
  schema-2 LAB receipt match the installer hash and source commit.
- Cleanup: the successful artifact/signature/receipt trio was copied to the
  durable diagnostic handoff before deleting the exact owned `a3` output root,
  LAB Cargo target, and generated source-tree outputs. The two failed-attempt
  result/log pairs were deleted after A7 recorded their causes. The LAB
  worktree remains tracked-clean with only its dependency junctions.

### A9 - FIELD clean baseline build

- Source: clean FIELD worktree commit
  `7bdc8eb537996320f78f85f5e7a1d2a0b2affb1f` with its standalone field shell,
  frontend entry, native field modules, and build-authorization contract.
- Result: `DroneDream-Field-1.0.0.exe` built successfully in 268.6 seconds. The
  installer is 6,353,026 bytes with SHA-256
  `b954ba91ba85486aaaae03c6a245175de18669b6e07943f89a4472315274c901`;
  Windows resources identify `DroneDream · FIELD`, version `1.0.0`.
- Verified contracts: the FIELD gate accepted the exact source while reporting
  zero validated hardware packs and explicitly kept hardware authority denied
  pending native/backend/runtime quorum. Ten generated FIELD frontend files,
  the lightweight Runtime installer mode, static LLVM/WebView2 checks, isolated
  updater URL family, bilingual NSIS installer, updater signature, and checksum
  all pass.
- Cleanup: the EXE/checksum/signature trio was retained, then the exact FIELD
  Cargo target, ten untracked `frontend/field-dist` files, Tauri generation
  directories, and TypeScript incremental files were removed. The FIELD
  worktree is tracked-clean with only its dependency junctions.
