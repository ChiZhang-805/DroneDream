# DroneDream desktop release policy

DroneDream publishes the five Windows applications as one synchronized release.
The display version may remain `1.0.0` during development; the strictly increasing
Git commit count is the update build number.

## Permanent public layout

- One immutable build release:
  `five-edition-v<version>-build-<buildNumber>`.
- Exactly twenty immutable build assets: installer, updater signature, SHA-256
  checksum, and build receipt for each of Universal, SIM, LAB, FIELD, and
  AUTONOMY.
- Five permanent updater-channel releases:
  `desktop-<edition>-channel`.
- Each updater-channel release contains exactly one `latest-<edition>.json` file.
  That manifest points to the matching installer inside the shared immutable
  five-edition release.
- The website download menu points to those same five immutable installer assets.

An installed older build checks only its permanent edition channel. It may update
directly to the newest build without the intermediate build releases remaining
online. Equal display versions are ordered by the authenticated `build-number` and
`source-commit` fields in the updater manifest.

## Retention

Keep:

1. the current five-edition build;
2. one previous five-edition build for emergency rollback;
3. the five permanent updater channels; and
4. the current Runtime release.

Delete older desktop build releases, their tags, superseded Runtime releases, and
obsolete website/signing candidate releases after the five updater channels and
website downloads have been verified against the current five-edition release.
Git history remains the source of old application code; deleted Release assets are
not recoverable unless they were preserved elsewhere.

## Publishing

Build all five signed installers into one handoff directory, then publish from the
repository root:

```powershell
& desktop/scripts/publish-five-edition-release.ps1 `
  -HandoffRoot "Q:\DroneDream-Workspace\Build\History\<build>\codex-builds\core-five-msvc" `
  -PruneObsoleteReleases `
  -Confirm:$false
```

The publisher rejects mixed source commits/build numbers, invalid checksums,
missing updater signatures, or a non-canonical twenty-file release. It creates or
verifies the immutable combined release before changing any updater channel, then
removes non-manifest assets from those channels. `-WhatIf` previews the GitHub
mutations without applying them.

Do not manually replace assets in an immutable five-edition release. Publish a new
build number and advance the five channel manifests instead.
