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

### A10 - Unified-core integration and current UI contract

- The Universal, SIM, LAB, and FIELD source surfaces were integrated into the
  single authoritative `main` worktree. Build-time edition selection now keeps
  Universal's mode switch while SIM, LAB, and FIELD are fixed to their product
  identity. FIELD retains its standalone lightweight entry and native command
  boundary.
- Static validation passed for frontend type checking, linting (one existing
  Fast Refresh warning only), 27 targeted SIM/FIELD tests, 13 shared Windows
  build-contract tests, all four Rust feature/profile combinations, and all
  four production frontend bundles.
- Failed UI attempt: the first integrated SIM headed check stopped on its first
  offline case before any EXE build. The current page correctly rendered the
  reviewed `Ready to install` state and `Install DroneDreamRuntime` action, but
  the inherited SIM visual script still required the superseded `0%` startup
  progress bar and `Download the Runtime` label.
- Lesson and repair: UI acceptance must assert the current product contract,
  not preserve historical copy or transitional widget values. The
  missing-Runtime case now requires the current install action, forbids the
  login action, and forbids a false `100%` readiness claim; it does not require
  the optional readiness container to be present, absent, or frozen at the old
  `0%` value. The ready case supplies an already-running Runtime and verifies a
  `100%` result plus the login action without allowing any background
  `start_runtime` call. This preserves the unified launcher's explicit
  start/repair safety contract instead of reviving an obsolete automatic-start
  behavior.
  Edition identity, absence of hardware authority, bilingual copy, responsive
  layout, light/dark rendering, canvas detail, and offline-only fixtures remain
  mandatory.
- Cleanup: the external Rust check target (2,945,335,732 bytes) and generated
  frontend/Tauri outputs were independently scoped and removed after their
  successful checks. The failed headed-check screenshot and receipt are kept
  only until this lesson is recorded, then the exact failed attempt directory
  is removed before the corrected run.
- Visual integration follow-up: the first light-scene run proved that the 3D
  scene and controls had switched correctly, but the inherited dark launcher
  header kept the sampled upper-white ratio at `0.54246`, below the reviewed
  `0.60` minimum. The missing high-specificity light-header rule was restored;
  the threshold was not weakened.
- Localization follow-up: after all 12 English cases and the first Chinese
  missing-Runtime case passed, the old SIM script still expected the historical
  Chinese sign-in wording ending in `工作区`. The unified interface deliberately
  uses `登录并进入调优平台`; the check now follows the canonical translation key
  while retaining an exact accessible-name assertion.
- Corrected result: all 24 SIM headed cases passed across English/Simplified
  Chinese, dark/light appearance, desktop/tablet/mobile viewports, and
  missing/ready Runtime states. The offline-only receipt SHA-256 is
  `189b82eccf78c1287a888742f97962291948a2ba65ec1270f219ffd924b92451`.
  The screenshots and receipt are reproducible diagnostics rather than product
  deliverables and are deleted after this compact evidence is recorded.
- FIELD integration failure: the first standalone FIELD layout preflight
  stopped before launching a browser because its production bundle lacked the
  shared Settings consumer marker. `FieldSettingsDialog` existed but had no
  reachable import from `FieldRoot`, so the optimizer correctly removed the
  orphaned popup. The repair adds the launcher settings control, shared dialog,
  backdrop-close behavior, and focus return, plus a unit assertion that the
  live dialog carries the `field-lightweight` consumer boundary.
- FIELD responsive follow-up: after the Settings surface became reachable, all
  desktop and tablet cases passed but the new second chrome action narrowed the
  390px mobile brand/action gap below the required 8px. FIELD now gives its
  compact lockup an explicit small-screen width bound and keeps both language
  and Settings controls visible; the overlap assertion remains unchanged.
- Corrected FIELD result: all 6 standalone headed cases passed for
  English/Simplified Chinese at desktop, tablet, and mobile sizes. The check
  verifies the shared Settings surface, edition colors, no hardware authority,
  no simulator terminology, a detailed nonblank 3D canvas, and the
  hover-to-starflight interaction. The receipt SHA-256 is
  `128031cac92ef474589fb277673ebb9fa747ff186e3b506e3b82d6d76a991c38`;
  its screenshots, receipt, and generated `field-dist` are removed after this
  evidence is recorded.

### A11 - Unified four-edition build entry and full-suite preflight

- A single PowerShell entry now maps Universal, SIM, LAB, and FIELD to their
  exact Tauri overlays, product names, native profiles, and public OAuth client
  identifiers. It requires one clean source commit, reuses one external Cargo
  target during the batch, preserves the canonical installer filenames, and
  copies only installers, checksums, updater signatures/manifests, and compact
  JSON receipts into the exact handoff root.
