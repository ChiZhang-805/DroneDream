# DroneDream Desktop

This directory builds the `0.3.18` Windows development-preview installer and a
Tauri 2 shell around the existing React/Vite application
in `../frontend`. It does not copy or fork the business UI, and the normal web
commands under `frontend/` continue to work unchanged.

## Current scope

- A Windows desktop window that loads the existing Vite development server or
  its production `frontend/dist` output.
- A read-only `probe_system_prerequisites` Tauri command. It reports Windows
  version, registered WSL distributions, physical/available memory, fixed-disk
  free space, and display adapters as structured JSON.
- A `/desktop/setup` first-run page that renders the prerequisite report,
  dedicated-runtime status, component health, install plan, and live runtime
  installation progress. The packaged desktop app opens this page first; the
  normal web build still opens the dashboard.
- A fresh-interactive-install mode page with three choices: **Install all
  (recommended)**, **Custom runtime drive**, and **Desktop application only**.
  The first choice is selected by default when a suitable disk exists. The
  installer records one narrowly scoped, current-user handoff; after the app
  renders the confirmed plan, it atomically consumes that handoff and starts
  runtime setup without requiring a second install click.
- A fixed-disk selector that derives the isolated `X:\DroneDream` runtime path
  and recalculates the install plan without accepting arbitrary directories.
  The native default chooser prefers a safe writable non-system disk with NTFS
  and at least 52 GiB free, then falls back to the Windows system disk. This
  reserves 8 GiB for the download, 24 GiB for the installed runtime, and
  20 GiB of post-install host headroom.
- Read-only `probe_runtime_status` and `get_runtime_install_plan` commands. The
  target-drive probe rejects network/removable/non-NTFS locations and checks
  that enough free space exists before a runtime installation can be offered.
- A manifest-verified runtime installation workflow exposed through
  `start_runtime_install`, `get_runtime_install_progress`, and
  `cancel_runtime_install`. It downloads the fixed beta channel selected at
  build time in `frontend/.env.production`, verifies the detached Ed25519
  signature, streams and verifies split artifacts with resume support, imports
  only the dedicated `DroneDreamRuntime` distribution, and reports each stage
  to the setup page. A valid fresh-install handoff invokes the same workflow
  automatically; the page controls remain available for retry, continuation,
  cancellation, or repair. `start_runtime` and `repair_runtime` start or
  restart that exact managed distribution and re-run its identity and
  readiness checks.
- Branded application icons, a production CSP, and an enabled bilingual NSIS
  installer target.

## Fresh Windows install flow (closed beta)

The desktop program and simulation runtime are deliberately separate:

- The current-user NSIS package installs the desktop program to
  `%LOCALAPPDATA%\DroneDream` by default. Its ordinary directory page may be
  used to choose another desktop-program folder.
- `DroneDreamRuntime` is a separate signed WSL2 image. Its location is always
  the fixed safe path `X:\DroneDream` on the selected local fixed NTFS drive;
  custom mode selects only `X:`, never an arbitrary directory. Resumable
  download data is stored in the separately owned sibling
  `X:\DroneDream.download-cache`.
- The current signed beta rootfs is about **6.1 GB** (about 5.7 GiB). The
  planner reserves 8 GiB for download/staging, estimates 24 GiB installed,
  keeps 20 GiB of post-install headroom, and therefore requires at least
  **52 GiB** free before a fresh Runtime install.

On a fresh interactive installation, **Install all** is selected by default
and shows the recommended Runtime disk, download size, and storage requirement.
**Custom runtime drive** applies the same NTFS, fixed-disk, canonical-path, and
52-GiB checks to the chosen drive. **Desktop application only** installs no
Runtime and creates no automatic-download request. If no eligible drive is
available, the two Runtime choices are disabled and the installer safely falls
back to desktop-only.

