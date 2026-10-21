# DroneDream release version policy

The desktop and website release version is fixed at **1.0.0**.

Do not increment this version for ordinary code, copy, layout, test, packaging,
or deployment changes. Change it only when the product owner explicitly states
that the current work is a version upgrade and names or approves the new
version. A release change must update the Tauri config, Cargo package, desktop
npm package and lockfile, frontend npm package and lockfile, localized in-app
version label, website release metadata, updater manifest, tests, and release
tag together.

Application-update signatures and Windows Authenticode signatures are separate:

- the Tauri updater signature proves that an update artifact was authorized by
  DroneDream and is mandatory for in-app installation;
- Authenticode proves the Windows publisher identity and is what Windows and
  SmartScreen inspect.

Never describe an installer as signed unless both the intended updater artifact
signature and a `Valid` Authenticode result have been verified on the exact
published bytes.
