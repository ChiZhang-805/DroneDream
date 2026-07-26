-- Managed model allowance, entitlement, and payment-order foundation.
--
-- Product contract:
--   * Free, Plus, and Pro expose the same DroneDream capability set.
--   * The plans differ only in included managed-model credits (and price).
--   * Once included credits are exhausted, model calls fail closed and the
--     desktop can ask the customer to use BYOK instead.
--
-- Provider credentials and payment secrets never live in these tables. They
-- are Supabase Edge Function secrets. Grants are stored only as SHA-256 hashes.

create table if not exists public.model_subscription_plans (
  plan_id text primary key,
  display_name text not null unique,
  display_rank integer not null unique,
  monthly_price_cny_fen integer not null check (monthly_price_cny_fen >= 0),
  included_ai_credits bigint not null check (included_ai_credits >= 0),
  capability_set text not null default 'core-v1'
    check (capability_set = 'core-v1'),
  credit_policy_version integer not null default 1
    check (credit_policy_version > 0),
  active boolean not null default true,
  updated_at timestamptz not null default now(),
  constraint model_subscription_plans_known_plan
    check (plan_id in ('free', 'plus', 'pro'))
);

insert into public.model_subscription_plans (
  plan_id,
  display_name,
  display_rank,
  monthly_price_cny_fen,
  included_ai_credits,
  capability_set,
  credit_policy_version
)
values
  ('free', 'Free', 1, 0, 300000, 'core-v1', 1),
  ('plus', 'Plus', 2, 3900, 3000000, 'core-v1', 1),
  ('pro', 'Pro', 3, 12900, 15000000, 'core-v1', 1)
on conflict (plan_id) do update
set
  display_name = excluded.display_name,
  display_rank = excluded.display_rank,
  monthly_price_cny_fen = excluded.monthly_price_cny_fen,
  included_ai_credits = excluded.included_ai_credits,
  capability_set = excluded.capability_set,
  credit_policy_version = excluded.credit_policy_version,
  active = true,
  updated_at = now();

create table if not exists public.account_entitlements (
  user_id uuid primary key references auth.users(id) on delete cascade,
  plan_id text not null references public.model_subscription_plans(plan_id),
  status text not null default 'active'
    check (status in ('active', 'past_due', 'cancelled')),
  current_period_start timestamptz not null,
  current_period_end timestamptz not null,
  cancel_at_period_end boolean not null default false,
  source text not null default 'free'
    check (source in ('free', 'payment', 'admin')),
  payment_provider text
    check (
      payment_provider is null
      or payment_provider in ('alipay', 'wechat', 'card')
    ),
  provider_subscription_reference text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (current_period_end > current_period_start),
  check (
    (plan_id = 'free' and payment_provider is null)
    or plan_id in ('plus', 'pro')
  )
);

create table if not exists public.model_usage_periods (
  period_id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  plan_id text not null references public.model_subscription_plans(plan_id),
  period_start timestamptz not null,
  period_end timestamptz not null,
  included_ai_credits bigint not null check (included_ai_credits >= 0),
  reserved_ai_credits bigint not null default 0 check (reserved_ai_credits >= 0),
  consumed_ai_credits bigint not null default 0 check (consumed_ai_credits >= 0),
  request_count bigint not null default 0 check (request_count >= 0),
  input_tokens bigint not null default 0 check (input_tokens >= 0),
  output_tokens bigint not null default 0 check (output_tokens >= 0),
  total_tokens bigint not null default 0 check (total_tokens >= 0),
  estimated_request_count bigint not null default 0
    check (estimated_request_count >= 0),
  credit_policy_version integer not null check (credit_policy_version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, period_start, period_end),
  check (period_end > period_start)
);

create index if not exists model_usage_periods_user_end_idx
  on public.model_usage_periods (user_id, period_end desc);

create table if not exists public.model_gateway_grants (
  grant_id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  token_sha256 text not null unique
    check (token_sha256 ~ '^[0-9a-f]{64}$'),
  scope text not null check (scope in ('assistant', 'job')),
  scope_reference text check (
    scope_reference is null
    or (
      length(scope_reference) between 1 and 128
      and scope_reference ~ '^[A-Za-z0-9_.:-]+$'
    )
  ),
  max_calls integer not null check (max_calls between 1 and 256),
  used_calls integer not null default 0 check (used_calls >= 0),
  expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  check (used_calls <= max_calls)
);