After the user confirms the installer once, NSIS copies the desktop program
and writes a version-bound, current-user-protected Runtime choice. A successful
fresh install-all or custom-Runtime install launches DroneDream exactly once;
the ordinary finish-page Run callback is suppressed so it cannot open a second
copy. If Windows cannot start that process, the protected choice remains for
the next manual launch. The setup page first renders the exact confirmed target
and read-only plan, then automatically downloads, verifies, imports, starts,
and health-checks `DroneDreamRuntime`. The in-app Runtime button is not part of
the normal first-install path; it is retained for a safe retry,
post-cancellation continuation, or repair.

The desktop install itself is per-user and does not request elevation. If WSL2
must be enabled, Runtime setup may show a separate Windows UAC prompt for
`wsl --install --no-distribution`. When Windows requires a restart, the setup
records a restart continuation. Reopen DroneDream after reboot and it resumes
automatically without another Runtime-install click. Installer receipts are
version-bound and expire after 72 hours; an invalid or stale receipt fails
closed and leaves manual recovery available.

Automatic Runtime setup is intentionally limited to a **fresh interactive**
install. Upgrades, same-version reinstalls, passive installs, and silent
installs behave as desktop-application-only operations and never initiate a
Runtime download. A valid pending Runtime intent or reboot continuation blocks
replacement or uninstall until it is resumed or explicitly discarded. An
invalid or stale handoff also fails closed instead of being overwritten and
must be cleared through the desktop recovery path. If the owned
`DroneDreamRuntime` already exists, fresh install-all also recognizes it and
does not import a duplicate.

Before the native Runtime operation starts, the setup page can discard the
pending automatic request. After download/import has started, its normal
Cancel control performs a safe cancellation; authenticated resumable download
progress may be retained for a later retry. Upgrade, reinstall, and uninstall
are blocked while a Runtime install/start/repair operation is active rather
than replacing files underneath it.

After its fail-closed operation and handoff checks, uninstalling the desktop
program deliberately preserves the `DroneDreamRuntime` WSL distribution, its
selected `X:\DroneDream` data, and its download cache. Removing the Runtime is a
separate destructive action and is never implied by desktop uninstall.

When Runtime startup reaches the health-check stage but cannot become ready,
DroneDream captures bounded systemd, journal, WSL-network, and Windows-localhost
evidence before rolling back a distribution created by that failed attempt.
The validated report path is shown in the error dialog and lives under
`X:\DroneDream.download-cache\diagnostics`; it therefore survives rollback and
ordinary desktop uninstall together with the resumable download cache. Reports
are capped at 512 KiB each, ten files, and 5 MiB total, with credential-like
lines redacted. See `../docs/14-runtime-release.md` for the complete ownership
and retention contract.

The desktop installer and installer-driven runtime workflow consume the
separately built, smoke-tested, Ed25519-signed runtime manifest and split
rootfs assets whose hashes are covered by that manifest
from the desktop binary's compiled beta channel. The manual frontend flow pins
the same release in `frontend/.env.production`. If those assets are unavailable
or fail verification, installation stops without importing a distribution.
The runtime image, rather than the small NSIS package, supplies the FastAPI
backend, worker, PX4, and Gazebo. Neither install mode ever reuses, moves,
converts, terminates, or unregisters a user's existing Ubuntu distribution or
bundles personal files.

The Runtime's detached Ed25519 manifest signature authenticates the Runtime
payload; it is separate from Windows Authenticode. The preview NSIS installer
is still not Authenticode-signed. Windows may show a SmartScreen
warning, so it must not be advertised as a production release. The
NSIS package embeds Microsoft's official Evergreen WebView2 bootstrapper. It
verifies both registration and the real runtime executable; a stale registry
entry triggers a best-effort Microsoft repair/install attempt before DroneDream
files are copied. The application also asks the official WebView2 Loader API to
confirm a usable runtime before creating its first window, so a damaged shared
runtime produces a bilingual native error instead of a blank application window.
The bootstrapper still needs an internet connection if WebView2 must be installed
or repaired.

The NSIS package installs project and runtime notices under `licenses/`,
including the DroneDream MIT license, the runtime third-party component index,
and the exact Valkey `COPYING` text. Runtime GitHub Releases publish the same
materials beside the manifest-authenticated rootfs parts.

