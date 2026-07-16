# DroneDreamRuntime manifest-signing and release pipeline

The detached Ed25519 signature in this document authenticates the Runtime
manifest and payload parts. It is not Windows Authenticode signing and does not
establish a Windows publisher identity for the NSIS executable. The current
`0.3.18` preview installer remains unsigned and can trigger SmartScreen.

The Windows installer downloads a dedicated WSL2 distribution; it never
moves, upgrades, or unregisters an existing Ubuntu distribution. A user may
choose any suitable fixed NTFS drive. `X:\DroneDream` in the signed manifest
is a drive-letter placeholder, not a hard-coded installation path; on the
current development machine the desktop planner may recommend
`E:\DroneDream`.

This document covers the release assets consumed by the installer-driven,
one-confirmation Windows flow. The manifest embedded inside the rootfs remains
the source/component/smoke record described in `runtime/README.md`.

## Windows installer integration

The NSIS executable remains small because it ships the desktop application,
not the PX4/Gazebo rootfs. A fresh interactive install offers **Install all
(recommended)**, **Custom runtime drive**, and **Desktop application only**.
The first two choices show and validate the target before the user confirms;
the third never creates a Runtime download request. The desktop application
defaults to `%LOCALAPPDATA%\DroneDream`, while the Runtime is isolated at the
fixed `X:\DroneDream` path and uses `X:\DroneDream.download-cache` for resumable
staging.

The current beta artifact recorded by the release fixture is 6,116,882,432
bytes (about **6.1 GB**, or 5.7 GiB). The Windows planner reserves 8 GiB for
download/staging and enforces at least **52 GiB** free for the complete
8-GiB-download, 24-GiB-installed, and 20-GiB-headroom policy. Manifest byte
counts remain authoritative; user-facing rounded sizes are informational.

After the desktop files are installed and DroneDream opens, the setup UI
renders the confirmed plan and automatically consumes the protected installer
handoff. It then downloads and authenticates this separate release, imports
only `DroneDreamRuntime`, starts it, and performs readiness checks. If WSL2
enablement needs administrator rights, Windows may show a separate UAC prompt.
If Windows then requires a reboot, reopening DroneDream resumes the protected
continuation automatically.

Only fresh interactive installs can create that automatic Runtime request.
Upgrades, reinstalls, passive installs, and silent installs are treated as
desktop-application-only operations and never start a Runtime download. A
valid pending Runtime intent or reboot continuation blocks replacement or
uninstall until it is resumed or explicitly discarded. Invalid or stale
handoffs also fail closed and require the desktop recovery/discard path rather
than being overwritten. Before work starts, the setup page can discard a
pending request; an active operation uses the Runtime installer's safe Cancel
path. Desktop uninstall removes neither the dedicated WSL
distribution nor its `X:\DroneDream` root/cache. It also never modifies or
reuses an existing Ubuntu distribution.

This behavior does not remove the current release boundary: the desktop NSIS
installer is unsigned and can trigger Windows SmartScreen. Treat it as a
closed-beta package until code signing and the full clean-machine journey are
verified.

## Runtime failure diagnostics and retention

If the imported distribution starts but does not become ready, the desktop
installer distinguishes three outcomes instead of reporting every timeout as
the same failure: a Runtime-internal service failure, a healthy Runtime that
Windows cannot reach through localhost, or an indeterminate health result.
Before unregistering a distribution created by that failed attempt, it captures
a bounded snapshot of the managed systemd units, their recent journals,
listening sockets, WSL networking, and the Runtime-internal readiness response.

The report is written as an ordinary file below the marker-owned sibling cache:
`X:\DroneDream.download-cache\diagnostics\runtime-health-<timestamp>-<id>.log`.
It is never written below `%TEMP%`, the desktop-program directory, or the WSL
import target. The writer revalidates the cache marker, rejects links and
reparse points, requires the diagnostics directory and report to resolve
directly below that cache, creates a unique file without overwriting an existing
report, removes control characters, redacts credential-like lines, and caps the
result at 512 KiB. Rotation retains at most ten reports and 5 MiB in total,
while failing closed on link-like or otherwise unsafe matching entries. The UI
receives only this already-validated local path; it does not turn it into a URL
or execute it.

Failed-import rollback deliberately preserves the report and authenticated
download data so a retry does not destroy its own evidence. Ordinary desktop
uninstall also preserves `DroneDreamRuntime`, `X:\DroneDream`, the sibling
download cache, and these reports. The NSIS **delete application data** choice
is scoped to the desktop bundle's `%APPDATA%`/`%LOCALAPPDATA%` state and does not
claim ownership of Runtime storage. Cache removal remains a separate,
explicitly destructive maintenance operation.

