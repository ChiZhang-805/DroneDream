# SignPath Foundation application packet

This document contains the verified project facts and application text for a
free SignPath Foundation open-source code-signing subscription. It is an
application aid, not proof that DroneDream has been accepted or signed.

## Verified project information

| Field | Value |
| --- | --- |
| Project | DroneDream |
| Repository | https://github.com/ChiZhang-805/DroneDream |
| Maintainer | Chi Zhang (`@ChiZhang-805`) |
| Contact | cz005623@gmail.com |
| License | MIT |
| Public website | https://getdronedream.com/ |
| Releases | https://github.com/ChiZhang-805/DroneDream/releases |
| Existing installer form | Public Windows x64 NSIS installer, currently unsigned |
| Release workflow | `.github/workflows/desktop-installer.yml` |
| Code signing policy | `CODE_SIGNING_POLICY.md` |
| Privacy policy | `PRIVACY.md` |
| Security policy | `SECURITY.md` |

## Eligibility evidence

- The repository is public and licensed under the OSI-approved MIT License.
- The project is actively maintained and has public source history,
  documentation, releases, stars, forks, and a public Windows NSIS preview.
- The release workflow builds the application from the public repository on
  GitHub-hosted runners and uses committed npm and Cargo lockfiles.
- The repository does not track Windows installers, code-signing certificates,
  private keys, or opaque maintainer-owned binary components.
- The npm dependency inventories declare licenses, Rust metadata declares a
  license for every external crate, and Runtime third-party components and
  pinned revisions are documented in `runtime/THIRD_PARTY_NOTICES.md`.
- The application is an engineering experiment tool, not a vulnerability
  scanner, exploit tool, security bypass, or malware component.
- The installer warns before system changes, supports silent install and
  uninstall, isolates its WSL2 distribution, and does not reuse or unregister
  an unrelated Linux distribution.
- Network behavior, local data, credentials, third parties, retention, and
  removal are documented in the privacy policy.

## Application description

Use the following English text in the SignPath application form:

> DroneDream is an open-source, local-first Windows desktop platform with four
> separately identified products: Universal, SIM, LAB, and FIELD. It supports
> parametric vehicle design, PX4/Gazebo simulation, bounded controller-tuning
> experiments, simulation-to-hardware qualification, and field evidence. The
> Windows products share a separately managed Runtime where required and do not
> modify a user's existing Ubuntu distribution. DroneDream is an engineering
> and research tool and does not claim to certify parameters for real aircraft.

For the reason for requesting signing, use:

> DroneDream has a public NSIS installer and a small initial user group of
> approximately 50 students and engineering users. The project is
> non-commercial at this stage. Authenticode signing is requested so users can
> verify that each Windows application and installer was produced by the
> public GitHub repository and was not modified after the reviewed build. The
> project will use SignPath's GitHub origin verification, manual approval for
> every release, immutable versioned releases, a separate authenticated Tauri
> updater signature, and exact SHA-256 verification between GitHub and the
> public download website.

For build and release provenance, use:

> Source is built only by `.github/workflows/desktop-installer.yml` on
> GitHub-hosted Windows runners. The workflow installs npm and Cargo
> dependencies from committed lockfiles, runs frontend/backend/Rust tests and
> static checks, builds and signs the application executable, bundles and signs
> the NSIS installer, verifies both Authenticode signatures, creates the Tauri
> updater signature, computes SHA-256, writes the edition-specific
> `latest-<edition>.json`, and publishes an immutable per-edition GitHub
> Release. Only after that immutable release succeeds does CI advance the
> corresponding authenticated stable metadata channel. The public website is
> allowed to deploy only the same version, byte length, and SHA-256.

## Requested SignPath configuration

Ask SignPath to provision one project with GitHub.com as a trusted build
system, origin verification enabled, and two artifact configurations:

1. `windows-application`: one PE file named `drone-dream-desktop.exe`, requiring
   `ProductName` to be exactly one of `DroneDream-Universal`, `DroneDream-Sim`,
   `DroneDream-Lab`, or `DroneDream-Field`, and requiring
   `ProductVersion=${version}`. Sign with Authenticode SHA-256 and a trusted
   timestamp.
2. `windows-installer`: one PE file whose name is exactly one of
   `DroneDream-Universal_${version}_x64-setup.exe`,
   `DroneDream-Sim_${version}_x64-setup.exe`,
   `DroneDream-Lab_${version}_x64-setup.exe`, or
   `DroneDream-Field_${version}_x64-setup.exe`, with the matching `ProductName`
   and `ProductVersion=${version}`. Sign with Authenticode SHA-256 and a trusted
   timestamp.

Use a release signing policy that accepts only the public DroneDream GitHub
repository, GitHub-hosted runners, the committed desktop workflow, and a
manually approved signing request. Disable release signing from self-hosted
runners and disallow rerunning an old workflow to obtain a new signature.

## Values supplied after acceptance

The release workflow is prepared to use these GitHub configuration values:

- secret `SIGNPATH_API_TOKEN`;
- variable `SIGNPATH_ORGANIZATION_ID`;
- variable `SIGNPATH_PROJECT_SLUG`;
- variable `SIGNPATH_APPLICATION_POLICY_SLUG`;
- variable `SIGNPATH_APPLICATION_ARTIFACT_CONFIGURATION_SLUG`;
- variable `SIGNPATH_INSTALLER_POLICY_SLUG`; and
- variable `SIGNPATH_INSTALLER_ARTIFACT_CONFIGURATION_SLUG`.

The same workflow also requires one registered public OAuth client identifier
for each desktop callback identity:

- variable `DRONEDREAM_OAUTH_CLIENT_ID_UNIVERSAL`;
- variable `DRONEDREAM_OAUTH_CLIENT_ID_SIM`;
- variable `DRONEDREAM_OAUTH_CLIENT_ID_LAB`; and
- variable `DRONEDREAM_OAUTH_CLIENT_ID_FIELD`; and
- variable `DRONEDREAM_OAUTH_CLIENT_ID_AGENT`.

The SignPath GitHub App must be installed for this repository and the
predefined GitHub.com trusted build system must be linked to the SignPath
project before the first signed release.

## Human-only actions

These actions require the maintainer's own identity or explicit account
authorization and cannot be delegated to a build script:

1. Enable and verify MFA on the GitHub account used to maintain DroneDream.
2. Read and accept the SignPath Foundation conditions.
3. Submit the application at https://signpath.org/apply using the text above.
4. If accepted, create/authorize the SignPath account, install the SignPath
   GitHub App, link GitHub.com as the trusted build system, and approve the
   requested artifact/policy configuration.
5. Register or confirm the five public desktop OAuth clients in the browser and
   enter their public client IDs as the four GitHub repository variables above.
6. Create a least-privilege SignPath submitter token and enter it directly as
   the GitHub `SIGNPATH_API_TOKEN` secret. Never send the token in chat or
   commit it to the repository.
7. Manually approve each production signing request in SignPath.

All source changes, workflow implementation, validation, artifact naming,
release checks, and stable-channel advancement are automated. The steps above
remain human-only because they require the maintainer's identity, account
consent, secret entry, or an explicit production-signing approval.