The probes use read-only CIM, current-user registry, fixed WSL commands, and a
bounded localhost HTTP readiness check. Native commands can be called from the
desktop webview without adding Tauri packages to the shared web frontend:

```js
const report = await window.__TAURI__.core.invoke(
  "probe_system_prerequisites",
);
const runtime = await window.__TAURI__.core.invoke(
  "probe_runtime_status",
);
const plan = await window.__TAURI__.core.invoke(
  "get_runtime_install_plan",
  { targetRoot: "E:\\DroneDream" },
);
const install = await window.__TAURI__.core.invoke(
  "start_runtime_install",
  {
    request: {
      targetRoot: "E:\\DroneDream",
      releaseManifestUrl:
        "https://github.com/ChiZhang-805/DroneDream/releases/download/runtime-v0.1.0-beta.1/runtime-release.json",
    },
  },
);
const installerChoice = await window.__TAURI__.core.invoke(
  "get_installer_runtime_intent",
);
const automaticInstall = await window.__TAURI__.core.invoke(
  "auto_start_installer_runtime",
);
```

The global API is available only inside Tauri. Browser builds remain ordinary
web builds, and their runtime-setup view is read-only: it never invokes native
probe, install, cancel, start, or repair commands. Omitting `targetRoot` from an
install-plan request asks the native probe to choose the fixed NTFS drive using
the non-system-first safety policy above. The desktop setup page adopts that
recommendation, then sends an explicit `X:\DroneDream` path after the user
chooses a disk. The release URL is not user-entered; production builds take it
from `VITE_RUNTIME_RELEASE_MANIFEST_URL` in `frontend/.env.production` and reject
missing, credential-bearing, or non-HTTPS values.

## Developer prerequisites (Windows)

- Node.js and npm
- Rust 1.97.0 MSVC (`rustup` / `cargo`)
- Microsoft C++ Build Tools with **Desktop development with C++**
- Microsoft Edge WebView2 runtime (normally already present on Windows 10/11)

See the official Tauri 2 prerequisites:
<https://v2.tauri.app/start/prerequisites/>.

## Commands

```powershell
cd desktop
npm ci
npm run check:frontend
npm run dev
npm run build
npm run build:llvm
```

`npm run dev` starts the existing frontend dev server automatically. `npm run
build` first runs the existing frontend build and then compiles the desktop
executable and `DroneDream_<version>_x64-setup.exe` NSIS installer.

`npm run build:llvm` is the no-administrator fallback for Windows development
machines without a usable MSVC installation. It expects the official Rust
`1.97.0-x86_64-pc-windows-gnullvm` toolchain plus the portable LLVM-MinGW UCRT
package available through WinGet. The script also discovers Rust in the
standard per-user `.cargo\bin` location when a newly installed toolchain is not
yet on the terminal's `PATH`. Pinning the fallback to Rust 1.97.0 keeps it
aligned with GitHub Actions instead of silently moving with the `stable`
channel. It statically links the LLVM runtime, stages the locked WebView2 loader
for NSIS, and inspects both PE import tables so the installer cannot accidentally
depend on toolchain DLLs from the developer's machine. GitHub Actions and public
releases continue to use the standard MSVC toolchain. The standard installer is
written below `src-tauri/target/release/bundle/nsis`; the LLVM fallback uses
`src-tauri/target/x86_64-pc-windows-gnullvm/release/bundle/nsis`.

The LLVM fallback also verifies the pinned NSIS template and the generated
WebView2 health gate, then rewrites the SHA-256 file for the exact configured
desktop version. Pull requests and manual desktop workflow runs retain the
verified installer as a 14-day Actions artifact. Pushing an immutable
`desktop-v<version>` tag whose version exactly matches the Tauri, npm, and Cargo
metadata publishes those same two verified files as an unsigned GitHub
prerelease; an existing release is never overwritten.

