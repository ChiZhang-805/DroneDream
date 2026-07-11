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
  dedicated-runtime status, component health, and a non-destructive install
  plan in both browser and desktop builds. The packaged desktop app opens this
  page first; the normal web build still opens the dashboard.
- A fixed-disk selector that derives the isolated `X:\DroneDream` runtime path
  and recalculates the install plan without accepting arbitrary directories.
  The native default chooser prefers a safe writable non-system disk with NTFS
  and at least 52 GiB free, then falls back to the Windows system disk. This
  reserves 8 GiB for the download, 24 GiB for the installed runtime, and
  20 GiB of post-install host headroom.
- Read-only `probe_runtime_status` and `get_runtime_install_plan` commands. The
  target-drive probe rejects network/removable/non-NTFS locations and checks
  that enough free space exists before a runtime installation can be offered.
- Branded application icons, a production CSP, and an enabled bilingual NSIS
  installer target.

The current installer contains the Windows UI only. It does not start the
FastAPI backend, a worker, PX4, or Gazebo, and therefore cannot run a tuning
job by itself yet. It deliberately does not reuse the developer's Ubuntu
distribution or bundle personal files. Public simulation builds will download
a separately versioned and signed `DroneDreamRuntime` WSL image during
first-run setup.

The preview installer is unsigned. Windows may show a SmartScreen warning, so
it must not be advertised as a production release. It uses a current-user NSIS
installation and does not request administrator access. If Microsoft Edge
WebView2 is missing, the installer downloads the official WebView2 bootstrapper
and therefore needs an internet connection for that prerequisite.

The probes use read-only CIM, current-user registry, fixed WSL commands, and a
bounded localhost HTTP readiness check. From the desktop webview they can be called
without adding Tauri packages to the shared web frontend:

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
```

The global API is available only inside Tauri. Browser builds remain ordinary
web builds, so UI code must guard access with `window.__TAURI__` before calling
these commands. Omitting `targetRoot` asks the native probe to choose the fixed
NTFS drive using the non-system-first safety policy above. The setup page omits
`targetRoot` on its first request and adopts the native recommendation; it sends
an explicit path only after the user changes the disk selector.

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
PX4 while a Gazebo GUI simulation is running. The future runtime defaults to a
single worker and a single PX4/Gazebo trial.

## Runtime distribution contract

The public runtime is a dedicated WSL2 distribution named
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
A future signed install receipt will additionally bind `runtimeId` to the
downloaded image hash.

The Windows target directory is also checked before any future import. An
existing non-empty directory, file, junction, or symbolic link is blocked.
Only DroneDream installation or repair tooling may create the reserved
`.dronedream-runtime-root.json` ownership marker; users should never create
that marker by hand.

Future downloads use the strictly named same-drive sibling
`X:\DroneDream.download-cache`, not a child of `X:\DroneDream`. This keeps the
WSL import target empty across retries and application restarts. The cache has
its own ownership marker and accepts cleanup entries only below its
`artifacts` directory; absolute paths, parent traversal, duplicate entries,
links, junctions, reparse points, directories, and unmarked roots are rejected
before any deletion. A successful import removes only artifacts already marked
as digest-verified. A failed import removes nothing, preserving verified chunks
and partial data for resume. The small marker and cache directory may remain
for a later repair or update.

The future first-run runtime installer will download the image with resume
support, verify its published SHA-256/signature, import it to a user-selected
fixed NTFS drive, and run backend, worker, PX4, Gazebo, and parameter-readback
smoke tests. The cache lifecycle primitives are implemented and tested, but are
intentionally not registered as a Tauri command until a real signed artifact
manifest and release URL exist. Until then, the setup page remains diagnostic
and does not expose a destructive install action.