create index if not exists model_gateway_grants_user_expiry_idx
  on public.model_gateway_grants (user_id, expires_at desc);

create table if not exists public.model_usage_requests (
  request_id uuid primary key,
  request_key text not null
    check (length(request_key) between 8 and 128),
  user_id uuid not null references auth.users(id) on delete cascade,
  grant_id uuid not null references public.model_gateway_grants(grant_id)
    on delete restrict,
  period_id uuid not null references public.model_usage_periods(period_id)
    on delete restrict,
  purpose text not null check (purpose in ('assistant', 'job')),
  provider text not null check (length(provider) between 1 and 64),
  model text not null check (length(model) between 1 and 128),
  status text not null default 'reserved'
    check (status in ('reserved', 'completed', 'failed', 'expired')),
  reserved_ai_credits bigint not null check (reserved_ai_credits > 0),
  consumed_ai_credits bigint check (
    consumed_ai_credits is null or consumed_ai_credits >= 0
  ),
  input_tokens bigint check (input_tokens is null or input_tokens >= 0),
  output_tokens bigint check (output_tokens is null or output_tokens >= 0),
  total_tokens bigint check (total_tokens is null or total_tokens >= 0),
  usage_estimated boolean not null default false,
  output_credit_weight integer not null check (output_credit_weight between 1 and 100),
  credit_policy_version integer not null check (credit_policy_version > 0),
  provider_request_id text check (
    provider_request_id is null or length(provider_request_id) <= 255
  ),
  error_code text check (error_code is null or length(error_code) <= 128),
  reservation_expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  settled_at timestamptz,
  unique (user_id, request_key),
  check (
    (status = 'reserved' and settled_at is null and consumed_ai_credits is null)
    or (status <> 'reserved' and settled_at is not null)
  )
);

create index if not exists model_usage_requests_user_created_idx
  on public.model_usage_requests (user_id, created_at desc);
create index if not exists model_usage_requests_reserved_expiry_idx
  on public.model_usage_requests (reservation_expires_at)
  where status = 'reserved';

create table if not exists public.payment_orders (
  order_id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete restrict,
  idempotency_key text not null
    check (length(idempotency_key) between 8 and 128),
  plan_id text not null references public.model_subscription_plans(plan_id)
    check (plan_id in ('plus', 'pro')),
  payment_method text not null
    check (payment_method in ('alipay', 'wechat', 'card')),
  billing_period_months integer not null default 1
    check (billing_period_months between 1 and 12),
  amount_cny_fen integer not null check (amount_cny_fen > 0),
  currency text not null default 'CNY' check (currency = 'CNY'),
  status text not null default 'pending'
    check (status in ('pending', 'paid', 'closed', 'failed', 'refunded')),
  provider_order_reference text,
  provider_transaction_reference text,
  checkout_expires_at timestamptz not null,
  paid_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, idempotency_key),
  unique (payment_method, provider_order_reference),
  unique (payment_method, provider_transaction_reference),
  check (
    (status = 'paid' and paid_at is not null)
    or (status <> 'paid')
  )
);

create index if not exists payment_orders_user_created_idx
  on public.payment_orders (user_id, created_at desc);

create table if not exists public.payment_webhook_events (
  event_id uuid primary key default gen_random_uuid(),
  payment_method text not null
    check (payment_method in ('alipay', 'wechat', 'card')),
  provider_event_reference text not null,
  payload_sha256 text not null check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  signature_verified boolean not null,
  processing_status text not null default 'received'
    check (processing_status in ('received', 'processed', 'rejected', 'failed')),
  error_code text check (error_code is null or length(error_code) <= 128),
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  unique (payment_method, provider_event_reference)
);

alter table public.model_subscription_plans enable row level security;
alter table public.account_entitlements enable row level security;
alter table public.model_usage_periods enable row level security;
alter table public.model_gateway_grants enable row level security;
alter table public.model_usage_requests enable row level security;
alter table public.payment_orders enable row level security;
alter table public.payment_webhook_events enable row level security;