For this 16 GB development machine, keep `CARGO_BUILD_JOBS=4` and never compile
PX4 while a Gazebo GUI simulation is running. The initial beta runtime target is
a single worker and a single PX4/Gazebo trial.

## Runtime distribution contract

The beta runtime is a dedicated WSL2 distribution named
`DroneDreamRuntime`. Release automation, not the end user's computer, installs
and compiles Ubuntu, Python, PX4, Gazebo, backend, and worker dependencies.
Each image must contain `/opt/dronedream/runtime-manifest.json` with at least:

```json
{
  "schemaVersion": 1,
  "version": "0.1.0",
  "runtimeId": "123e4567-e89b-12d3-a456-426614174000",
  "components": {
    "backend": "0.1.0",
    "px4": "pinned-git-sha",
    "gazebo": "pinned-version"
  },
  "smokeTests": {
    "px4Sitl": true,
    "gazebo": true,
    "parameterReadback": true
  }
}
```

The desktop app rejects manifests that omit the backend, PX4, or Gazebo version
or the three successful release-time smoke tests. The distribution must be
registered as WSL version 2 and launch the backend with
`DRONEDREAM_RUNTIME_ID` set to the manifest's `runtimeId`. Runtime readiness
requires `/health/ready` to return both that identity as `data.runtime_id` and
the backend version declared by the manifest. This prevents a same-version
development server on port 8000 from being mistaken for the packaged runtime.
A packaged runtime must also configure `DRONEDREAM_PX4_EXECUTABLE` and
`DRONEDREAM_GAZEBO_EXECUTABLE` with executable files. Once a runtime identity
is configured, `/health/ready` requires a live worker heartbeat through
`REDIS_URL` even if ordinary web/development mode leaves worker heartbeats
optional. Missing worker, PX4, or Gazebo readiness returns HTTP 503.
The installer verifies the signed release manifest, every split-part SHA-256,
and the reassembled archive SHA-256. It then requires the signed release
`buildId`, the image's inner `runtimeId`, and `/health/ready`'s `runtime_id` to
match before recording the install as healthy.

The Windows target directory is checked again before every import. An
existing non-empty directory, file, junction, or symbolic link is blocked.
Only DroneDream installation or repair tooling may create the reserved
`.dronedream-runtime-root.json` host ownership receipt. The receipt records the
exact runtime name, signed build identity, version, and installation time;
start and repair refuse an unowned or mismatched WSL registration. Users should
never create or edit that receipt by hand.

Downloads use the strictly named same-drive sibling
`X:\DroneDream.download-cache`, not a child of `X:\DroneDream`. This keeps the
WSL import target empty across retries and application restarts. The cache has
its own ownership marker and accepts cleanup entries only below its
`artifacts` directory; absolute paths, parent traversal, duplicate entries,
links, junctions, reparse points, directories, and unmarked roots are rejected
before any deletion. Split parts are individually authenticated and appended
to a staged archive; Range requests resume from the last safe byte boundary.
Cancel and recoverable failures preserve verified progress. A successful import
removes only digest-verified temporary artifacts; the small ownership marker
and cache directory may remain for a later repair or update.

The installer-driven importer accepts only canonical signed release metadata
from its compiled trusted Ed25519 keyring, HTTPS artifact URLs, contiguous
parts smaller than 2 GiB, and a release that declares successful PX4 SITL,
Gazebo, and parameter-readback smoke tests. It imports the archive with WSL2
into the installer-confirmed fixed NTFS `X:\DroneDream` root, starts the managed
services, and performs the identity/readiness checks above. If installation
fails after this attempt creates `DroneDreamRuntime`, rollback may unregister
only that exact new distribution; pre-existing distributions are left
untouched.

The command surface and UI are intended for a closed-beta package. Contract,
unit, frontend, and installer-build checks do not by themselves prove the full
customer-machine journey with a 6.1-GB download, UAC/reboot, WSL import, and
live PX4/Gazebo workload. Run that end-to-end matrix on clean supported Windows
machines before claiming public production readiness, and keep the unsigned
SmartScreen warning visible in tester instructions.
