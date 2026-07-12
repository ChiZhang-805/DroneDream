# DroneDreamRuntime signed release pipeline

The Windows installer downloads a dedicated WSL2 distribution; it never
moves, upgrades, or unregisters an existing Ubuntu distribution. A user may
choose any suitable fixed NTFS drive. `X:\DroneDream` in the signed manifest
is a drive-letter placeholder, not a hard-coded installation path; on the
current development machine the desktop planner may recommend
`E:\DroneDream`.

This document covers the release assets consumed by the one-click installer.
The manifest embedded inside the rootfs remains the source/component/smoke
record described in `runtime/README.md`.

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
wsl.exe --import DroneDreamRuntime <chosen-directory> <verified-rootfs.tar> --version 2
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