- Failure lesson: renaming a copied installer while retaining the build
  system's original checksum sidecar makes standard filename-aware checksum
  verification fail even when the bytes are identical. The wrapper therefore
  keeps each canonical NSIS filename and its matching sidecars together.
- Full-suite preflight lesson: Universal intentionally opens in its SIM
  workspace, whose sidebar has five SIM-safe entries. Four inherited UI tests
  still asserted the old all-surfaces sidebar and Universal lockup. The tests
  now assert the active workspace contract; the Runtime access test explicitly
  selects LAB before checking its broader read-only/course navigation.
- Contract lesson: integration changes to protected shared UI files require an
  explicit refresh of their SHA-256 entries in the Universal build profile.
  The hash gate remains strict; no assertion or validation threshold was
  weakened.
- Python test invocation lesson: the Worker package is not importable from the
  repository root without its declared local package path or editable install.
  Run its tests with the Worker and Backend package roots explicitly on
  `PYTHONPATH`; do not treat a collection-path error as a product-code failure.
- Cleanup: these preflight failures produced no installers or Cargo targets.
  Pytest/Vitest caches are disposable and are removed after the corrected
  suites pass; the sole Markdown file retains the reusable diagnosis.
- Backend timing lesson: the complete backend collection contains 2,169 tests
  across 127 files and legitimately exceeds a 15-minute monolithic command on
  this machine. A host-command timeout left its Python child alive, and a
  second attempt briefly competed with that stale process. Verify the exact
  command line, stop only the orphaned PID, then run deterministic sequential
  file batches; do not infer a test failure from an outer timeout.
- Corrected backend result: 126 files and 2,161 tests passed. The remaining
  eight tests are all in `test_technical_report_evidence_v10.py` and correctly
  fail closed because the current routing-evaluation fixture differs from its
  frozen evidence commit `ef00362927475b2fc411a4d82084bbbae8846582`.
  The technical report and its frozen evidence remain untouched by policy;
  this expected freeze-bound rejection is not an EXE product regression.
- Cleanup follow-up: the two timed-out backend processes were identified by
  exact command line and terminated without affecting other Python work. The
  batch diagnostic directory was deleted after its result was recorded. The
  corrected runs then removed 24 repository pytest/bytecode cache directories
  (13,609,381 bytes) and four exact system-temp pytest trees (about 692 MB),
  deleting test-created links themselves without following their targets.
- First unified EXE attempt: Universal compiled, bundled, signed, and passed
  its checksum/updater checks, but SIM stopped before compilation. The shared
  lower-level LLVM builder intentionally sets process-local `RUSTFLAGS`; a
  second invocation in the same wrapper process correctly rejected that value
  as an unexpected caller override.
- Repair: the four-edition wrapper now refuses caller-supplied Rust flags up
  front, snapshots every build environment variable it or the lower-level
  script mutates, and clears only the known lower-level Rust flag outputs
  immediately before each edition. The lower-level custom-flag safety gate is
  unchanged.
- Failed-attempt cleanup: the incomplete `a1` handoff, shared Cargo target
  (about 1.6 GB at failure), generated frontend output, Tauri generation, and
  staged LLVM loader were all verified absent after the wrapper's `finally`
  cleanup. The previously accepted historical Universal installer remains the
  fallback until a complete four-edition batch passes.
- Second unified EXE attempt: Universal, SIM, and LAB compiled, bundled,
  updater-signed, and passed their planner/checksum gates. FIELD also compiled
  and produced its signed NSIS installer, but the planner verifier failed only
  while deleting its copied `dronedream-runtime-probe.exe`: Windows briefly
  retained the just-exited executable and returned `Access denied`.
- Repair: the verifier now completes process-exit bookkeeping, waits after a
  timed-out kill, disposes the process object, and retries deletion for a
  bounded ten-second window. Every retry revalidates that the exact target is
  a non-reparse `DroneDream-Planner-Smoke-*` child of the system TEMP root; it
  never broadens the cleanup target or suppresses a persistent failure. The
  PowerShell parser and the shared Windows build-contract suite cover this
  lifecycle contract.
- Failed-attempt cleanup: the incomplete `a2` handoff, its external Cargo
  target, generated source outputs, planner process, and planner temp directory
  were all verified absent. The repository returned to a tracked-clean state
  before the next attempt, while the four historical fallback installers were
  retained.
- Third unified EXE attempt: Universal, SIM, and LAB again completed all build
  gates, and FIELD again compiled and bundled successfully. This time the FIELD
  planner probe reached its 90-second timeout. The verifier redirected both
  native output streams but waited for process exit before reading them, which
  permits a full pipe buffer to deadlock the child and parent.
- Repair: start asynchronous reads for stdout and stderr immediately after the
  probe starts, then wait for exit and collect both completed tasks. A timed-out
  process is killed and awaited before exact cleanup. This keeps diagnostic
  capture without allowing either redirected stream to block planner exit.
