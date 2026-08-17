# DroneDream product website

This directory contains the release tooling and BaoTa/Nginx configuration for
the independent DroneDream product and download website. The React and Three.js
source lives in `frontend/src/site`; the generated release is
`frontend/site-dist`.

## Public website topology

- GitHub Pages is the global entry point until the project domain has working
  DNS. After DNS is verified, set the repository variable
  `DRONEDREAM_CUSTOM_DOMAIN` to the exact hostname, such as
  `getdronedream.com`, and the Pages build will emit `CNAME`.
- `https://getdronedream.com/` and `https://www.getdronedream.com/` remain the
  intended future global entry points.
- `https://cn.getdronedream.com/` is reserved for the Alibaba Cloud mirror.
  It must not be made public until the domain and deployment satisfy the
  applicable mainland-China filing and HTTPS requirements.

The Pages build reads `website/pages-release.json` and links directly to the
exact versioned GitHub Release asset. It does not duplicate the installer in
the Pages artifact. This keeps the global download, checksum, CI artifact, and
future SignPath-signed release traceable to the same bytes.

Build the Pages artifact locally with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File website/scripts/build-pages-site.ps1
```

The script produces `index.html`, `404.html`, `.nojekyll`, an optional `CNAME`,
and `downloads/latest.json` under `frontend/site-dist`. Update
`website/pages-release.json` only after a new installer version is explicitly
approved and its public GitHub Release asset has been verified.

## Build and review a release

Build the versioned Windows installer first, then pass its supported MSVC output
to the website builder from the repository root. For a single-edition MSVC
build:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File website/scripts/build-release-site.ps1 `
  -EditionId universal `
  -CargoTargetRoot desktop/src-tauri/target
```

For the four-edition build handoff:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File website/scripts/build-release-site.ps1 `
  -EditionId universal `
  -InstallerHandoffRoot "$env:LOCALAPPDATA/DroneDream/codex-builds/core-four-msvc"
```

The builder reads the desktop version, verifies the installer checksum, builds
the static site, copies the exact versioned preview EXE and checksum, writes
`downloads/latest.json`, and generates `SHA256SUMS` for the complete site. It
refuses missing or ambiguous handoffs instead of guessing between stale builds.
The EXE is not Authenticode-signed, so
the website must continue to describe it as a preview rather than a signed
production release.

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

`deploy-static-baota.sh` verifies the archive, manifest, release metadata,
installer checksum, security headers, and loopback-only staging vhost before it
atomically switches `current`. Any failure restores the previous symlink and
Nginx configuration.

The supported Windows entry point is the PowerShell wrapper. Targets are
declared together in `website/deployment-targets.json`, so the SSH destination,
public host, public root URI, and vhost policy cannot silently drift apart.
Pass the private key **path**, never its contents.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File website/scripts/deploy-static-baota.ps1 `
  -SshKeyPath "$HOME\.ssh\DroneDream-deploy.pem" `
  -TargetMode Production
```

The wrapper builds the website unless `-SkipBuild` is supplied, validates every
local manifest entry, creates a temporary archive, uploads into a private remote
staging directory, verifies the uploaded archive SHA-256, invokes the guarded
server deployment, removes temporary files, and probes the public page and
hashed assets. It uses `BatchMode=yes` and `StrictHostKeyChecking=yes`; connect
once manually and verify the server fingerprint before the first automated run.

`Production` is the default and requires:

- `cn.getdronedream.com`;
- the root `https://cn.getdronedream.com/` URI;
- an existing BaoTa vhost that names that host and listens on 443 with TLS.

Production deployment preserves that employee-managed TLS vhost instead of
overwriting its certificate paths. Before activating a release, the server
script validates the preserved vhost, the trusted certificate, the HTTPS
content/security headers, and the HTTP-to-HTTPS redirect. The wrapper then
repeats the checks through public DNS and re-downloads the installer.

Until DNS, filing, and TLS are complete, the explicit preview target remains:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File website/scripts/deploy-static-baota.ps1 `
  -SshKeyPath "$HOME\.ssh\DroneDream-deploy.pem" `
  -TargetMode Preview
```

Preview mode installs the repository-managed HTTP vhost. It declares both
`cn.getdronedream.com` and `47.93.180.216`, while the direct IPv4 URL remains
the only supported pre-filing bare-IP public preview. Production mode will fail closed
until the BaoTa TLS vhost is in place.
Keep ports 80/443 public, restrict SSH to trusted administrator addresses, and
never commit or paste a private key or Alibaba Cloud AccessKey.

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
