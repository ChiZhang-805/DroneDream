# Managed Model Access, Allowances, and Billing

## Product contract

Free, Plus, and Pro expose the same `core-v1` DroneDream product:

- the same desktop tuning workflow;
- the same Harness, optimizers, simulator integration, and reports;
- the same experiment assistant, community, manuals, and updates.

They differ only in monthly included managed-model credits and price. When the
included allowance cannot reserve the next request, the gateway fails closed
with `MODEL_QUOTA_EXHAUSTED`; the user must switch to BYOK or purchase a larger
allowance. No optimizer or Harness capability is hidden behind a paid tier.

The migration seeds these operator-editable launch defaults:

| Plan | Monthly price | Included credits |
| --- | ---: | ---: |
| Free | ¥0 | 100,000 |
| Plus | ¥20 | 1,000,000 |
| Pro | ¥200 | 5,000,000 |

These are launch configuration defaults, not hard-coded commercial promises.
The authoritative rows live in `public.model_subscription_plans`; the website
loads them from the billing Edge Function and uses its embedded values only as
an offline fallback.

## Trust boundary

```text
Signed-in website/desktop
        |
        | Supabase user access token
        v
model-gateway Edge Function ---- service role ---- quota/grant ledger
        |
        | server-only provider API key
        v
OpenAI-compatible model provider

Signed-in website
        |
        | create order
        v
billing-checkout Edge Function ---- payment provider
        ^                                  |
        | signed + verified callback       |
        +----------------------------------+
                         |
                         v
                 paid entitlement
```

The platform provider key, Supabase service-role key, payment signing keys, and
wallet API secrets must never enter Vite variables, desktop files, the local
Runtime, repository history, browser storage, or an API response.

The frontend receives only:

- a public Supabase URL and publishable key;
- a Supabase account session;
- a short-lived `ddg_...` grant returned once for `assistant` or `job`;
- an allowance snapshot and payment checkout target.

Only the grant's SHA-256 hash is stored in Supabase. Job grants are encrypted in
the local backend's existing `JobSecret` boundary and never returned in job
payloads.

## Credit settlement

Credit policy version 1 uses:

```text
actual credits = input tokens + output tokens × output weight
```

The default output weight is `4`. The model provider's reported token counts
are authoritative when they are complete and internally consistent.

Before a provider call, the gateway atomically reserves a conservative ceiling:

```text
reserved credits =
  serialized UTF-8 request bytes
  + configured maximum output tokens × output weight
```

This prevents concurrent calls from overspending one allowance. After a
successful response, the reservation is replaced with actual credits. If the
provider omits reliable usage, the conservative reservation is charged and the
receipt is marked `usage_estimated=true`; the settings dashboard shows the
number of estimated requests. Provider/network failures release the
reservation. Abandoned reservations expire after 15 minutes and are reclaimed
when usage is viewed or a new grant/request is made.

Each deliberate client request includes an idempotency key. Reusing one key
cannot create a second charge. A completed response is not cached, so a caller
that loses the response receives a fail-closed idempotency conflict instead of
being charged twice.

## Database objects

Migration:

`supabase/migrations/20260726060000_create_model_access_billing.sql`

The migration creates:

- `model_subscription_plans`;
- `account_entitlements`;
- `model_usage_periods`;
- `model_gateway_grants`;
- `model_usage_requests`;
- `payment_orders`;
- `payment_webhook_events`.

All tables use RLS. Users may read only their own entitlement, usage, request
receipts, and orders. There is no client policy for grants or webhook events.
All mutating RPCs are `SECURITY DEFINER`, pin `search_path`, revoke `public`,
and grant execution only to `service_role`.

Paid entitlements are changed only by `billing_mark_order_paid`, which is
called after an Edge Function verifies the provider signature, merchant/app
identity, order, amount, currency, payment state, and event idempotency.
Browser redirects and QR display never activate a plan.

One checkout buys one month. Renewal is manual. Early renewal of the same plan
extends the entitlement while retaining separate monthly allowance periods. A
plan change becomes effective immediately, preserves the remaining paid
duration, and adds the purchased month.

## Edge Function routes

### `model-gateway`

