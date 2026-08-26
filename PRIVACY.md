# DroneDream privacy policy

Effective date: July 20, 2026

DroneDream is a local-first, open-source PX4 and Gazebo experiment application.
The desktop application does not include first-party advertising, behavioral
analytics, crash-reporting telemetry, or a DroneDream cloud account. Local use
does not automatically transmit experiment results to the project maintainer.

## Data kept on the user's computer

DroneDream may keep the following data on the computer where it runs:

- application language, model-provider name, model name, and compatible API
  base URL;
- active-session experiment drafts, excluding model API keys;
- jobs, parameters, tracks, scenarios, metrics, run history, logs, simulation
  telemetry, reports, and other experiment artifacts;
- local Runtime installation state, diagnostics, and application/WebView
  caches; and
- a model-provider API key during the current application session and, when a
  model-guided job is created, an encrypted per-job copy in the local backend
  database until that job reaches a terminal state.

Experiment drafts use session storage and are discarded when the application
session ends. Provider, model, and base-URL preferences may persist between
sessions. Model API keys are excluded from drafts and persistent preference
storage. The backend removes the encrypted per-job API key when the job
finishes, fails, or is cancelled.

## Network connections

DroneDream transfers information to another networked system only for an
operation requested or configured by the user or person installing the
software. Depending on the selected features, those connections may include:

- GitHub Releases, to check for application updates and to download the signed
  DroneDreamRuntime release manifest and Runtime files;
- Microsoft, to install the WebView2 runtime when it is missing from the
  Windows computer;
- OpenAI or another OpenAI-compatible provider selected by the user, when the
  user chooses an LLM-guided optimizer; the request contains the engineering
  context needed to propose parameters and is governed by that provider's own
  terms and privacy policy;
- a backend, object store, identity provider, or Gazebo/noVNC endpoint
  explicitly configured by the operator for a non-local deployment; and
- external documentation or course pages that the user chooses to open.

Local application traffic normally stays on the loopback interface between
the desktop UI and the local DroneDream backend. The project website fetches
release metadata from its own server and does not use first-party analytics.

## User control and deletion

Users can avoid third-party model-provider traffic by selecting a keyless
optimizer. Cancelling or completing an LLM-guided job purges its encrypted API
key. Run history and artifacts can be deleted through the application where
the corresponding controls are available, or by deleting the local
DroneDream data directories.

Uninstalling the desktop application removes the installed program but may
preserve diagnostics, experiment data, and the independently installed
DroneDreamRuntime so an accidental uninstall does not destroy user work.
Users who want complete removal must also delete the DroneDream application
data and explicitly remove the dedicated `DroneDreamRuntime` WSL distribution.
The installer never unregisters an unrelated Ubuntu or WSL distribution.

## Remote deployments

People who operate a shared or public DroneDream deployment are independent
operators responsible for authentication, access control, retention,
encryption, backups, user notices, and compliance for that deployment. This
repository does not claim that an operator's deployment follows this local
desktop policy.

## Security

API keys and other credentials must not be committed to the repository or
included in reports. Network-accessible deployments must use authentication
and TLS. Security issues should be reported according to the
[Security policy](SECURITY.md).

Questions or deletion guidance requests may be sent to
**cz005623@gmail.com**.
