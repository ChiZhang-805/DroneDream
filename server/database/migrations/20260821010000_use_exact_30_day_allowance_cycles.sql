-- Make every managed-model allowance cycle an exact, rolling 30-day window.
--
-- Free accounts are anchored to auth.users.created_at. Paid accounts are
-- anchored to the instant their current entitlement started. We deliberately
-- do not use date_trunc('month') or interval '1 month': both would make quota
-- duration depend on the calendar instead of the customer's subscription time.

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
  selected_anchor timestamptz;
  selected_start timestamptz;
  selected_end timestamptz;
  cycle_index bigint;
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
    selected_anchor := entitlement.current_period_start;
  else
    select *
    into selected_plan
    from public.model_subscription_plans
    where plan_id = 'free'
      and active;

    select created_at
    into selected_anchor
    from auth.users
    where id = p_user_id;
  end if;

  if selected_plan.plan_id is null then
    raise exception using
      errcode = 'P0001',
      message = 'MODEL_PLAN_UNAVAILABLE';
  end if;
  if selected_anchor is null then
    raise exception using
      errcode = 'P0001',
      message = 'MODEL_ACCOUNT_NOT_FOUND';
  end if;

  cycle_index := greatest(
    floor(extract(epoch from (now() - selected_anchor)) / 2592000)::bigint,
    0
  );
  selected_start := selected_anchor + cycle_index * interval '30 days';
  selected_end := selected_start + interval '30 days';

  -- Do not extend a legacy or cancelled paid entitlement. New payments below
  -- are exact 30-day multiples; a pre-migration calendar-month entitlement may
  -- have one final short compatibility window instead of losing paid time.
  if entitlement.user_id is not null then
    selected_end := least(selected_end, entitlement.current_period_end);
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

-- Purchased durations use the same exact 30-day unit as allowance periods.
-- Existing entitlement time is retained on early renewal or plan changes.
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
  if selected_order.status <> 'pending' then
    raise exception using errcode = 'P0001', message = 'PAYMENT_ORDER_NOT_PAYABLE';
  end if;

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
      + selected_order.billing_period_months * interval '30 days';
  elsif existing_entitlement.user_id is not null
    and existing_entitlement.status = 'active'
    and existing_entitlement.current_period_end > now()
  then
    -- A paid plan change becomes effective immediately while preserving the
    -- remaining paid duration and adding the newly purchased 30-day block.
    next_start := now();
    next_end := existing_entitlement.current_period_end
      + selected_order.billing_period_months * interval '30 days';
  else
    next_start := now();
    next_end := next_start
      + selected_order.billing_period_months * interval '30 days';
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

-- Preserve live-cycle usage at cutover. Requests that fall in the newly
-- calculated rolling window are attached to that exact period, then both the
-- source and destination aggregates are rebuilt from request-level evidence.
do $$
declare
  selected_user record;
  selected_period public.model_usage_periods%rowtype;
  old_period_ids uuid[];
  old_period_id uuid;
begin
  for selected_user in
    select distinct user_id
    from public.model_usage_periods
    where period_start <= now()
      and period_end > now()
  loop
    selected_period := public.model_access_ensure_period(selected_user.user_id);

    select array_agg(distinct period_id)
    into old_period_ids
    from public.model_usage_requests
    where user_id = selected_user.user_id
      and created_at >= selected_period.period_start
      and created_at < selected_period.period_end
      and period_id <> selected_period.period_id;

    update public.model_usage_requests
    set period_id = selected_period.period_id
    where user_id = selected_user.user_id
      and created_at >= selected_period.period_start
      and created_at < selected_period.period_end
      and period_id <> selected_period.period_id;

    update public.model_usage_periods p
    set
      reserved_ai_credits = coalesce((
        select sum(r.reserved_ai_credits)
        from public.model_usage_requests r
        where r.period_id = p.period_id and r.status = 'reserved'
      ), 0),
      consumed_ai_credits = coalesce((
        select sum(r.consumed_ai_credits)
        from public.model_usage_requests r
        where r.period_id = p.period_id and r.status = 'completed'
      ), 0),
      request_count = (
        select count(*)
        from public.model_usage_requests r
        where r.period_id = p.period_id and r.status = 'completed'
      ),
      input_tokens = coalesce((
        select sum(r.input_tokens)
        from public.model_usage_requests r
        where r.period_id = p.period_id and r.status = 'completed'
      ), 0),
      output_tokens = coalesce((
        select sum(r.output_tokens)
        from public.model_usage_requests r
        where r.period_id = p.period_id and r.status = 'completed'
      ), 0),
      total_tokens = coalesce((
        select sum(r.total_tokens)
        from public.model_usage_requests r
        where r.period_id = p.period_id and r.status = 'completed'
      ), 0),
      estimated_request_count = (
        select count(*)
        from public.model_usage_requests r
        where r.period_id = p.period_id
          and r.status = 'completed'
          and r.usage_estimated
      ),
      updated_at = now()
    where p.period_id = selected_period.period_id;

    if old_period_ids is not null then
      foreach old_period_id in array old_period_ids
      loop
        update public.model_usage_periods p
        set
          reserved_ai_credits = coalesce((
            select sum(r.reserved_ai_credits)
            from public.model_usage_requests r
            where r.period_id = p.period_id and r.status = 'reserved'
          ), 0),
          consumed_ai_credits = coalesce((
            select sum(r.consumed_ai_credits)
            from public.model_usage_requests r
            where r.period_id = p.period_id and r.status = 'completed'
          ), 0),
          request_count = (
            select count(*)
            from public.model_usage_requests r
            where r.period_id = p.period_id and r.status = 'completed'
          ),
          input_tokens = coalesce((
            select sum(r.input_tokens)
            from public.model_usage_requests r
            where r.period_id = p.period_id and r.status = 'completed'
          ), 0),
          output_tokens = coalesce((
            select sum(r.output_tokens)
            from public.model_usage_requests r
            where r.period_id = p.period_id and r.status = 'completed'
          ), 0),
          total_tokens = coalesce((
            select sum(r.total_tokens)
            from public.model_usage_requests r
            where r.period_id = p.period_id and r.status = 'completed'
          ), 0),
          estimated_request_count = (
            select count(*)
            from public.model_usage_requests r
            where r.period_id = p.period_id
              and r.status = 'completed'
              and r.usage_estimated
          ),
          updated_at = now()
        where p.period_id = old_period_id;
      end loop;
    end if;
  end loop;
end;
$$;

revoke all on function public.model_access_ensure_period(uuid) from public;
revoke all on function public.billing_mark_order_paid(
  uuid, text, text, text, text
) from public;

grant execute on function public.model_access_ensure_period(uuid)
  to service_role;
grant execute on function public.billing_mark_order_paid(
  uuid, text, text, text, text
) to service_role;