drop policy if exists "Anyone reads active model plans"
  on public.model_subscription_plans;
create policy "Anyone reads active model plans"
  on public.model_subscription_plans
  for select
  to anon, authenticated
  using (active);

drop policy if exists "Users read their own model entitlement"
  on public.account_entitlements;
create policy "Users read their own model entitlement"
  on public.account_entitlements
  for select
  to authenticated
  using (user_id = auth.uid());

drop policy if exists "Users read their own model usage periods"
  on public.model_usage_periods;
create policy "Users read their own model usage periods"
  on public.model_usage_periods
  for select
  to authenticated
  using (user_id = auth.uid());

drop policy if exists "Users read their own model usage requests"
  on public.model_usage_requests;
create policy "Users read their own model usage requests"
  on public.model_usage_requests
  for select
  to authenticated
  using (user_id = auth.uid());

drop policy if exists "Users read their own payment orders"
  on public.payment_orders;
create policy "Users read their own payment orders"
  on public.payment_orders
  for select
  to authenticated
  using (user_id = auth.uid());

-- No client policy is created for grants or webhook events. Edge Functions use
-- the service-role connection and expose only deliberately scoped projections.

create or replace function public.model_access_ensure_period(
  p_user_id uuid
)
returns public.model_usage_periods
language plpgsql
security definer
set search_path = ''
as $$
declare
  entitlement public.account_entitlements%rowtype;
  selected_plan public.model_subscription_plans%rowtype;
  selected_period public.model_usage_periods%rowtype;
  selected_start timestamptz;
  selected_end timestamptz;
begin
  select *
  into entitlement
  from public.account_entitlements
  where user_id = p_user_id
    and status = 'active'
    and current_period_start <= now()
    and current_period_end > now();

  if entitlement.user_id is not null then
    select *
    into selected_plan
    from public.model_subscription_plans
    where plan_id = entitlement.plan_id
      and active;
    selected_start := entitlement.current_period_start;
    selected_end := least(
      selected_start + interval '1 month',
      entitlement.current_period_end
    );
    -- A user may renew early and extend one entitlement across several paid
    -- months. Keep the allowance monthly instead of turning the whole extended
    -- entitlement into a single quota period.
    while selected_end <= now()
      and selected_end < entitlement.current_period_end
    loop
      selected_start := selected_end;
      selected_end := least(
        selected_start + interval '1 month',
        entitlement.current_period_end
      );
    end loop;
  else
    select *
    into selected_plan
    from public.model_subscription_plans
    where plan_id = 'free'
      and active;
    selected_start :=
      date_trunc('month', timezone('utc', now())) at time zone 'UTC';
    selected_end := selected_start + interval '1 month';
  end if;

  if selected_plan.plan_id is null then
    raise exception using
      errcode = 'P0001',
      message = 'MODEL_PLAN_UNAVAILABLE';
  end if;

  insert into public.model_usage_periods (
    user_id,
    plan_id,
    period_start,
    period_end,
    included_ai_credits,
    credit_policy_version
  )
  values (
    p_user_id,
    selected_plan.plan_id,
    selected_start,
    selected_end,
    selected_plan.included_ai_credits,
    selected_plan.credit_policy_version
  )
  on conflict (user_id, period_start, period_end) do nothing;

  select *
  into selected_period
  from public.model_usage_periods
  where user_id = p_user_id
    and period_start = selected_start
    and period_end = selected_end;

  return selected_period;
end;
$$;

