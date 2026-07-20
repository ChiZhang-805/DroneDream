# Code signing policy

Free code signing provided by [SignPath.io](https://signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

## Scope

This policy covers the DroneDream Windows desktop application and its NSIS
installer. Only binaries produced from the public
[ChiZhang-805/DroneDream](https://github.com/ChiZhang-805/DroneDream)
repository by the repository's GitHub Actions release workflow are eligible
for a DroneDream release signature.

The separately downloaded DroneDreamRuntime image is not an Authenticode
binary. It is governed by its own signed release manifest, checksums, pinned
source revisions, and third-party notices. A Runtime manifest signature must
never be described as a Windows publisher signature.

## Team roles

- **Authors and committers:** [Chi Zhang (@ChiZhang-805)](https://github.com/ChiZhang-805).
- **Reviewers:** Chi Zhang reviews contributions from people who do not have
  direct commit access. Security-sensitive build, installer, updater, and
  signing changes are reviewed through pull requests before they reach the
  release branch.
- **Approver:** Chi Zhang is the release-signing approver. Every production
  signing request requires an explicit manual approval in SignPath; a tag or
  successful build alone is not approval to publish.

The project is currently maintained by one person. If another person receives
write or signing authority, this section and the repository CODEOWNERS file
must be updated before that authority is used.

## Release process

1. The release version is explicitly approved by the project owner and is
   synchronized across the Tauri, Cargo, npm, UI, updater, and website
   metadata. Ordinary changes do not silently increment the version.
2. A release is built on a GitHub-hosted Windows runner from a tagged commit.
   JavaScript and Rust dependencies are installed from committed lockfiles.
3. Tests, linting, type checking, Rust formatting and Clippy, installer
   localization checks, Runtime planner checks, and the release-source policy
   audit must pass before signing.
4. The unpacked DroneDream application executable is uploaded as a GitHub
   Actions artifact and submitted to SignPath with verified GitHub origin
   metadata. After manual approval, the signed executable is used to create
   the NSIS installer.
5. The NSIS installer is uploaded as a second GitHub Actions artifact and
   submitted to SignPath. After manual approval, both the installed
   application executable and installer must pass Windows Authenticode
   verification with status `Valid`.
6. The exact Authenticode-signed installer is then signed with the independent
   Tauri updater key. SHA-256 and updater metadata are generated only after
   the final installer bytes exist.
7. GitHub publishes an immutable versioned release. The public website may be
   updated only with the identical installer bytes, checksum, and version.

Unsigned artifacts from pull requests and ordinary workflow runs are retained
only as short-lived test artifacts. They are not public releases and must not
be presented as trusted-publisher installers.

## Signing-key protection

The Authenticode private key is generated and retained by SignPath in managed
hardware security infrastructure. It is not exported to this repository or to
GitHub Actions. The separate Tauri updater private key is stored only as an
encrypted GitHub Actions secret and in an access-controlled maintainer backup;
it is never committed, logged, uploaded as a build artifact, or included in an
installer.

## Artifact restrictions

Signed executable metadata must identify the product as `DroneDream`, and all
product/file versions in one release must match the approved release version.
The signing configuration must reject unexpected executable names or product
metadata. Third-party binaries must not be re-signed as DroneDream binaries.

The release workflow and all scripts that determine signed contents are owned
by `@ChiZhang-805` through `.github/CODEOWNERS`. Changes to this policy, the
privacy policy, the release workflow, signing configuration, installer, or
release scripts require code-owner review.

## Privacy and security

DroneDream's data handling and network behavior are documented in the
[Privacy policy](PRIVACY.md). Vulnerability reporting and the simulation-safety
boundary are documented in the [Security policy](SECURITY.md).

Questions about this policy may be sent to **cz005623@gmail.com**.
