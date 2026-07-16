# DroneDream product website

This directory contains the release and deployment wrapper for the independent
DroneDream product/download website. The React and Three.js source lives in
`frontend/src/site`, and the production output is `frontend/site-dist`.

## Build a release website

First build the current Windows installer. Then run from PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File website/scripts/build-release-site.ps1
```

The script verifies the installer checksum, builds the static website, copies
the exact versioned `0.3.18` preview EXE and checksum, and emits
`downloads/latest.json`. It refuses to publish a stale or mismatched installer.
This build does not Authenticode-sign the EXE and the site must not label it as
a signed or production release.

For local review:

```powershell
npm.cmd --prefix frontend run site:preview
```

Open `http://127.0.0.1:4174/`.

## Alibaba Cloud deployment

The recommended production layout is Ubuntu LTS + Nginx for the static site,
with versioned EXE, video, and future Runtime payloads moved to OSS/CDN as
traffic grows. A 2-vCPU/2-GiB server is sufficient for the static Nginx site;
large release traffic should not be served indefinitely from its system disk.
Do not store Alibaba Cloud AccessKeys in this repository.

1. Replace `dronedream.example.com` in both Nginx templates with the final domain.
2. Make `/var/www/dronedream-releases` writable by the deployment account, then run
   `scripts/deploy-static.sh user@server`. It uploads to a new release directory,
   verifies the remote EXE SHA-256, and atomically switches
   `/var/www/dronedream-current` while preserving older releases for rollback.
3. Install `nginx/dronedream-bootstrap.conf`, run `nginx -t`, and reload Nginx.
   Use Certbot's webroot flow with `/var/www/dronedream-current` to issue the first
   certificate.
4. Replace the bootstrap server block with `nginx/dronedream.conf`, update the
   certificate paths if necessary, run `nginx -t` again, and reload. The production
   template redirects HTTP to HTTPS, enables HSTS, compression, CSP, and immutable
   caching for versioned assets.
5. Keep only ports 80/443 public; restrict SSH to the administrator's IP and use an
   SSH key. Never send the server password or an Alibaba Cloud AccessKey in chat.

If an existing server was created from a WordPress image, take a snapshot before
changing Nginx or document roots. Reinstalling or replacing its system disk can
destroy WordPress and its database, so that destructive step requires explicit
confirmation from the owner.