create or replace function public.model_access_snapshot(
  p_user_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_period public.model_usage_periods%rowtype;
  selected_plan public.model_subscription_plans%rowtype;
  recent_requests jsonb;
  stale_credits bigint;
begin
  selected_period := public.model_access_ensure_period(p_user_id);
  select *
  into selected_period
  from public.model_usage_periods
  where period_id = selected_period.period_id
  for update;

  select coalesce(sum(reserved_ai_credits), 0)
  into stale_credits
  from public.model_usage_requests
  where period_id = selected_period.period_id
    and status = 'reserved'
    and reservation_expires_at <= now();

  if stale_credits > 0 then
    update public.model_usage_requests
    set
      status = 'expired',
      error_code = 'RESERVATION_EXPIRED',
      settled_at = now()
    where period_id = selected_period.period_id
      and status = 'reserved'
      and reservation_expires_at <= now();

    update public.model_usage_periods
    set
      reserved_ai_credits = greatest(reserved_ai_credits - stale_credits, 0),
      updated_at = now()
    where period_id = selected_period.period_id
    returning * into selected_period;
  end if;

  select *
  into selected_plan
  from public.model_subscription_plans
  where plan_id = selected_period.plan_id;

  select coalesce(
    jsonb_agg(item order by item.created_at desc),
    '[]'::jsonb
  )
  into recent_requests
  from (
    select
      request_id,
      purpose,
      provider,
      model,
      status,
      reserved_ai_credits,
      consumed_ai_credits,
      input_tokens,
      output_tokens,
      total_tokens,
      usage_estimated,
      created_at,
      settled_at
    from public.model_usage_requests
    where user_id = p_user_id
    order by created_at desc
    limit 50
  ) as item;

  return jsonb_build_object(
    'plan', jsonb_build_object(
      'id', selected_plan.plan_id,
      'name', selected_plan.display_name,
      'monthly_price_cny_fen', selected_plan.monthly_price_cny_fen,
      'included_ai_credits', selected_period.included_ai_credits,
      'capability_set', selected_plan.capability_set
    ),
    'period', jsonb_build_object(
      'starts_at', selected_period.period_start,
      'ends_at', selected_period.period_end
    ),
    'usage', jsonb_build_object(
      'reserved_ai_credits', selected_period.reserved_ai_credits,
      'consumed_ai_credits', selected_period.consumed_ai_credits,
      'remaining_ai_credits', greatest(
        selected_period.included_ai_credits
          - selected_period.consumed_ai_credits
          - selected_period.reserved_ai_credits,
        0
      ),
      'request_count', selected_period.request_count,
      'input_tokens', selected_period.input_tokens,
      'output_tokens', selected_period.output_tokens,
      'total_tokens', selected_period.total_tokens,
      'estimated_request_count', selected_period.estimated_request_count,
      'credit_policy_version', selected_period.credit_policy_version
    ),
    'recent_requests', recent_requests
  );
end;
$$;

create or replace function public.model_gateway_issue_grant(
  p_user_id uuid,
  p_token_sha256 text,
  p_scope text,
  p_scope_reference text default null
)
returns public.model_gateway_grants
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_period public.model_usage_periods%rowtype;
  issued_grant public.model_gateway_grants%rowtype;
  grant_ttl interval;
  grant_calls integer;
  stale_credits bigint;
begin
  if p_token_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception using errcode = '22023', message = 'INVALID_GRANT_HASH';
  end if;
  if p_scope not in ('assistant', 'job') then
    raise exception using errcode = '22023', message = 'INVALID_GRANT_SCOPE';
  end if;
  if p_scope_reference is not null and (
    length(p_scope_reference) not between 1 and 128
    or p_scope_reference !~ '^[A-Za-z0-9_.:-]+$'
  ) then
    raise exception using errcode = '22023', message = 'INVALID_SCOPE_REFERENCE';
  end if;

  selected_period := public.model_access_ensure_period(p_user_id);
  select *
  into selected_period
  from public.model_usage_periods
  where period_id = selected_period.period_id
  for update;

  select coalesce(sum(reserved_ai_credits), 0)
  into stale_credits
  from public.model_usage_requests
  where period_id = selected_period.period_id
    and status = 'reserved'
    and reservation_expires_at <= now();

  if stale_credits > 0 then
    update public.model_usage_requests
    set
      status = 'expired',
      error_code = 'RESERVATION_EXPIRED',
      settled_at = now()
    where period_id = selected_period.period_id
      and status = 'reserved'
      and reservation_expires_at <= now();

    update public.model_usage_periods
    set
      reserved_ai_credits = greatest(reserved_ai_credits - stale_credits, 0),
      updated_at = now()
    where period_id = selected_period.period_id
    returning * into selected_period;
  end if;

  if (
    selected_period.consumed_ai_credits
      + selected_period.reserved_ai_credits
  ) >= selected_period.included_ai_credits then
    raise exception using errcode = 'P0001', message = 'MODEL_QUOTA_EXHAUSTED';
  end if;

  if p_scope = 'assistant' then
    grant_ttl := interval '5 minutes';
    -- A second call is reserved for an OpenAI-compatible provider that rejects
    -- JSON response_format and requires the client's strict local fallback.
    grant_calls := 2;
  else
    grant_ttl := interval '24 hours';
    -- Jobs allow at most 100 optimization generations. Reserve two provider
    -- calls per generation for the strict response-format fallback, plus
    -- headroom for bounded recovery without issuing a second credential.
    grant_calls := 256;
  end if;

  insert into public.model_gateway_grants (
    user_id,
    token_sha256,
    scope,
    scope_reference,
    max_calls,
    expires_at
  )
  values (
    p_user_id,
    p_token_sha256,
    p_scope,
    p_scope_reference,
    grant_calls,
    now() + grant_ttl
  )
  returning * into issued_grant;

  return issued_grant;
end;
$$;

create or replace function public.model_usage_reserve(
  p_request_id uuid,
  p_request_key text,
  p_token_sha256 text,
  p_purpose text,
  p_provider text,
  p_model text,
  p_reserved_ai_credits bigint,
  p_output_credit_weight integer,
  p_credit_policy_version integer
)
returns public.model_usage_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_grant public.model_gateway_grants%rowtype;
  selected_period public.model_usage_periods%rowtype;
  existing_request public.model_usage_requests%rowtype;
  reserved_request public.model_usage_requests%rowtype;
  stale_credits bigint;
begin
  if length(p_request_key) not between 8 and 128
    or p_request_key !~ '^[A-Za-z0-9_.:-]+$'
  then
    raise exception using errcode = '22023', message = 'INVALID_REQUEST_KEY';
  end if;
  if p_reserved_ai_credits <= 0
    or p_output_credit_weight not between 1 and 100
    or p_credit_policy_version <= 0
  then
    raise exception using errcode = '22023', message = 'INVALID_CREDIT_RESERVATION';
  end if;

  select *
  into selected_grant
  from public.model_gateway_grants
  where token_sha256 = p_token_sha256
  for update;

  if selected_grant.grant_id is null
    or selected_grant.revoked_at is not null
    or selected_grant.expires_at <= now()
    or selected_grant.used_calls >= selected_grant.max_calls
    or selected_grant.scope <> p_purpose
  then
    raise exception using errcode = 'P0001', message = 'MODEL_GRANT_INVALID';
  end if;

  select *
  into existing_request
  from public.model_usage_requests
  where user_id = selected_grant.user_id
    and request_key = p_request_key;
  if existing_request.request_id is not null then
    if existing_request.grant_id <> selected_grant.grant_id
      or existing_request.purpose <> p_purpose
      or existing_request.provider <> p_provider
      or existing_request.model <> p_model
    then
      raise exception using errcode = 'P0001', message = 'IDEMPOTENCY_CONFLICT';
    end if;
    return existing_request;
  end if;

  selected_period := public.model_access_ensure_period(selected_grant.user_id);
  select *
  into selected_period
  from public.model_usage_periods
  where period_id = selected_period.period_id
  for update;

  select coalesce(sum(reserved_ai_credits), 0)
  into stale_credits
  from public.model_usage_requests
  where period_id = selected_period.period_id
    and status = 'reserved'
    and reservation_expires_at <= now();

  if stale_credits > 0 then
    update public.model_usage_requests
    set
      status = 'expired',
      error_code = 'RESERVATION_EXPIRED',
      settled_at = now()
    where period_id = selected_period.period_id
      and status = 'reserved'
      and reservation_expires_at <= now();

    update public.model_usage_periods
    set
      reserved_ai_credits = greatest(reserved_ai_credits - stale_credits, 0),
      updated_at = now()
    where period_id = selected_period.period_id
    returning * into selected_period;
  end if;

  if selected_period.credit_policy_version <> p_credit_policy_version then
    raise exception using errcode = 'P0001', message = 'CREDIT_POLICY_MISMATCH';
  end if;
  if (
    selected_period.consumed_ai_credits
      + selected_period.reserved_ai_credits
      + p_reserved_ai_credits
  ) > selected_period.included_ai_credits then
    raise exception using errcode = 'P0001', message = 'MODEL_QUOTA_EXHAUSTED';
  end if;

  update public.model_usage_periods
  set
    reserved_ai_credits = reserved_ai_credits + p_reserved_ai_credits,
    updated_at = now()
  where period_id = selected_period.period_id;

  update public.model_gateway_grants
  set used_calls = used_calls + 1
  where grant_id = selected_grant.grant_id;

  insert into public.model_usage_requests (
    request_id,
    request_key,
    user_id,
    grant_id,
    period_id,
    purpose,
    provider,
    model,
    reserved_ai_credits,
    output_credit_weight,
    credit_policy_version,
    reservation_expires_at
  )
  values (
    p_request_id,
    p_request_key,
    selected_grant.user_id,
    selected_grant.grant_id,
    selected_period.period_id,
    p_purpose,
    p_provider,
    p_model,
    p_reserved_ai_credits,
    p_output_credit_weight,
    p_credit_policy_version,
    now() + interval '15 minutes'
  )
  returning * into reserved_request;

  return reserved_request;
end;
$$;

create or replace function public.model_usage_settle(
  p_request_id uuid,
  p_consumed_ai_credits bigint,
  p_input_tokens bigint,
  p_output_tokens bigint,
  p_total_tokens bigint,
  p_usage_estimated boolean,
  p_provider_request_id text default null
)
returns public.model_usage_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_request public.model_usage_requests%rowtype;
  settled_request public.model_usage_requests%rowtype;
begin
  if p_consumed_ai_credits < 0
    or (
      p_input_tokens is null
      and (
        not p_usage_estimated
        or p_output_tokens is not null
        or p_total_tokens is not null
      )
    )
    or (
      p_input_tokens is not null
      and (
        p_output_tokens is null
        or p_total_tokens is null
        or p_input_tokens < 0
        or p_output_tokens < 0
        or p_total_tokens < 0
        or p_total_tokens <> p_input_tokens + p_output_tokens
      )
    )
  then
    raise exception using errcode = '22023', message = 'INVALID_MODEL_USAGE';
  end if;

  select *
  into selected_request
  from public.model_usage_requests
  where request_id = p_request_id
  for update;

  if selected_request.request_id is null then
    raise exception using errcode = 'P0001', message = 'MODEL_REQUEST_NOT_FOUND';
  end if;
  if selected_request.status = 'completed' then
    return selected_request;
  end if;
  if selected_request.status <> 'reserved' then
    raise exception using errcode = 'P0001', message = 'MODEL_REQUEST_NOT_RESERVED';
  end if;

  update public.model_usage_periods
  set
    reserved_ai_credits = greatest(
      reserved_ai_credits - selected_request.reserved_ai_credits,
      0
    ),
    consumed_ai_credits = consumed_ai_credits + p_consumed_ai_credits,
    request_count = request_count + 1,
    input_tokens = input_tokens + coalesce(p_input_tokens, 0),
    output_tokens = output_tokens + coalesce(p_output_tokens, 0),
    total_tokens = total_tokens + coalesce(p_total_tokens, 0),
    estimated_request_count =
      estimated_request_count + case when p_usage_estimated then 1 else 0 end,
    updated_at = now()
  where period_id = selected_request.period_id;

  update public.model_usage_requests
  set
    status = 'completed',
    consumed_ai_credits = p_consumed_ai_credits,
    input_tokens = p_input_tokens,
    output_tokens = p_output_tokens,
    total_tokens = p_total_tokens,
    usage_estimated = p_usage_estimated,
    provider_request_id = left(p_provider_request_id, 255),
    settled_at = now()
  where request_id = p_request_id
  returning * into settled_request;

  return settled_request;
end;
$$;

create or replace function public.model_usage_fail(
  p_request_id uuid,
  p_error_code text
)
returns public.model_usage_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_request public.model_usage_requests%rowtype;
  failed_request public.model_usage_requests%rowtype;
begin
  select *
  into selected_request
  from public.model_usage_requests
  where request_id = p_request_id
  for update;

  if selected_request.request_id is null then
    raise exception using errcode = 'P0001', message = 'MODEL_REQUEST_NOT_FOUND';
  end if;
  if selected_request.status <> 'reserved' then
    return selected_request;
  end if;

  update public.model_usage_periods
  set
    reserved_ai_credits = greatest(
      reserved_ai_credits - selected_request.reserved_ai_credits,
      0
    ),
    updated_at = now()
  where period_id = selected_request.period_id;

  update public.model_usage_requests
  set
    status = 'failed',
    error_code = left(coalesce(p_error_code, 'MODEL_REQUEST_FAILED'), 128),
    settled_at = now()
  where request_id = p_request_id
  returning * into failed_request;

  return failed_request;
end;
$$;

create or replace function public.billing_create_order(
  p_user_id uuid,
  p_plan_id text,
  p_payment_method text,
  p_idempotency_key text,
  p_billing_period_months integer default 1
)
returns public.payment_orders
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_plan public.model_subscription_plans%rowtype;
  existing_order public.payment_orders%rowtype;
  created_order public.payment_orders%rowtype;
begin
  if p_plan_id not in ('plus', 'pro')
    or p_payment_method not in ('alipay', 'wechat', 'card')
    or p_billing_period_months not between 1 and 12
    or length(p_idempotency_key) not between 8 and 128
    or p_idempotency_key !~ '^[A-Za-z0-9_.:-]+$'
  then
    raise exception using errcode = '22023', message = 'INVALID_PAYMENT_ORDER';
  end if;

  select *
  into existing_order
  from public.payment_orders
  where user_id = p_user_id
    and idempotency_key = p_idempotency_key;
  if existing_order.order_id is not null then
    if existing_order.plan_id <> p_plan_id
      or existing_order.payment_method <> p_payment_method
      or existing_order.billing_period_months <> p_billing_period_months
    then
      raise exception using errcode = 'P0001', message = 'IDEMPOTENCY_CONFLICT';
    end if;
    return existing_order;
  end if;

  select *
  into selected_plan
  from public.model_subscription_plans
  where plan_id = p_plan_id
    and active;
  if selected_plan.plan_id is null or selected_plan.monthly_price_cny_fen <= 0 then
    raise exception using errcode = 'P0001', message = 'PAYMENT_PLAN_UNAVAILABLE';
  end if;

  insert into public.payment_orders (
    user_id,
    idempotency_key,
    plan_id,
    payment_method,
    billing_period_months,
    amount_cny_fen,
    checkout_expires_at
  )
  values (
    p_user_id,
    p_idempotency_key,
    p_plan_id,
    p_payment_method,
    p_billing_period_months,
    selected_plan.monthly_price_cny_fen * p_billing_period_months,
    now() + interval '35 minutes'
  )
  returning * into created_order;

  return created_order;
end;
$$;

create or replace function public.billing_mark_order_paid(
  p_order_id uuid,
  p_provider_order_reference text,
  p_provider_transaction_reference text,
  p_provider_event_reference text,
  p_payload_sha256 text
)
returns public.payment_orders
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_order public.payment_orders%rowtype;
  existing_entitlement public.account_entitlements%rowtype;
  paid_order public.payment_orders%rowtype;
  next_start timestamptz;
  next_end timestamptz;
begin
  if p_payload_sha256 !~ '^[0-9a-f]{64}$'
    or coalesce(p_provider_order_reference, '') = ''
    or coalesce(p_provider_transaction_reference, '') = ''
    or coalesce(p_provider_event_reference, '') = ''
  then
    raise exception using errcode = '22023', message = 'INVALID_PAYMENT_RECEIPT';
  end if;

  select *
  into selected_order
  from public.payment_orders
  where order_id = p_order_id
  for update;
  if selected_order.order_id is null then
    raise exception using errcode = 'P0001', message = 'PAYMENT_ORDER_NOT_FOUND';
  end if;
  if selected_order.status = 'paid' then
    return selected_order;
  end if;
  -- A cryptographically verified success callback is authoritative even when
  -- it arrives just after the browser checkout deadline. Rejecting it would
  -- take the customer's money without activating the purchased entitlement.
  if selected_order.status <> 'pending' then
    raise exception using errcode = 'P0001', message = 'PAYMENT_ORDER_NOT_PAYABLE';
  end if;

  -- Serialize entitlement changes even when this is the user's first paid
  -- order and no entitlement row exists yet.
  perform 1
  from auth.users
  where id = selected_order.user_id
  for update;

  insert into public.payment_webhook_events (
    payment_method,
    provider_event_reference,
    payload_sha256,
    signature_verified,
    processing_status,
    processed_at
  )
  values (
    selected_order.payment_method,
    p_provider_event_reference,
    p_payload_sha256,
    true,
    'processed',
    now()
  )
  on conflict (payment_method, provider_event_reference) do nothing;

  update public.payment_orders
  set
    status = 'paid',
    provider_order_reference = left(p_provider_order_reference, 255),
    provider_transaction_reference = left(p_provider_transaction_reference, 255),
    paid_at = now(),
    updated_at = now()
  where order_id = selected_order.order_id
  returning * into paid_order;

  select *
  into existing_entitlement
  from public.account_entitlements
  where user_id = selected_order.user_id
  for update;

  if existing_entitlement.user_id is not null
    and existing_entitlement.status = 'active'
    and existing_entitlement.current_period_end > now()
    and existing_entitlement.plan_id = selected_order.plan_id
  then
    next_start := existing_entitlement.current_period_start;
    next_end := existing_entitlement.current_period_end
      + make_interval(months => selected_order.billing_period_months);
  elsif existing_entitlement.user_id is not null
    and existing_entitlement.status = 'active'
    and existing_entitlement.current_period_end > now()
  then
    -- A paid plan change becomes effective immediately while preserving the
    -- remaining paid duration and adding the newly purchased month.
    next_start := now();
    next_end := existing_entitlement.current_period_end
      + make_interval(months => selected_order.billing_period_months);
  else
    next_start := now();
    next_end := next_start
      + make_interval(months => selected_order.billing_period_months);
  end if;
  insert into public.account_entitlements (
    user_id,
    plan_id,
    status,
    current_period_start,
    current_period_end,
    cancel_at_period_end,
    source,
    payment_provider,
    provider_subscription_reference
  )
  values (
    selected_order.user_id,
    selected_order.plan_id,
    'active',
    next_start,
    next_end,
    true,
    'payment',
    selected_order.payment_method,
    p_provider_transaction_reference
  )
  on conflict (user_id) do update
  set
    plan_id = excluded.plan_id,
    status = 'active',
    current_period_start = excluded.current_period_start,
    current_period_end = excluded.current_period_end,
    cancel_at_period_end = true,
    source = 'payment',
    payment_provider = excluded.payment_provider,
    provider_subscription_reference = excluded.provider_subscription_reference,
    updated_at = now();

  return paid_order;
end;
$$;

revoke all on function public.model_access_ensure_period(uuid) from public;
revoke all on function public.model_access_snapshot(uuid) from public;
revoke all on function public.model_gateway_issue_grant(uuid, text, text, text)
  from public;
revoke all on function public.model_usage_reserve(
  uuid, text, text, text, text, text, bigint, integer, integer
) from public;
revoke all on function public.model_usage_settle(
  uuid, bigint, bigint, bigint, bigint, boolean, text
) from public;
revoke all on function public.model_usage_fail(uuid, text) from public;
revoke all on function public.billing_create_order(
  uuid, text, text, text, integer
) from public;
revoke all on function public.billing_mark_order_paid(
  uuid, text, text, text, text
) from public;

grant execute on function public.model_access_ensure_period(uuid)
  to service_role;
grant execute on function public.model_access_snapshot(uuid)
  to service_role;
grant execute on function public.model_gateway_issue_grant(uuid, text, text, text)
  to service_role;
grant execute on function public.model_usage_reserve(
  uuid, text, text, text, text, text, bigint, integer, integer
) to service_role;
grant execute on function public.model_usage_settle(
  uuid, bigint, bigint, bigint, bigint, boolean, text
) to service_role;
grant execute on function public.model_usage_fail(uuid, text)
  to service_role;
grant execute on function public.billing_create_order(
  uuid, text, text, text, integer
) to service_role;
grant execute on function public.billing_mark_order_paid(
  uuid, text, text, text, text
) to service_role;
