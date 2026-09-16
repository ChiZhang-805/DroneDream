# Desktop publication status — 2026-09-16

## Publication order

Publish a tested, consistently versioned installer and its verified signatures
to the GitHub update channel before updating the daily-use desktop installation.
Local validation builds must remain explicitly identified as local builds, not
as already-published releases. Do not disable runtime or model admission checks
to make a release pass.

Keep the existing public inventory: eight long-lived branches, five updater
channels, the latest and previous five-edition installer releases, one Runtime
release, and the latest successful GitHub Pages deployment.

## Source changes in this update

- Chatbot is the new-conversation entry. The first submitted message creates an
  independently stored conversation and navigates to its sidebar entry.
- Account- and edition-scoped local conversations preserve failed submissions,
  reopen saved messages, and keep background responses in their original thread.
- Model clarification text is preserved independently of the interface locale.
- Asset binding, interpretation controls, authentication, runtime transport,
  settings persistence, and boundary validation include the accumulated fixes
  and regression tests from the source review.
- Runtime check rows use returned evidence, not animation timing, to indicate
  success. Update failures expose the affected component and their actual cause.

## Verified scope

The frontend suite passed 1,034 tests in 134 files using two workers and a
20-second per-test default on the development host. Type checking, scoped lint,
the AGENT frontend build, and the local desktop build passed. This is not a
cloud-model flight acceptance result.

The first Pages CI run caught an unreachable `pending` branch in the Runtime
status display. That branch was removed; the full referenced TypeScript build
(`tsc -b --force`) and 17 focused conversation/Runtime/updater tests then passed.
Use the referenced-project build for this check: a root-only `tsc --noEmit` run
does not validate all frontend projects.

An AGENT client-only local patch was installed on the development host. It
preserves the existing Core, Runtime, and account data. Conversations currently
persist locally per account; this change does not claim cross-device chat sync.

## Update channel is not promoted by this source commit

The last published five-edition installer release remains build 1838.
Two conditions must be resolved before a new complete release can be promoted:

1. The current local-expert package fails the current control-protocol staging
   check with `LOCAL_POLICY_RUNTIME_CURRENT_CONTROL_REQUIRED`. A genuinely
   compatible and admitted model package is required; editing its qualification
   fields or reusing an old receipt is not a remedy.
2. The repository's production Windows signing workflow lacks its SignPath
   organization, project, policy/artifact configuration and API-token settings.
   The Tauri updater signing key exists, but that signature is not a Windows
   Authenticode publisher signature and cannot be described as one.

The public registered AGENT OAuth client variable was added to GitHub so its
builds use the same approved login identity as the local client. No credential
values or private account data are included in this public document.

Existing release assets and update-channel manifests remain unchanged until
the replacement installers satisfy the release requirements.

## Open-source / SignPath preparation

The maintainer authorized MIT licensing of first-party Core source, including
modification, redistribution, and commercial use. Core license metadata has been
published in the clean [DroneDream-Agent-Core repository](https://github.com/ChiZhang-805/DroneDream-Agent-Core).
The initial public snapshot excludes private history, real session exports,
developer handoff notes, credentials and model weights. The original private
repository and its development files remain intact.
The exact reviewed Core source is recorded in
[`agent-core-public-source.json`](agent-core-public-source.json); this is a source
reference, not a binary qualification receipt or an updater manifest.

School Map and My Drone were separately authorized under MIT on 2026-09-16 and
are included with a hash-scoped external license grant. Historical `NOASSERTION`
metadata and qualification-bound archive bytes remain unchanged. The later
permission does not requalify assets or models, grant third-party rights, or
constitute a new installer release.

The [SignPath application packet](signpath-foundation-application.md) now lists
all five editions and distinguishes intended signing from actual acceptance.
`desktop/scripts/check-signpath-readiness.py` reads repository visibility and
configuration names only; it never retrieves secret values or grants signing
authority. The original incubation repository remains private. No SignPath
application, account authorization, certificate, or token is claimed as completed.

The product workflow still needs an exact public Core source binding and its
complete build/staging before it can demonstrate the origin of every included
first-party executable. Publishing MIT source and obtaining signing approval do
not waive that requirement or the current model's control-protocol admission gate.
