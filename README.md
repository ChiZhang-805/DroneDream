<p align="center">
  <img src="docs/assets/brand/drone-dream-lockup-primary.png" alt="DroneDream" width="640" />
</p>

<p align="center">
  <strong>Website track · The public doorway into DroneDream.</strong>
</p>

<p align="center">
  <a href="https://getdronedream.com/">Global website</a> ·
  <a href="website/README.md">Alibaba Cloud delivery</a> ·
  <a href="https://github.com/ChiZhang-805/DroneDream/releases">Releases</a>
</p>

## The website track

This branch owns DroneDream’s public web experience. It explains the product,
guides visitors toward the Windows application and console, publishes the user
manual, presents pricing and model-access options, and provides a community
space for discussing reproducible tuning work.

The website introduces the software; it does not duplicate the software’s
backend, optimizer evidence, or technical-report source.

## What visitors can do

The public experience brings together five connected journeys:

- understand DroneDream’s simulation-first workflow and technical principles;
- review product capabilities before opening the experiment console;
- compare plans and managed-model access without hiding the local-model path;
- read or download the English and Simplified Chinese user manuals;
- join the community to publish topics, images, comments, and reactions under
  account and content-integrity controls.

Release metadata and checksums keep the download experience connected to the
corresponding GitHub release rather than to an opaque uploaded file.

## One experience, two delivery targets

The canonical global release target is GitHub Pages at
[getdronedream.com](https://getdronedream.com/). The same verified static
artifact can be promoted to the Alibaba Cloud/BaoTa host as the mainland
delivery target. The repository defines that topology; each public activation
still requires independent origin, domain, TLS, and byte-parity verification.

Both targets share one build manifest and file-hash inventory. Deployment
scripts validate the candidate release before activation, preserve rollback
boundaries, and prevent a partial upload from becoming the public site.

## Designed for clarity and access

The site uses DroneDream’s pink, violet, and blue identity across the animated
landing experience, product cards, manuals, pricing, account flows, and
community surfaces. English and Chinese copy are authored for comparable visual
rhythm instead of being treated as interchangeable strings.

Responsive layout, keyboard navigation, focus management, reduced-motion
support, accessible names, modal focus traps, typography fit, contained
overflow, and real-browser desktop/mobile checks are part of the release
contract.

## Relationship to software and report

The website may publish approved product screenshots, release metadata, user
manuals, and a finished technical-report PDF. It does not own the experiment
engine or the report’s LaTeX, claim ledger, and raw evidence.

Software behavior is consumed from the
[`codex/software`](https://github.com/ChiZhang-805/DroneDream/tree/codex/software)
track; the publication-ready report is consumed from
[`codex/technical-report`](https://github.com/ChiZhang-805/DroneDream/tree/codex/technical-report).
That separation lets the public story stay synchronized without turning the
website branch into a second copy of either project.

## Visit and follow

- Visit [getdronedream.com](https://getdronedream.com/) for the global product
  experience.
- Treat Alibaba Cloud as a deployment target until its release receipt confirms
  domain, TLS, and artifact parity.
- Browse [GitHub Releases](https://github.com/ChiZhang-805/DroneDream/releases)
  for published installers and integrity files.
- Read the source-owned [website delivery notes](website/README.md) when build,
  browser-audit, parity, or deployment detail is needed.

This root page describes the website as a product surface; operational commands
remain in the dedicated delivery notes. Release trust is documented in the
[Code signing policy](CODE_SIGNING_POLICY.md) and [Privacy policy](PRIVACY.md).