| Method and path | Credential | Purpose |
| --- | --- | --- |
| `GET /usage` | Supabase user JWT | Read current plan, period, totals, and recent receipts |
| `POST /grants` | Supabase user JWT | Issue a short-lived scoped grant |
| `POST /chat/completions` | Opaque `ddg_` grant | Make a bounded OpenAI-compatible model call |

The gateway fixes the upstream base URL, provider, model, maximum output, and
credit policy from server secrets. Client attempts to choose an upstream model
are ignored. Upstream model names, fingerprints, credentials, and raw error
payloads are not exposed.

### `billing-checkout`

| Method and path | Credential | Purpose |
| --- | --- | --- |
| `GET /availability` | Public | Read active plans and honestly enabled channels |
| `POST /create` | Supabase user JWT | Create a server-priced Plus/Pro order |
| `POST /webhooks/alipay` | Alipay RSA2 signature | Verify and activate an Alipay payment |
| `POST /webhooks/wechat` | WeChat platform signature + APIv3 encryption | Verify and activate a WeChat payment |

`verify_jwt=false` in `supabase/config.toml` is intentional. Supabase's generic
JWT pre-check would reject opaque model grants and payment-provider callbacks.
Each route implements its own narrower credential check.

## Server secrets

Supabase automatically supplies its project URL and service-role key to deployed
Edge Functions. Configure the remaining values only through Supabase Edge
Function secrets or another server-side secret manager.

Model gateway:

```dotenv
MODEL_GATEWAY_ALLOWED_ORIGINS=https://getdronedream.com,https://www.getdronedream.com,http://tauri.localhost,tauri://localhost
PLATFORM_LLM_API_KEY=server-only
PLATFORM_LLM_BASE_URL=https://provider.example/v1
PLATFORM_LLM_MODEL=provider-model-id
PLATFORM_LLM_MODEL_ALIAS=DroneDream Managed
PLATFORM_LLM_PROVIDER=provider-ledger-name
PLATFORM_LLM_MAX_OUTPUT_TOKENS=2048
PLATFORM_LLM_OUTPUT_CREDIT_WEIGHT=4
PLATFORM_LLM_CREDIT_POLICY_VERSION=1
PLATFORM_LLM_TIMEOUT_MS=90000
```

Billing common:

```dotenv
BILLING_ALLOWED_ORIGINS=https://getdronedream.com,https://www.getdronedream.com,http://tauri.localhost,tauri://localhost
PAYMENTS_ENABLED=false
```

Alipay:

```dotenv
ALIPAY_APP_ID=
ALIPAY_MERCHANT_PRIVATE_KEY_PKCS8=
ALIPAY_PUBLIC_KEY_SPKI=
ALIPAY_SELLER_ID=
ALIPAY_NOTIFY_URL=https://PROJECT_REF.supabase.co/functions/v1/billing-checkout/webhooks/alipay
ALIPAY_RETURN_URL=https://getdronedream.com/pricing/
```

WeChat Pay:

```dotenv
WECHAT_APP_ID=
WECHAT_MCH_ID=
WECHAT_MERCHANT_CERT_SERIAL=
WECHAT_MERCHANT_PRIVATE_KEY_PKCS8=
WECHAT_PLATFORM_CERTIFICATE_SERIAL=
WECHAT_PLATFORM_PUBLIC_KEY_SPKI=
WECHAT_API_V3_KEY=
WECHAT_NOTIFY_URL=https://PROJECT_REF.supabase.co/functions/v1/billing-checkout/webhooks/wechat
```

Keep `PAYMENTS_ENABLED=false` until sandbox/low-value end-to-end callbacks have
passed. The availability endpoint still returns plans, but every checkout
button remains honestly disabled unless the selected channel has every
required secret.

WeChat platform certificates rotate. The configured platform certificate
serial/public key must be updated before expiry; otherwise response and callback
verification intentionally fails closed.

## Deployment sequence

1. Review and approve the plan prices, included credits, output weight, model,
   maximum output, and allowed origins.
2. Link the Supabase CLI to the production project.
3. Apply the migration:

   ```powershell
   npx supabase db push
   ```

