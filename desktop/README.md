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
- Read-only `probe_runtime_status` and `get_runtime_install_plan` commands. The
  target-drive probe rejects network/removable/non-NTFS locations and checks
  that enough free space exists before a runtime installation can be offered.
- Branded application icons, a production CSP, and an enabled bilingual NSIS
  installer target.

The current installer contains the Windows UI only. It deliberately does not
reuse the developer's Ubuntu distribution or bundle personal files. Public
simulation builds will download a separately versioned and signed
`DroneDreamRuntime` WSL image during first-run setup.

The probes use read-only CIM, current-user registry, fixed WSL commands, and a
localhost TCP readiness check. From the desktop webview they can be called
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
);
```

The global API is available only inside Tauri. Browser builds remain ordinary
web builds, so UI code must guard access with `window.__TAURI__` when the probe
is wired into a page later.

## Developer prerequisites (Windows)

- Node.js and npm
- Rust stable MSVC (`rustup` / `cargo`)
- Microsoft C++ Build Tools with **Desktop development with C++**
- Microsoft Edge WebView2 runtime (normally already present on Windows 10/11)

See the official Tauri 2 prerequisites:
<https://v2.tauri.app/start/prerequisites/>.

## Commands

```powershell
cd desktop
npm install
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
`stable-x86_64-pc-windows-gnullvm` toolchain plus the portable LLVM-MinGW UCRT
package available through WinGet. GitHub Actions and public releases continue
to use the standard MSVC toolchain.

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
  "runtimeId": "release-generated-uuid",
  "components": {
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

The desktop app rejects manifests that omit the required component versions or
the three successful release-time smoke tests. A future signed install receipt
will additionally bind `runtimeId` to the downloaded image hash.

The online installer will download the image with resume support, verify its
published SHA-256/signature, import it to a user-selected fixed NTFS drive, and
run backend, worker, PX4, Gazebo, and parameter-readback smoke tests. Until a
signed runtime artifact is published, the setup page remains diagnostic and
does not expose a destructive install action.
