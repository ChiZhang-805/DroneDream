# SignPath Foundation application packet

Updated 2026-09-16. **Preparation only: not submitted or accepted.** This packet
is not a claim that the complete product already meets every condition.

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
| Signing policy | https://github.com/ChiZhang-805/DroneDream/blob/main/CODE_SIGNING_POLICY.md |
| Privacy policy | https://github.com/ChiZhang-805/DroneDream/blob/main/PRIVACY.md |
| Security policy | https://github.com/ChiZhang-805/DroneDream/blob/main/SECURITY.md |

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
3. The current local model package fails current control-protocol admission.
   This is an installer/flight issue, not something signing or MIT can fix.
4. SignPath account/project/token settings are not provisioned. The desktop
   workflow also needs the exact public Core source binding and complete sidecar
   build/staging. A shell-only build does not prove the whole product's origin.
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

## Human steps

1. Core repository placement and MIT rights for the two first-party default assets
   were confirmed on 2026-09-16. Review the exact proposed binary/model inventory;
   this confirmation does not cover third-party weights or training datasets.
2. Verify GitHub MFA at https://github.com/settings/security; confirm maintainer
   name and contact email.
3. Read https://signpath.org/terms.html. Once the technical conditions above are
   resolved, submit https://signpath.org/apply using truthful information. This
   document does not claim submission or terms acceptance on your behalf.
4. If accepted, complete SignPath account setup and MFA, authorize the GitHub App
   for the intended repositories, and approve agreed artifact/policy settings.
5. Enter the provider-issued token directly into GitHub Actions Secrets; never
   send it in chat or source. Enter nonsecret IDs/slugs in repository Variables.
6. Manually approve signing requests when a qualified release is ready.
   Application acceptance is not automatic release approval.

Run `python desktop/scripts/check-signpath-readiness.py` to inspect configured
names and repository visibility without reading or printing secret values.
Configuration presence does not prove acceptance, correct permissions, complete
public-source licensing, or flight qualification.
