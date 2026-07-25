# Security policy

Release signatures follow the repository's
[Code signing policy](CODE_SIGNING_POLICY.md). Local data, optional network
connections, third-party providers, and deletion behavior are documented in
the [Privacy policy](PRIVACY.md).

## Supported releases

DroneDream is currently a development preview. Security fixes are applied to
the newest source revision and the newest published desktop installer only.
Older preview installers and Runtime images should be upgraded rather than
kept in service.

## Reporting a vulnerability

Please do not open a public issue for an unpatched vulnerability, exposed
credential, unsafe archive, path traversal, authentication bypass, or command
execution problem. Email **cz005623@gmail.com** with:

- the affected version or commit;
- the operating system and deployment mode;
- concise reproduction steps;
- the expected and observed result; and
- any logs or proof of concept with secrets removed.

You should receive an acknowledgement within seven days. Please allow a
reasonable remediation and release window before public disclosure.

## Safety boundary

DroneDream automates simulation and optimization around PX4 and Gazebo. Its
outputs are research artifacts, not flight certification. A parameter set that
passes SITL can still be unsafe on real hardware because of unmodelled
dynamics, sensor faults, actuator limits, environmental effects, or integration
differences. Validate recommendations in progressively more realistic,
controlled environments and follow the vehicle, airspace, and operator safety
requirements that apply to you.

The product treats advanced environment effects as present only when the
launcher returns verifiable evidence that they were physically injected. A UI
selection or configuration value alone is not proof of a simulated effect.

## Credential handling

- Never commit API keys, signing certificates, SSH keys, access tokens, or
  production `.env` files.
- Use the encrypted job-secret path for model-provider credentials.
- Keep authentication enabled on every network-accessible deployment.
- Verify installer and Runtime SHA-256 values; use signed release manifests
  when publishing Runtime images. Runtime Ed25519 signatures do not sign the
  Windows executable. The `1.0.0` release candidate must not be presented as a
  trusted-publisher release until the exact NSIS bytes pass Authenticode
  verification.

## Audited dependency exception

The frontend is a browser-only Vite single-page application built with
`createBrowserRouter`. It does not install or enable React Router's RSC or
server-runtime packages. The dependency gate therefore records
`GHSA-qwww-vcr4-c8h2` as non-applicable while this architecture remains true:
that advisory concerns React Server Components action handling. The audit
script pins the reviewed React Router version, refuses the exception if an RSC
package is added, and continues to fail on every other high or critical npm
advisory.
