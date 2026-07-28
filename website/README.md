# DroneDream product website

This directory contains the release tooling and BaoTa/Nginx configuration for
the independent DroneDream product and download website. The React and Three.js
source lives in `frontend/src/site`; the generated release is
`frontend/site-dist`.

## Public website topology

- `https://getdronedream.com/` is the only global production entry point and is
  published by GitHub Pages.
- `http://47.93.180.216/` is an internal bare-IP mirror for selected users in
  mainland China. It has no public domain and is not a second production site.
- Both origins must serve the same commit-pinned artifact. The Pages workflow
  builds that artifact once, deploys it to GitHub Pages, and uploads an
  identically named workflow artifact for the BaoTa mirror.
- Supabase cloud data can be shared, but browser sessions remain scoped to each
  origin. Users sign in separately on the two origins.

The Pages build reads `website/pages-release.json` and links directly to the
exact versioned GitHub Release asset. It does not duplicate the installer in
the shared site artifact. This keeps the global download, checksum, CI artifact,
and future SignPath-signed release traceable to the same bytes.

Build the Pages artifact locally with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File website/scripts/build-pages-site.ps1
```

The script produces `index.html`, `404.html`, `.nojekyll`, the fixed
`getdronedream.com` `CNAME`, `downloads/latest.json`, `build-manifest.json`, and
`SHA256SUMS` under `frontend/site-dist`. A local build is for review; the
production mirror must use the exact artifact downloaded from the successful
Pages workflow. Update `website/pages-release.json` only after a new installer
version is explicitly approved and its public GitHub Release asset and checksum
have been verified.

## Build and review a release

Build the versioned Windows installer first, then run from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File website/scripts/build-release-site.ps1
```

The builder reads the desktop version, verifies the installer checksum, and
creates an offline review bundle containing the EXE. That bundle is not the
shared production artifact and must not be passed to the BaoTa deployment
wrapper. The EXE is not Authenticode-signed, so the website must continue to
describe it as a preview rather than a signed production release.

For local review:

```powershell
npm.cmd --prefix frontend run site:preview
```

Open `http://127.0.0.1:4174/`.

## Supported Alibaba Cloud/BaoTa deployment

The current host uses BaoTa's Nginx installation and this release layout:

```text
/www/wwwroot/dronedream/
  releases/<version>-<UTC timestamp>/
  current -> releases/<active release>
  candidate -> releases/<release under validation>   # temporary
```

`deploy-static-baota.sh` verifies the archive, integrity and build manifests,
release metadata, security headers, and loopback-only staging vhost before it
atomically switches `current`. Any failure restores the previous symlink and
Nginx configuration.

Wait for the successful Pages workflow for the frozen commit, then download its
shared artifact:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File website/scripts/download-pages-artifact.ps1 `
  -Commit $commit `
  -Destination "work\website-artifacts\$commit"
```

Deploy that downloaded directory to the internal mirror. Pass the private key
**path**, never its contents:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File website/scripts/deploy-static-baota.ps1 `
  -SshKeyPath "$HOME\.ssh\DroneDream-deploy.pem" `
  -ArtifactDirectory "work\website-artifacts\$commit" `
  -ExpectedCommit $commit
```

The wrapper does not rebuild. It validates every local artifact hash, source
commit, origin contract, release URL, installer bytes and checksum; uploads the
archive through a private staging directory; and verifies the mirror's
`SHA256SUMS` plus public HTML, JavaScript, and CSS byte-for-byte. Targets are
fixed in `website/deployment-targets.json`, so the SSH destination, public host,
root URI, and artifact directory cannot silently drift apart. It uses
`BatchMode=yes` and `StrictHostKeyChecking=yes`; connect once manually and
verify the server fingerprint before the first automated run.

After both deployments, run the independent two-origin parity check:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File website/scripts/verify-site-parity.ps1 `
  -ExpectedCommit $commit
```

The mirror vhost declares only `47.93.180.216` on HTTP. Keep port 80 public only
to the intended audience, restrict SSH to trusted administrator addresses, and
never commit or paste a private key or Alibaba Cloud AccessKey. Global HTTPS is
owned by GitHub Pages and must be verified independently before release signoff.

### Release cleanup

Run cleanup on the server. It is a dry run unless `--apply` is present and it
uses the same lock as deployment:

```bash
bash website/scripts/prune-static-baota.sh 0.3.18-20260716T183330Z
bash website/scripts/prune-static-baota.sh --apply 0.3.18-20260716T183330Z
```

The active release is always retained. Additional release IDs supplied on the
command line are also retained.

## Legacy generic-Nginx workflow

`website/scripts/deploy-static.sh` and the templates under `website/nginx/`
target the older `/var/www/dronedream-*` layout for a generic Ubuntu/Nginx host.
They are retained as **legacy reference tooling** and are not the supported path
for the current BaoTa server. Do not mix that layout with the BaoTa scripts or
vhosts.

If an existing host was created from a WordPress image, take a snapshot before
changing Nginx or document roots. Reinstalling or replacing its system disk can
destroy WordPress and its database and therefore requires explicit owner
approval.
