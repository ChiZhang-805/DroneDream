# Account authentication and data isolation

## Decision

DroneDream uses two explicit operating modes:

- **Public signed Windows application** requires a Supabase account. Supabase
  Auth supplies the access token, while the bundled local Runtime and database
  remain the experiment execution boundary. The startup screen cannot report
  100% or expose the tuning-platform entry until the Runtime is ready, the
  signed update check has completed, and `GET /api/v1/session` accepts the
  current account identity.
- **Local development/test workspace** may explicitly omit Supabase and use
  disabled or demo authentication. This exception is not a shippable desktop
  configuration and must never be used to make a public build appear ready.

New users register with an email address, a password, and the verification
code sent to that address; returning users sign in with email and password.
Google can be enabled for the browser deployment after its OAuth callback is
configured. SMS is excluded from the first release because it adds provider
cost and abuse controls.

The product must never display a successful cloud sign-in while continuing to
query unscoped local or cloud records. Authentication and tenant filtering are
one release gate.

## Implemented foundation

The backend already has the required ownership model:

- `users` keys an OIDC identity by immutable `(issuer, subject)`.
- `jobs` and `batch_jobs` carry `user_id`.
- job, trial, batch, and artifact reads enforce the current owner.
- production rejects `AUTH_MODE=disabled`.
- `AUTH_MODE=oidc_jwt` verifies asymmetric JWT signatures, issuer, audience,
  expiry, and subject through the configured JWKS endpoint.

The frontend has a Supabase account layer for public desktop builds:

- no Supabase environment variables means an honest local-development
  workspace; a formal signed desktop build must fail before release when those
  public variables are absent;
- email verification creates one password-protected account per verified
  email, and the registration form keeps the code field visible from the
  beginning;
- a Supabase access token is attached to API requests in memory;
- the backend identity probe must accept the same immutable account subject
  before the startup gate can reach 100%;
- unfinished experiment drafts are redacted and mirrored into persistent local
  storage so a normal app exit or restart can restore them;
- an explicit desktop exit asks the backend to cancel known active jobs, then
  terminates only the dedicated `DroneDreamRuntime` WSL distribution with a
  bounded command before destroying the window; it never issues a global WSL
  shutdown or targets the user's other distributions;
- signing out or changing accounts clears the unfinished experiment draft to
  prevent cross-account disclosure;
- the desktop refresh-token session uses `sessionStorage` until an
  OS-keychain-backed Tauri storage adapter is added;
- Google and Apple buttons are build flags and stay hidden in the desktop
  WebView until its signed deep-link callback is implemented.

Model access remains separate from account authentication:

- included DroneDream model access uses a short-lived, purpose-scoped gateway
  grant; the platform provider key exists only in an Edge Function secret;
- BYOK credentials remain memory-only and are never placed in an experiment
  draft or persistent browser storage.

The quota, grant, and payment boundary is documented in
[21 Managed Model Access, Allowances, and Billing](./21-managed-model-access-and-billing.md).

## Configuration contract

Frontend build variables:

```dotenv
VITE_SUPABASE_URL=https://PROJECT_REF.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
VITE_TURNSTILE_SITE_KEY=public_site_key
VITE_AUTH_GOOGLE_ENABLED=false
VITE_AUTH_APPLE_ENABLED=false
```

Backend runtime variables:

```dotenv
APP_ENV=desktop
AUTH_MODE=oidc_jwt
OIDC_ISSUER=https://PROJECT_REF.supabase.co/auth/v1
OIDC_AUDIENCE=authenticated
OIDC_JWKS_URL=https://PROJECT_REF.supabase.co/auth/v1/.well-known/jwks.json
OIDC_ALGORITHMS=RS256,ES256
```

The publishable frontend key is expected to be public. Never place the
Supabase service-role key, SMTP password, OAuth client secret, personal
password, or any signing key in frontend variables or the repository.

## Human configuration required

1. Create the Supabase project and choose its data region.
2. Enable email and password sign-in, require email confirmation, and change
   the confirmation template to show the one-time token used by the in-app
   registration code field.
3. For testing, use Supabase's included email delivery within its limits. For
   public release, connect a dedicated sender domain and custom SMTP provider
   such as Resend, Postmark, Amazon SES, or another provider chosen by the
   operator.
4. Create a Cloudflare Turnstile widget for the production domains, copy its
   public site key into the frontend build variables, deploy that build, and
   only then enable CAPTCHA in Supabase Auth with the private secret key.
5. Add the production website URL and allowed redirect URLs.
6. Copy only the project URL, publishable key, and Turnstile public site key
   into the frontend build variables. The packaged local Runtime receives only
   the public OIDC verifier configuration above; it never receives a Supabase
   service-role key.
7. Confirm the project uses an asymmetric signing key compatible with the
   JWKS verifier, then run the cross-user isolation acceptance tests.
8. If Google login is wanted, create a Google OAuth web client, register the
   Supabase callback URL, add its client ID and secret in Supabase, then set
   `VITE_AUTH_GOOGLE_ENABLED=true` for the browser build.
9. Defer Apple login until an Apple Developer account, Services ID, verified
   domain, redirect URL, and secret-rotation owner are ready.

No mailbox password is needed. The operator configures the SMTP provider
inside Supabase; DroneDream receives only the resulting authenticated session.

## Isolation acceptance gate

Before cloud accounts appear in a public build:

1. User A creates a job and can list, open, download, rerun, and delete it.
2. User B cannot discover User A's job through list filters or guessed IDs.
3. User B receives a not-found or forbidden response for User A's trials,
   artifacts, reports, batches, and downloads.
4. A normal close/restart restores the redacted unfinished five-step draft;
   signing out clears it.
5. Signing in as another user does not reveal the previous account's jobs,
   model API key, draft, or cached artifact URL.
6. Expired, wrong-audience, wrong-issuer, unsigned, and symmetric-algorithm
   tokens fail closed.
7. Local-only development mode remains available without pretending that it is
   a public signed build or that its data is synced to a cloud account.

## Storage direction for the initial user count

For roughly fifty users, do not create one physical database per user. Use one
managed PostgreSQL database, immutable OIDC identities, indexed `user_id`
columns, API ownership checks, and private object storage. This is easier to
back up, migrate, observe, and operate while still isolating records. Separate
databases are justified later only by regulatory, regional, or enterprise
contract requirements.

Local data and cloud data must remain visibly distinct until a deliberate sync
protocol exists. A future sync design needs stable record IDs, per-record
ownership, conflict rules, encrypted transfer, deletion propagation, and an
offline queue; login alone is not synchronization.
