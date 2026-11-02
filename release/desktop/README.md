# Desktop release

This directory contains the source-controlled inputs used to build and publish
the five Windows editions from the single `main` branch.

## Layout

- `config/` — edition, update, capability, safety, schema, and Vehicle Pack data.
- `scripts/` — build and publication tools.
- `tests/` — release-contract tests.
- `RELEASE_POLICY.md` — public release and retention rules.

The five editions share one source tree. Their differences are expressed by
`apps/desktop/editions/*.json` and the data under `config/`; they are not stored
on separate branches.

## Validate

From the repository root:

```powershell
python -m pytest release/desktop/tests -q
npm --prefix apps/desktop run verify:updater-build
```

## Publish

Build all five installers from the same `main` commit, then publish them as one
synchronized release:

```powershell
& apps/desktop/scripts/publish-five-edition-release.ps1 `
  -HandoffRoot "Q:\DroneDream-Workspace\Build\Release-Staging" `
  -PublishOnly `
  -Confirm:$false
```

After the website and all five updater channels are verified, rerun with
`-PruneObsoleteReleases` to apply the retention policy. Generated installers,
receipts, test evidence, and caches belong outside the repository.
