# DroneDream Quality Audit — 2026-07-16

This report records the repository-wide audit performed before publishing the
`0.3.18` development preview. It distinguishes what was verified locally from
what still requires a clean customer machine, a real PX4/Gazebo host, or a
production signing identity. Passing this audit does not turn an unsigned
development preview into a production-certified flight-control product.

## Outcome

- The application, public website, desktop shell, Runtime installer, backend,
  worker, optimization engines, simulation adapters, documentation, and release
  metadata were reviewed as one product rather than as isolated modules.
- All locally executable automated suites and static checks passed after the
  repairs listed below.
- The Windows installer and public download site were rebuilt from the audited
  source. Their version, filename, byte length, and SHA-256 digest agree.
- The five-step experiment workflow, persisted draft state, API schemas,
  optimizer identifiers, parameter catalog, Runtime stages, and release
  metadata are consistent across frontend, backend, desktop, and documentation.
- No known silent fallback remains for an unsupported advanced physical effect:
  the real runner either returns validated application evidence or fails closed.

## Audit scope

The review covered:

- React/TypeScript application UI, bilingual copy, responsive layouts,
  accessibility contracts, wizard gating, 2D/3D track editing, the ECE 498 BH
  course page, and the Three.js public website;
- FastAPI routes, authentication, persistence, migrations, artifact handling,
  orchestration, reports, worker leases, cancellation, and cleanup;
- all seven accuracy-first experimental optimizers and their common search-space,
  feasibility, budget, scenario, holdout, and recommendation contracts;
- PX4 parameter validation, real CLI protocol, process containment, offboard
  execution, telemetry and artifact schemas, Gazebo markers, and scenario-effect
  evidence;
- Tauri/Rust commands, WebView2 bootstrap, WSL2 prerequisite probing, resumable
  Runtime delivery, manifest verification, keepalive behavior, NSIS localization,
  install/uninstall paths, and log diagnostics;
- Docker, Nginx, CI, static-site release and rollback scripts, security headers,
  dependency locks, manuals, and cross-document links.

Generated dependencies, build caches, binary outputs, and third-party vendored
code were not reviewed line by line. They were instead checked through lockfile
audits, reproducible builds, checksums, license files, and generated-artifact
verification.

## Repairs made during the audit

### Product workflow and interface

- Consolidated the experiment builder into a gated five-step workflow and
  removed the obsolete batch-oriented desktop UI while retaining compatible
  backend batch endpoints for existing clients.
- Persisted `completed_steps`, including safe migration of older five-step and
  legacy seven-step drafts. Returning to an earlier step now preserves valid
  later work without falsely marking an unfinished step complete.
- Corrected the generic OpenAI-compatible LLM configuration contract so
  provider-neutral endpoints are accepted consistently by frontend and backend.
- Completed Chinese/English isolation and parity checks and removed stale wizard
  copy.
- Added adaptive Three.js rendering: the scene pauses off-screen, raises frame
  rate during interaction, lowers it while idle, and dynamically adjusts internal
  resolution without removing the drone, stars, lighting, or starflight effect.

### Backend and optimization

- Hardened schema validation, authentication, secret redaction, artifact paths,
  storage cleanup, migrations, worker presence, renewable leases, cancellation,
  and fencing against stale workers.
- Verified common-random-number scenario matrices, search/holdout separation,
  constraint handling, multi-objective/Pareto scoring, trial budgets, failure
  accounting, early stopping, and reproducibility manifests.
- Added and tested constrained MOBO, multi-fidelity MOBO, TuRBO, SAASBO,
  surrogate-assisted CMA-ES, BIPOP-CMA-ES, and the adaptive optimizer portfolio.
- Normalized import order and formatting across application code, migrations,
  scripts, and tests so the same quality gate runs locally and in CI.

### PX4/Gazebo, Runtime, and desktop delivery

- Enforced parameter safe bounds and requested/before/applied readback evidence.
- Added validated static box/cylinder injection. Wind/gust, sensor and GPS
  degradation, battery, payload, actuator delay, and other physical effects are
  accepted only when a launcher proves that it applied them.
- Improved timeout diagnostics by separating Runtime-internal health from Windows
  localhost reachability and exporting service/API logs before rollback.
- Sanitized progress/error text at the Rust/JavaScript boundary and made startup
  probing tolerate a slow but healthy first boot instead of showing a premature
  fatal error.
- Added resumable downloads, strict manifest/component validation, path guards,
  Runtime keepalive, cleanup limits, localized installer pages, WebView2
  bootstrap, and deterministic release checks.

### Repository, deployment, and documentation

- Added a unified quality-gate workflow, repository hygiene checker, security
  policy, contribution guide, lockfile vulnerability scans, container build
  checks, and deployment safety checks.
- Hardened the static-site release archive against traversal, link/device members,
  duplicate entries, excessive expansion, concurrent deploys, broken candidates,
  invalid Nginx configuration, and partial activation. Failed deployments roll
  back the symlink and DroneDream-specific virtual host.
- Updated manuals and architecture, API, operations, Runtime, optimizer, PX4,
  parameter-catalog, phase-status, and harness-engineering documentation to the
  implemented five-step product and explicit capability boundaries.

## Verification matrix