## Published assets

Each immutable beta GitHub Release contains only these files:

- `runtime-release.json`: canonical UTF-8 release manifest;
- `runtime-release.json.sig`: detached Ed25519 signature envelope;
- `smoke-report.json`: the real PX4/Gazebo smoke evidence bound to the
  rootfs build ID;
- `DroneDreamRuntime-<version>-amd64.tar.partNNNN`: ordered rootfs pieces;
- `DroneDream-LICENSE.txt`, `THIRD_PARTY_NOTICES.md`, and
  `Valkey-COPYING.txt`: project and principal third-party notices distributed
  alongside the binary runtime.

The whole rootfs tar is not uploaded separately. GitHub Release assets have a
2 GiB per-file ceiling, so the release tool defaults to 1900 MiB and rejects
every part size greater than or equal to 2 GiB. The installer downloads with
resume support, verifies each part, verifies the complete stream, and then
reassembles the original uncompressed tar. `compression` is deliberately
`none` in schema version 1, so the verified tar can be passed directly to:

```powershell
wsl.exe --import DroneDreamRuntime "<chosen-directory>" "<verified-rootfs.tar>" --version 2
```

The installer obtains the signature by appending `.sig` to the manifest URL.
For example:

```text
https://github.com/ChiZhang-805/DroneDream/releases/download/<tag>/runtime-release.json
https://github.com/ChiZhang-805/DroneDream/releases/download/<tag>/runtime-release.json.sig
```

Every part and smoke-report URL in the manifest must be HTTPS, must not contain
credentials, query strings, or fragments, and must end in the recorded safe
filename.

## Trust model

`runtime/release-public-keys.json` is compiled into the Windows installer. It
contains public keys only. A key ID is `ed25519:` followed by the full SHA-256
of the raw 32-byte public key. The first beta trust anchor is
`ed25519:7839a33eb8451e26c0e03ec65857e0caef7af8df70e9ddde3430a681b3f0d8c1`.
Its private counterpart is stored outside the repository and configured as the
`DRONEDREAM_RUNTIME_ED25519_PRIVATE_KEY` GitHub secret. An absent or unknown
key still fails closed.

Do not generate another key for routine releases. For a new fork or a planned
rotation, the following command creates a new private file without overwriting
an existing key and never prints private key material:

```powershell
$privateKey = Join-Path $HOME ".dronedream\runtime-release-ed25519.key"
New-Item -ItemType Directory -Force (Split-Path $privateKey) | Out-Null
python runtime/tools/runtime_release.py keygen `
  --private-key-output $privateKey `
  --public-key-output runtime/release-public-keys.generated.json
Get-Content -Raw $privateKey |
  gh secret set DRONEDREAM_RUNTIME_ED25519_PRIVATE_KEY
```

Review the generated public JSON and add its public entry to
`runtime/release-public-keys.json`; never replace a still-supported key until
installers trusting the new key are available. Commit only public material.
Keep the private file outside the repository and restrict it to the current
user. The GitHub workflow receives the private key only through the encrypted
secret; it neither writes nor prints it.

For rotation, add the new public entry as `active` and keep the previous entry
`active` during the overlap. Publish an installer containing both keys, and
only then sign new runtimes with the new secret. Mark the previous entry
`retired` only when new installers no longer need to accept releases signed by
it. A signature from an absent, retired, or malformed key fails in the desktop
installer.

## Manifest and signature contract

`runtime/release-manifest.schema.json` is the installer-facing strict schema.
Important properties include:

- `runtime.buildId`: the canonical UUID copied from the promoted rootfs
  manifest, never supplied independently at release time;
- source Git/PX4 commits and the exact Gazebo package description;
- every part's contiguous index, filename, byte count, SHA-256, and HTTPS URL;
- whole uncompressed tar byte count and SHA-256;
- smoke-report filename, SHA-256, URL, completion timestamp, and `passed:true`;
- at least 52 GiB of free space before installation and the portable
  `X:\DroneDream` target hint.

The manifest is canonical JSON using the RFC 8785-compatible subset needed by
this fixed schema: UTF-8, sorted ASCII field names, no insignificant
whitespace, no floating point values, and integers limited to the
interoperable JSON range. Python and Rust share
`runtime/tests/fixtures/jcs-release-vector.input.json`; its canonical SHA-256
is recorded alongside it.

The signature envelope is also canonical JSON and contains exactly:

```json
{
  "schemaVersion": 1,
  "algorithm": "Ed25519",
  "keyId": "ed25519:<full-public-key-sha256>",
  "manifestSha256": "<canonical-manifest-sha256>",
  "signature": "<base64-64-byte-signature>"
}
```