- Failed-attempt cleanup: the `a3` handoff, Cargo target, generated source
  outputs, and timed-out probe process were verified absent. A separate
  18,846,272-byte planner directory left by the earlier `a2` cleanup failure
  was identified by its exact TEMP child path, verified to contain no reparse
  points and have no running probe, then permanently removed. No current or
  historical accepted installer was deleted.
- Fourth unified EXE attempt: the asynchronous pipe fix was validated by
  Universal, SIM, and LAB, but FIELD still timed out. The remaining failure was
  therefore not process I/O: FIELD's intentionally reduced native entry rejects
  Runtime handoff commands, while the shared installer and build verifier were
  still trying to invoke the Runtime planner.
- Product-contract repair: FIELD is now compiled without the Runtime selection
  page and never advertises, seals, quiesces, or preserves Runtime installer
  metadata. Install/repair removes any such values written by an early FIELD
  candidate. Its build gate verifies the exact app-only clear command instead;
  Universal, SIM, and LAB retain the complete planner and durable Runtime
  quiesce contract. Static tests enforce both sides of this edition boundary.
- Failed-attempt cleanup: the entire `a4` handoff, Cargo target, generated
  source outputs, FIELD probe, and planner temp directory were verified absent
  before the FIELD-only repair build. No passed-but-incomplete A4 artifacts
  were retained as a release.
- Fifth EXE attempt (FIELD-only repair proof): FIELD rebuilt from clean commit
  `2ed1d062f3e9f057dbb584fa738134f9ea9eb1c1` and tree
  `d86e1390e2950ca288d974fdb592efe10fb5b1a2`. Its frontend, LLVM/Rust binary,
  NSIS installer, updater signature, checksum, update manifest, and app-only
  installer handoff gate all passed. The canonical installer is 6,191,817
  bytes; its receipt hash and checksum sidecar independently match, and the
  update manifest contains a non-empty FIELD signature.
- Successful-attempt cleanup: the dedicated external Cargo target and every
  generated source-tree path were absent after the wrapper completed. The
  small FIELD-only handoff is retained only until the succeeding complete
  four-edition batch is independently accepted; it is not a separate release
  or another source tree.
- Sixth EXE attempt (complete integrated batch): Universal, SIM, LAB, and
  FIELD all rebuilt from clean commit
  `224903c01ecaeb60b2b4ebfc5ebbba3d517d5413`. Each edition produced exactly
  five canonical delivery files, and every receipt bound the same source
  commit and tree. Independently recomputed installer hashes matched both the
  receipt and `.sha256` sidecar; all four updater manifests carried non-empty
  signatures. The installers were: Universal 12,455,655 bytes / SHA-256
  `9b76b222642de513d11ed07cd58b1a7b82fd6028bb5e2465a5c5568321ae32b4`;
  SIM 12,179,007 bytes / `5ba3aeba4a41b2c3a0fb4b68b14deb1d7f8c96fa6c9436a303d2a6c719bb853c`;
  LAB 12,522,906 bytes / `11d6d48e646b3e59bb4b33b92bf7404bf2b595fd245d9ed1a1d78de3f6acae48`;
  FIELD 6,197,030 bytes /
  `7b08f88d08a1338e60826933037f99b9fcb34090c1361c605af1f7cb601c896c`.
  The shared external Cargo target and all five generated source-tree paths
  were absent at completion.
- Installer UI validation lesson: the first FIELD UI run reached the correct
  visible welcome page but the verifier still expected the old generic
  `Welcome to DroneDream Setup` text. The verifier now accepts an explicit,
  newline-free Unicode display name while keeping the registry product name a
  separate strict identifier. The second FIELD run reached the correct app
  location page but showed that the old path-only auto-exit expected the next
  Runtime page; FIELD intentionally has no such page. A mutually exclusive
  `StopAfterLocationPage` verifier mode now validates the FIELD app-only flow
  without weakening the Universal/SIM/LAB path guard.
- Corrected installer UI result: all eight real NSIS flows passed serially
  (four editions, English and Simplified Chinese). Universal/SIM/LAB exercised
  the real path-validation-only exit; FIELD stopped at its verified app
  location boundary. Every pre-existing installation directory and edition
  registration was byte-for-byte unchanged after each run, no installer or
  app process remained, and the exact diagnostics file was removed. The two
  failed verifier runs also stopped before installation and left those states
  unchanged.
- Open cleanup item: the old installed executables predate the new Runtime
  quiesce recovery command, so they could not clear the authenticated marker
  left when the verifier deliberately terminated NSIS. Do not delete that
  marker by path. Build or retain an exact current native executable, invoke
  its supported recovery command, require exit zero and marker absence, then
  delete only the temporary build target.
