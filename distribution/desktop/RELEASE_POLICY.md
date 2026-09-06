# DroneDream public release, tag, and deployment retention policy

DroneDream publishes the five Windows applications as one synchronized release.
The display version may remain `1.0.0` during development; the strictly increasing
Git commit count is the update build number.

## Permanent public layout

- Exactly eight long-lived branches: `main`, the five edition branches
  (`codex/software`, `codex/software-sim`, `codex/software-lab`,
  `codex/software-field`, `codex/software-agent`), `codex/website`, and
  `codex/technical-report`. Feature branches are temporary and must not become
  additional permanent channels.
- An immutable build release for each retained desktop build:
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
- Exactly eight public Releases and eight matching Tags after retention: the
  current and rollback five-edition builds, five updater-channel releases, and
  the current Runtime release.
- Exactly one GitHub Pages Deployment record is retained after a successful
  publish. Superseded inactive Deployment records are deleted only after the
  newest record is verified successful.

The `Retain latest Pages deployment` job runs only after the Pages deployment
completes successfully. It verifies the newest `github-pages`
deployment state, marks every older record inactive, deletes those records, and
then verifies that exactly the newest deployment remains.

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

The public Release names and remote Tag names must be the same set. Under the
current five-product topology that set contains exactly eight entries: two
five-edition builds, five updater channels, and one Runtime release. A release
publisher must fail closed if any standalone remote Tag, orphaned Release, extra
Runtime release, or third desktop rollback remains after approved pruning.

Push validated work promptly to its existing long-lived branch. A fast update
does not relax source-integrity, secret scanning, build, test, or signed-release
gates, and it must not create an extra permanent branch, Release, Tag, or
Deployment record. Shared product changes still return through the repository's
normal integration policy.

Remote `archive/*`, unsigned internal-build, website-deployment, experiment, and
recovery-only Tags are forbidden. A recovery snapshot that is not a public
release belongs in a verified local Git bundle under the workspace Archive,
not in GitHub's public Tag list.

## GitHub Pages deployments

The `github-pages` environment retains exactly its newest successful Deployment.
Every successful Pages workflow audits all older records, requires them to be
`inactive`, and then deletes them. A superseded `success` or a terminal `error`
or `failure` record is first normalized to `inactive`. Cleanup fails before
changing anything if the newest record is not successful or an older record is
queued, pending, waiting, or in progress.

Deployment records are operational history, not Releases, Tags, immutable site
artifacts, or additional live websites. Workflow runs and their independently
configured log/artifact retention are outside this one-record Pages policy.

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
removes non-manifest assets from those channels. After pruning, it requires the
public Release and remote Tag inventories to equal the exact retained set.
`-WhatIf` previews the GitHub mutations without applying them.

Do not manually replace assets in an immutable five-edition release. Publish a new
build number and advance the five channel manifests instead.
