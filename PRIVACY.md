# DroneDream privacy policy

Effective date: July 25, 2026

DroneDream is a local-first, open-source PX4 and Gazebo experiment application.
The signed desktop application can be used without a DroneDream cloud account.
The public website separately offers an optional Supabase-backed account and
community. Local desktop use does not automatically upload experiment results
to the website operator or to the community.

Questions, account-deletion requests, community-data deletion requests, and
privacy requests may be sent to **cz005623@gmail.com**.

## Public website accounts

When a person creates or uses a website account, Supabase Auth processes the
email address, password authentication material, verification events, immutable
user identifier, session data, and account metadata such as the display name.
Passwords are handled by Supabase Auth and are not stored in this repository.
Authentication emails are delivered through the configured transactional email
provider.

The browser keeps the signed-in session in origin-scoped local storage so the
user can remain signed in. The current profile image is also stored only in that
browser's local storage and is not yet synchronized between devices. Signing
out removes the Supabase session through the Auth service.

## Public community

Community topics, comments, display names, tags, likes, timestamps, and uploaded
images are intentionally public. A person should not publish private keys,
passwords, precise personal locations, confidential flight data, or another
person's personal information.

Supabase Postgres stores community text and relationships. Supabase Storage
stores community images. Row-level security limits authenticated writes to the
signed-in identity, while community reads are public. Content may be removed
when requested by its author, when required for safety or legal reasons, or when
it violates the community guidelines.

Account and community data are retained while the account or content remains
active. Deletion requests are handled within a reasonable operational period.
Provider backups, security logs, abuse records, and delivery logs may persist
for a limited additional period under the provider's retention practices or
where required for security and legal compliance.

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

Experiment drafts use session storage in the desktop application and are
discarded when the application session ends. Provider, model, and base-URL
preferences may persist between sessions. Model API keys are excluded from
drafts and persistent preference storage. The backend removes the encrypted
per-job API key when the job finishes, fails, or is cancelled.

The public demonstration console stores unfinished experiment drafts and
workspace preferences in that browser. Those demonstration drafts are not
uploaded to Supabase and are not cloud simulation jobs.

## Network connections and service providers

DroneDream transfers information to another networked system only for an
operation requested or configured by the user or the website operator.
Depending on the selected features, those connections may include:

- GitHub Pages, to deliver the public website, and GitHub Releases, to check
  for updates and download release files;
- Supabase, to provide website authentication, database APIs, row-level
  authorization, and community image storage;
- the configured transactional email provider, to deliver account
  verification and account-recovery messages;
- Microsoft, to install the WebView2 runtime when it is missing;
- OpenAI or another OpenAI-compatible provider selected by the desktop user,
  when the user explicitly chooses an LLM-guided feature; and
- external documentation or course pages that the user chooses to open.

These providers may process normal service metadata such as IP address,
request time, user agent, delivery status, and security events. They may
process data in countries other than the user's country. Their own terms,
privacy policies, security measures, and retention practices also apply.

The DroneDream desktop application does not include first-party advertising.
The website does not currently use first-party advertising or behavioral
analytics.

## User control and deletion

Users can avoid website account and community processing by using the local
desktop application without signing in. They can avoid third-party
model-provider traffic by selecting a keyless optimizer.

Run history and artifacts can be deleted through the desktop application where
the corresponding controls are available, or by deleting the local DroneDream
data directories. Uninstalling the desktop application removes the installed
program but may preserve diagnostics, experiment data, and the independently
installed DroneDreamRuntime so an accidental uninstall does not destroy user
work. Complete removal also requires deleting the DroneDream application data
and explicitly removing the dedicated `DroneDreamRuntime` WSL distribution.

To request deletion of a website account or community content when an in-product
control is unavailable, contact the address at the top of this policy from the
account's verified email address.

## Children

The public account and community are not directed to children. A person who is
not legally able to consent to this processing should not create an account or
publish community content without the authorization required in their
jurisdiction.

## Remote deployments

People who operate a separate shared or public DroneDream deployment are
independent operators responsible for authentication, access control,
retention, encryption, backups, user notices, and compliance for that
deployment. This policy describes the official project website and signed
desktop release, not every third-party deployment.

## Security

API keys and other credentials must not be committed to the repository or
included in reports or community posts. Network-accessible deployments must
use authentication and TLS. Security issues should be reported according to
the [Security policy](SECURITY.md).

This policy may be updated as the public website, providers, or data practices
change. Material changes will be reflected by a new effective date.