| Area | Verification | Result |
| --- | --- | --- |
| Backend | Pytest unit/integration/API/migration suite | 731 passed |
| Backend | Ruff lint/imports/format, Bandit, mypy, compileall | Passed |
| Frontend | Vitest component/contract/interaction suite | 243 passed |
| Frontend | ESLint, TypeScript, app build, public-site build, i18n/a11y audits | Passed |
| Simulator scripts | Unit and protocol tests | 151 passed |
| Runtime | Contract and release tests | 34 passed, 4 POSIX-only checks skipped on Windows |
| Runtime shell | Bash syntax via the existing Ubuntu-22.04 WSL distro (read-only checks; no distro state changed) | 15 scripts passed |
| Desktop | Rust tests | 96 passed, 1 real-installed-Runtime test intentionally ignored |
| Desktop | Clippy, NSIS template/version checks, LLVM Windows release build | Passed |
| Dependencies | npm audit, Python lock audit, cargo audit | No known vulnerabilities |
| Documents/repository | JSON parsing, Markdown links, UTF-8/control characters, hygiene, diff check | Passed |
| Release site | 14-file integrity manifest and metadata/artifact checksum reconciliation | Passed |

`cargo audit` also reports 17 allowed maintenance/unsoundness warnings from the
GTK3/glib Linux dependency path. DroneDream's distributed desktop target is the
Windows Tauri build and does not ship that GTK path, but the warnings remain
documented rather than being hidden.

## Audited Windows artifact

- File: `DroneDream_0.3.18_x64-setup.exe`
- Size: `5,376,012` bytes (`5.13 MiB`)
- SHA-256: `40ca8deb6ea6f0f24e6de55000b641c9a69d90946bcde3173dd25429f5fdb1b5`
- Local build path:
  `desktop/src-tauri/target/x86_64-pc-windows-gnullvm/release/bundle/nsis/`
- Public-site staged path: `frontend/site-dist/downloads/`
- Signature status: **not Authenticode-signed**

The Runtime payload has its own Ed25519-signed manifest and per-part SHA-256
verification. That protects payload integrity but does not replace Windows
Authenticode publisher identity for the installer; SmartScreen may therefore
still warn users.

## Public-site deployment verification

The audited static release was atomically activated at
`http://47.93.180.216/` as server release
`0.3.18-20260716T065253Z`. The final pre-deployment Nginx/vhost rollback
backup is stored on the server at
`/root/dronedream-backups/20260716T054316Z`; the earlier audit-stage backup at
`/root/dronedream-backups/20260716T044858Z` was also retained.

Deployment exposed and repaired two server-compatibility defects before the
release was allowed to go live:

- Alibaba Cloud's Python 3.6 cannot call `date.fromisoformat`; release-date
  validation now uses a Python-3.6-compatible strict calendar-date check.
- Nginx reload can briefly leave an old worker serving the previous headers;
  the security-header gate now retries for a bounded interval instead of
  accepting a false negative or weakening the required headers.

After activation, an external probe verified:

- homepage, metadata, hashed JavaScript asset, checksum, and installer return
  HTTP 200 with the intended content types and cache policies;
- CSP, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, and
  `Permissions-Policy` are present;
- a fresh public download is exactly `5,376,012` bytes and hashes to
  `40ca8deb6ea6f0f24e6de55000b641c9a69d90946bcde3173dd25429f5fdb1b5`;
- Chinese desktop and English mobile pages render without console/page errors,
  clipping, overlap, or a missing Three.js scene.

The server still uses a bare IPv4 address over HTTP. A domain and HTTPS/TLS are
required before treating the website as a polished public production endpoint.

## Explicit acceptance boundaries

The following claims are deliberately not made by this report:

1. **No clean-PC certification yet.** The full install, restart, resumable
   Runtime download/import, first launch, repair, upgrade, and uninstall journey
   must still be repeated on clean Windows 10 and Windows 11 machines.
2. **No final real-flight/SITL certification yet.** A pinned released Runtime
   must run write/readback, arm, takeoff, each representative track, land,
   telemetry, artifact, failure, and recovery tests against the selected PX4 and
   Gazebo versions.
3. **Advanced effects are not all physically implemented.** Static obstacles
   are supported by the bundled runner. Wind/gust, sensor/GPS degradation,
   battery, payload, and actuator effects require compatible Gazebo/PX4 plugins
   or launcher hooks plus returned evidence; otherwise execution is rejected.
4. **The installer is unsigned.** Production distribution should use an
   Authenticode certificate and CI-held signing credentials before broad public
   promotion.
5. **Container images were not built on this Windows host.** Docker and Nginx
   image builds are enforced in CI, but Docker was unavailable for an additional
   local build during this audit.
6. **Capacity is not inferred from unit tests.** Real parallelism remains bounded
   by one real PX4/Gazebo trial per host runner. Worker count, CPU/RAM, queue
   limits, storage retention, and regional deployment cells require load tests.

## Release decision

`0.3.18` is suitable for a clearly labelled **development preview / closed
beta** and its public static-site download has passed the metadata, checksum,
header, rendering, and full-download probes above. It is not yet suitable to be
described as a signed production release or a validated replacement for
engineering review and real-vehicle safety testing.