The signature covers the exact canonical manifest bytes. Reformatting or
changing one byte invalidates it.

## Manual local packaging test

Only a rootfs exported by `runtime/export-rootfs.sh` can be packaged. That
script requires a successful real smoke report bound to the same runtime and
Docker image. Given those outputs:

If an older valid export retained the embedded manifest but lost only its
sidecar, recover that one member without unpacking any other archive path:

```bash
python runtime/tools/runtime_release.py extract-manifest \
  --rootfs runtime/out/DroneDreamRuntime-0.1.0-amd64.tar \
  --output runtime/out/DroneDreamRuntime-0.1.0-amd64.tar.manifest.json
```

The recovery command reads only
`opt/dronedream/runtime-manifest.json`, rejects duplicate/link/non-file
members, validates the embedded passed smoke evidence, and creates a new
sidecar without overwriting an existing file.

```bash
python runtime/tools/runtime_release.py package \
  --rootfs runtime/out/DroneDreamRuntime-0.1.0-amd64.tar \
  --runtime-manifest runtime/out/DroneDreamRuntime-0.1.0-amd64.tar.manifest.json \
  --smoke-report runtime/out/smoke-report.json \
  --output-directory runtime/out/release/runtime-v0.1.0-beta.1 \
  --base-url https://github.com/ChiZhang-805/DroneDream/releases/download/runtime-v0.1.0-beta.1 \
  --build-timestamp 2026-07-12T00:00:00Z

export DRONEDREAM_RUNTIME_ED25519_PRIVATE_KEY="$(cat ~/.dronedream/runtime-release-ed25519.key)"
python runtime/tools/runtime_release.py sign \
  --manifest runtime/out/release/runtime-v0.1.0-beta.1/runtime-release.json
unset DRONEDREAM_RUNTIME_ED25519_PRIVATE_KEY

python runtime/tools/runtime_release.py verify \
  --manifest runtime/out/release/runtime-v0.1.0-beta.1/runtime-release.json \
  --signature runtime/out/release/runtime-v0.1.0-beta.1/runtime-release.json.sig \
  --keyring runtime/release-public-keys.json \
  --payload-directory runtime/out/release/runtime-v0.1.0-beta.1
```

`reassemble` repeats all signature, evidence, part, and whole-artifact checks
while writing to a random partial filename. It atomically renames the output
only after all checks succeed; any failure removes the partial file.

## Self-hosted build and release workflow

`.github/workflows/runtime-release.yml` runs only through manual
`workflow_dispatch` on a dedicated Linux amd64 runner labelled
`dronedream-runtime-builder`. Recommended temporary builder capacity is 8 CPU,
32 GiB RAM, and at least 200 GiB SSD with Docker Buildx. It may be deleted
after the release.

The workflow performs these gates in order:

1. validate the beta tag and require a non-empty committed public keyring and
   GitHub signing secret;
2. run static contracts and unit tests;
3. build the pinned runtime from a clean commit;
4. run the real headless PX4/Gazebo and parameter readback smoke suite;
5. export the smoke-promoted rootfs;
6. split and sign canonical release metadata;
7. independently verify the signature, smoke report, every part, and the
   complete tar stream;
8. create a new immutable GitHub prerelease only when the operator explicitly
   sets `publish: true`.

Use `publish: false` first. Verified assets remain on the self-hosted runner
for inspection and no GitHub Release is created. The workflow never updates or
overwrites an existing tag/release. A failed, missing, mismatched, or partially
successful smoke report cannot reach the upload step.

## End-to-end release boundary

Static contracts, Rust/frontend tests, the pinned-NSIS-template check, and the
runtime smoke gate cover important pieces independently. They are not evidence
that a particular desktop installer has completed the entire customer journey.
Before promoting a public Windows release, exercise at least these cases on
clean supported machines with the exact published assets:

1. default install-all on a machine with WSL2 ready;
2. custom-drive install with the 6.1-GB signed payload and 52-GiB gate;
3. desktop-only with no Runtime network request;
4. WSL enablement through UAC, required reboot, reopen, and automatic resume;
5. discard before start and cancel during a resumable download;
6. upgrade, same-version reinstall, passive/silent install, and uninstall with
   no automatic Runtime import and with the existing Runtime preserved;
7. a machine that already has a personal Ubuntu distribution, proving it is
   unchanged throughout the flow;
8. unsigned SmartScreen tester instructions until Authenticode signing exists.

Record installer version, runtime release tag/build ID, Windows build, selected
drive, WSL state before/after, and final PX4/Gazebo readiness for each run. Do
not describe the package as full public production readiness until this matrix
passes with the release artifacts users will actually download.
