# SignPath Foundation application packet

**Foundation eligibility approved; signing setup pending.** The maintainer's
2026-10-29 approval email confirms eligibility and creation of DroneDream [OSS].
The account is active. The supplied dashboard still marks `release-signing`
as `INVALID` because its production certificate is `CSR PENDING`.
The GitHub trusted build system is linked, and the repository now contains the
SignPath secret and variables listed below. The default artifact configuration
has slug `initial` and accepts a raw PE executable. The manual desktop workflow
uses `test_signing=true` to build from pinned product/Core sources and submit its
full installer to `test-signing`; this does not publish or install a test-signed
build. Complete this actual test run before Foundation review and
production-certificate issuance. This is separate from the existing Tauri updater
signature. The historical application material below is not evidence of a
production signing run.

## Project details

| Field | Prepared answer |
| --- | --- |
| Project | DroneDream |
| Main repository | https://github.com/ChiZhang-805/DroneDream |
| Core repository | https://github.com/ChiZhang-805/DroneDream-Agent-Core |
| Website | https://getdronedream.com/ |
| Downloads | https://github.com/ChiZhang-805/DroneDream/releases |
| Maintainer | Chi Zhang, GitHub `ChiZhang-805` |
| Contact | cz005623@gmail.com — owner to confirm before submission |
| First-party license | MIT; modification, redistribution and commercial use permitted |
| Products | Universal, SIM, LAB, FIELD, AGENT (five editions) |
| Installer form | Windows x64 NSIS executable |
| Signing policy | https://github.com/ChiZhang-805/DroneDream/blob/main/docs/release/code-signing.md |
| Privacy policy | https://github.com/ChiZhang-805/DroneDream/blob/main/docs/legal/privacy.md |
| Security policy | https://github.com/ChiZhang-805/DroneDream/blob/main/.github/SECURITY.md |

Commercial use permitted by MIT is not commercial dual-licensing. Do not invent
user numbers, student eligibility, reputation, or a guaranteed acceptance decision.

## Technical conditions still requiring resolution

1. The product and clean Core repositories are public and MIT-licensed. Original
   private incubation history, real session exports, and account data remain
   excluded. The release must bind the exact public Core commit it builds.
2. The author explicitly granted MIT rights to School Map and My Drone on
   2026-09-16. Core's `docs/default-assets-license.md` and hash-scoped
   `runtime/default-assets-licenses.json` supply the later grant without changing
   the historical `NOASSERTION` metadata or qualification-bound archive bytes.
   Third-party dependencies, weights, and datasets still need their own verified
   redistribution terms; the grant does not relicense them.
3. Local model weights are optional in the current build contract. No model
   bundle is declared, so CI must not require or download a retired package.
   If a model bundle is declared later, its own source, license and compatibility
   requirements still apply.
4. The SignPath organization/account, CI credentials, test policy and repository
   integration are configured. The desktop workflow builds native sensors,
   payload placement, camera clock and the Linux Core wheel on Ubuntu, then
   builds Windows sidecars and the full installer on Windows. A successful
   source build and actual test-signing result are still required; configuration
   presence and a shell-only build do not prove the whole product's origin.
5. GitHub MFA was unavailable in the account API response; verify it in account
   settings. A missing response field does not mean MFA is disabled.

See [Desktop publication status](DESKTOP_PUBLICATION_STATUS.md). Source preparation
does not advance stable updater manifests or approve a flight-qualified release.

## Application text

Prepared text; confirm project/contact details and complete the conditions above:

> DroneDream is an MIT-licensed Windows desktop engineering and research project
> maintained by Chi Zhang. It has five editions: Universal, SIM, LAB, FIELD, and
> AGENT. Its source covers desktop workflows, PX4/Gazebo simulation integration,
> and an agent architecture combining cloud-language-model planning, local
> low-latency models, and a Harness enforcing structured contracts and safety
> boundaries. Core source: https://github.com/ChiZhang-805/DroneDream-Agent-Core.
> Production user data and credentials are private and are not distributed with
> the source. Autonomous-flight work is evaluated in simulation; the project does
> not claim real-aircraft flight certification.

Reason for signing:

> We request Authenticode signing so users can verify our Windows applications
> and NSIS installers. We intend to use verified GitHub build origin and manual
> approval for each signing request. Tauri updater signatures are separate from
> Windows publisher signatures. We understand that acceptance and the artifact
> configuration require SignPath Foundation review.

Build explanation — keep future tense until the complete build works:

> The intended release workflow is `.github/workflows/desktop-installer.yml`.
> Each release will pin public source for every first-party executable, build on
> GitHub-hosted Windows runners, retain dependency notices, and submit application
> and final NSIS installer artifacts for separately approved Authenticode signing.
> Only final signed installer bytes will receive the Tauri signature and SHA-256
> metadata before channel advancement. We will not request signatures for an
> installer containing unpublished Core source, unreviewed asset/model rights,
> or failed release qualification.

## Configuration requested from SignPath

Request a GitHub.com trusted build source, manual release approval, exact
file/version restrictions, and application/installer artifact configurations.
Agree coverage for all first-party sidecars. Do not re-sign third-party
executables as DroneDream-owned binaries or configure broad wildcard signing.

Current product-config names: `DroneDream-Universal`, `DroneDream-Sim`,
`DroneDream-Lab`, `DroneDream-Field`, `DroneDream-Agent`.
NSIS names follow `<ProductName>_<version>_x64-setup.exe`.
Main shell: `drone-dream-desktop.exe`.
Inspect actual PE metadata; a filename does not prove ProductName.

The workflow expects these names; never put secret values in Git:

| Storage | Name |
| --- | --- |
| GitHub secret | `SIGNPATH_API_TOKEN` |
| GitHub variable | `SIGNPATH_ORGANIZATION_ID` |
| GitHub variable | `SIGNPATH_PROJECT_SLUG` |
| GitHub variable | `SIGNPATH_APPLICATION_POLICY_SLUG` |
| GitHub variable | `SIGNPATH_APPLICATION_ARTIFACT_CONFIGURATION_SLUG` |
| GitHub variable | `SIGNPATH_INSTALLER_POLICY_SLUG` |
| GitHub variable | `SIGNPATH_INSTALLER_ARTIFACT_CONFIGURATION_SLUG` |

The Tauri key is independent. Existing public OAuth client IDs and Supabase
browser configuration are not SignPath credentials; do not replace them to apply.

## Remaining human steps

1. Approve the test request in SignPath if its configured policy asks for approval.
   Use the request URL returned by the actual GitHub run.
2. After the full source-build/test-signing run succeeds, give its GitHub run and
   SignPath request links to Foundation support for their setup review. Their
   approval email says they will order and import the production certificate
   after this review; `CSR PENDING` does not mean a usable certificate is issued.
3. Once Foundation activates the production certificate, verify `release-signing`
   is valid and approve the production signing requests. Test-signed files must
   not replace public downloads or installed desktop editions.

The secret is already in GitHub Actions Secrets. Do not resend it in chat or
commit it to source. An API token and a Tauri updater key serve different purposes.

Run `python apps/desktop/scripts/check-signpath-readiness.py` to inspect configured
names and repository visibility without reading or printing secret values.
Configuration presence does not prove acceptance, correct permissions, complete
public-source licensing, or flight qualification.
