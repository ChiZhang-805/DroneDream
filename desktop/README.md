# DroneDream Desktop

This directory is a Tauri 2 shell around the existing React/Vite application
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
- A fixed-disk selector that derives the isolated `X:\DroneDream` runtime path
  and recalculates the install plan without accepting arbitrary directories.
  The native default chooser prefers a safe writable non-system disk with NTFS
  and at least 52 GiB free, then falls back to the Windows system disk. This
  reserves 8 GiB for the download, 24 GiB for the installed runtime, and
  20 GiB of post-install host headroom.
- Read-only `probe_runtime_status` and `get_runtime_install_plan` commands. The
  target-drive probe rejects network/removable/non-NTFS locations and checks
  that enough free space exists before a runtime installation can be offered.
- A signed runtime installation workflow exposed through
  `start_runtime_install`, `get_runtime_install_progress`, and
  `cancel_runtime_install`. It downloads the fixed beta channel selected at
  build time in `frontend/.env.production`, verifies the detached Ed25519
  signature, streams and verifies split artifacts with resume support, imports
  only the dedicated `DroneDreamRuntime` distribution, and reports each stage
  to the setup page. `start_runtime` and `repair_runtime` start or restart that
  exact managed distribution and re-run its identity and readiness checks.
- Branded application icons, a production CSP, and an enabled bilingual NSIS
  installer target.

The desktop installer and first-run runtime workflow consume the separately
built, smoke-tested, signed runtime manifest and split rootfs assets at the
exact release URL configured in `frontend/.env.production`. If those assets
are unavailable or fail verification, installation stops without importing a
distribution. The runtime image, rather than the small NSIS package, supplies
the FastAPI backend, worker, PX4, and Gazebo. The installer never reuses,
moves, converts, terminates, or unregisters a user's Ubuntu distribution or
bundles personal files.

The preview installer is unsigned. Windows may show a SmartScreen warning, so
it must not be advertised as a production release. The NSIS application install
uses the current user. If WSL2 is not ready, first-run setup separately asks for
Windows administrator approval to run `wsl --install --no-distribution`; this
enables the platform without installing Ubuntu, and setup records a
`waitingForRestart` state when Windows cannot continue until after reboot. If
Microsoft Edge WebView2 is missing, NSIS downloads the official WebView2
bootstrapper and therefore needs an internet connection for that prerequisite.

The NSIS package installs project and runtime notices under `licenses/`,
including the DroneDream MIT license, the runtime third-party component index,
and the exact Valkey `COPYING` text. Runtime GitHub Releases publish the same
materials beside the signed rootfs parts.

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

The first-run installer accepts only canonical signed release metadata from its
compiled trusted Ed25519 keyring, HTTPS artifact URLs, contiguous parts smaller
than 2 GiB, and a release that declares successful PX4 SITL, Gazebo, and
parameter-readback smoke tests. It imports the archive with WSL2 into the
user-selected fixed NTFS `X:\DroneDream` root, starts the managed services, and
performs the identity/readiness checks above. If installation fails after this
attempt creates `DroneDreamRuntime`, rollback may unregister only that exact new
distribution; pre-existing distributions are left untouched.

The command surface and UI are ready for a closed-beta package. Publish the
matching signed runtime assets at the configured beta URL before distributing
an installer, and keep the unsigned SmartScreen warning visible in tester
instructions.