4. Deploy both functions from the repository root:

   ```powershell
   npx supabase functions deploy model-gateway
   npx supabase functions deploy billing-checkout
   ```

5. Add secrets through the Supabase dashboard or an untracked, access-restricted
   environment file outside the repository.
6. Build website and desktop with:

   ```dotenv
   VITE_SUPABASE_URL=https://PROJECT_REF.supabase.co
   VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
   ```

   The Edge URLs are derived automatically. `VITE_MODEL_GATEWAY_URL` and
   `VITE_BILLING_CHECKOUT_URL` are optional explicit public URL overrides.

7. With payments still disabled, test Free allowance, exact usage settlement,
   estimated settlement, concurrent quota exhaustion, stale recovery, and BYOK
   switching using two separate accounts.
8. Complete merchant onboarding and test each provider's sandbox or smallest
   permitted live amount. Confirm that a browser return without a verified
   callback does not activate a plan, while one verified callback activates it
   exactly once.
9. Set `PAYMENTS_ENABLED=true`, recheck `/availability`, and perform a monitored
   real purchase/refund run before public announcement.

## Merchant and card-payment prerequisites

The code supports Alipay computer-website payment and WeChat Native QR payment,
but code cannot create merchant eligibility:

- WeChat's official onboarding material supports ordinary merchants. Its
  partner-assisted small/micro-merchant flow can accept an operator identity,
  personal settlement bank card, and evidence of the real online business, but
  it must be submitted through a qualified service provider and approved.
- Direct WeChat App payment has an additional AppID binding and published-app
  review path. DroneDream therefore uses website Native QR payment first.
- Alipay website payment still requires an approved Alipay application and
  merchant product contract. A personal Alipay login alone is not sufficient
  evidence that computer-website payment is available; confirm the account's
  eligible merchant type in the Alipay console before enabling it.
- True wallet auto-renewal requires separate entrusted-deduction products,
  agreements, cancellation UX, and provider review. This implementation uses
  one-month manual renewal and must not be marketed as automatic renewal.

International cards are deliberately not implemented yet. Stripe supports Hong
Kong, but opening a Hong Kong account requires a real eligible Hong Kong
business/account configuration, identity and entity verification, and a payout
bank account. A mainland personal operator should not select Hong Kong merely
to bypass onboarding. Add card checkout only after a valid merchant entity is
chosen; then use a hosted checkout and webhook flow rather than handling card
numbers in DroneDream.

Official references:

- Supabase Edge Function secrets:
  <https://supabase.com/docs/guides/functions/secrets>
- Supabase Edge Function authentication:
  <https://supabase.com/docs/guides/functions/auth>
- WeChat Pay merchant onboarding:
  <https://pay.wechatpay.cn/static/applyment_guide/applyment_index.shtml>
- WeChat Pay small/micro-merchant preparation:
  <https://pay.wechatpay.cn/doc/v3/partner/4012165177>
- WeChat Pay App permission:
  <https://pay.wechatpay.cn/doc/v3/merchant/4013070174>
- WeChat Pay entrusted deduction:
  <https://pay.wechatpay.cn/doc/v2/merchant/4012205799>
- Alipay web/mobile application:
  <https://open.alipay.com/module/webApp>
- Stripe global availability:
  <https://stripe.com/global>
- Stripe verification documents:
  <https://docs.stripe.com/acceptable-verification-documents?country=HK>

## Validation gates

Before release, all of the following must be green:

- frontend TypeScript, ESLint, dependency audit, and complete Vitest suite;
- backend Ruff, mypy, and complete pytest suite;
- Runtime pytest suite;
- Deno `check` and `lint` for both Edge Functions;
- PostgreSQL migration syntax parse and a real linked Supabase migration;
- two-user RLS isolation;
- concurrent quota reservation and stale-reservation recovery;
- provider token-accounting receipt comparison;
- Alipay/WeChat signature, amount, currency, replay, and callback idempotency;
- website desktop/mobile screenshots;
- one monitored live payment and one refund/reconciliation exercise.

Local source validation does not substitute for the linked Supabase migration,
merchant approval, provider credentials, or real callback tests.
