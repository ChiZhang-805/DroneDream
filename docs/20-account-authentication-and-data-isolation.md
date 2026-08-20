# Account authentication and data isolation

## Decision

DroneDream uses two explicit operating modes:

- **Local workspace** is the default for the signed Windows application. It
  uses the local Runtime and local database, does not require an Internet
  account, and keeps the current experiment draft only for the current app
  session.
- **Cloud workspace** is opt-in. It uses Supabase Auth as the identity
  provider and DroneDream's authenticated API as the data boundary. The web
  deployment owns email/password registration and sign-in. The signed desktop
  application never collects those credentials inside its WebView: it opens
  the system browser, completes an edition-bound authorization-code + PKCE
  flow, and adopts only the resulting session. Google can be enabled for the
  browser deployment after its OAuth callback is configured. SMS is excluded
  from the first release because it adds provider cost and abuse controls.

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

The frontend now has an optional Supabase account layer:

- no Supabase environment variables means an honest local-only workspace;
- email verification creates one password-protected account per verified
  email, and the registration form keeps the code field visible from the
  beginning;
- a Supabase access token is attached to API requests in memory;
- signing out or changing accounts clears the unfinished experiment draft;
- desktop browser authorization uses a fixed per-edition loopback callback,
  validates state, nonce, audience and PKCE, and rejects redirect or token
  contracts that do not match the compiled public client;
- the desktop refresh grant is stored only in the edition-specific Windows
  Credential Manager namespace; the WebView receives the adopted session but
  never persists the grant in browser storage;
- a failed WebView adoption clears only that edition's unusable vault entry so
  a later explicit sign-in cannot loop on stale credentials; and
- Google and Apple buttons remain browser-deployment build flags. Desktop
  sign-in delegates provider interaction to the system browser instead of
  embedding provider credentials in the WebView.

The model API key remains separate from account authentication. It is never
placed in an experiment draft or persistent browser storage.

## Configuration contract

Frontend build variables:

```dotenv
VITE_SUPABASE_URL=https://PROJECT_REF.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
VITE_AUTH_GOOGLE_ENABLED=false
VITE_AUTH_APPLE_ENABLED=false
```

Desktop release build variables are public application identifiers, not
secrets. Each edition has a separately registered loopback callback and must
be compiled with its own provider-issued client ID:

```text
DRONEDREAM_OAUTH_CLIENT_ID_UNIVERSAL
DRONEDREAM_OAUTH_CLIENT_ID_SIM
DRONEDREAM_OAUTH_CLIENT_ID_LAB
DRONEDREAM_OAUTH_CLIENT_ID_FIELD
```

Backend runtime variables:

```dotenv
APP_ENV=production
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
4. Add the production website URL and allowed redirect URLs.
5. Copy only the project URL and publishable key into the frontend build
   secrets. Configure the backend OIDC values above in server secrets.
6. Confirm the project uses an asymmetric signing key compatible with the
   JWKS verifier, then run the cross-user isolation acceptance tests.
7. If Google login is wanted, create a Google OAuth web client, register the
   Supabase callback URL, add its client ID and secret in Supabase, then set
   `VITE_AUTH_GOOGLE_ENABLED=true` for the browser build.
8. Defer Apple login until an Apple Developer account, Services ID, verified
   domain, redirect URL, and secret-rotation owner are ready.
9. Register the four public desktop OAuth clients with their exact edition
   loopback callbacks, enter only the public client IDs as GitHub repository
   variables, and run
   `desktop/scripts/verify-five-edition-oauth-registration.ps1` before a signed
   release. An unsigned validation build may use an explicit unregistered
   placeholder to exercise layout and routing, but it cannot complete a real
   account sign-in with that placeholder.

No mailbox password is needed. The operator configures the SMTP provider
inside Supabase; DroneDream receives only the resulting authenticated session.

## Isolation acceptance gate

Before cloud accounts appear in a public build:

1. User A creates a job and can list, open, download, rerun, and delete it.
2. User B cannot discover User A's job through list filters or guessed IDs.
3. User B receives a not-found or forbidden response for User A's trials,
   artifacts, reports, batches, and downloads.
4. Signing out clears the unfinished conversation and five-step draft.
5. Signing in as another user does not reveal the previous account's jobs,
   model API key, draft, or cached artifact URL.
6. Expired, wrong-audience, wrong-issuer, unsigned, and symmetric-algorithm
   tokens fail closed.
7. Local-only mode remains available without pretending that its data is
   synced to a cloud account.

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
