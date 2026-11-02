-- Refresh managed-model allowances every seven days, increase each plan's
-- included allowance by 20x, and give every existing account a fresh cycle at
-- cutover. Subscription billing remains monthly; this migration changes only
-- the managed-model allowance window.

update public.model_subscription_plans
set included_ai_credits = case plan_id
  when 'free' then 6000000
  when 'plus' then 60000000
  when 'pro' then 300000000
end,
updated_at = now()
where plan_id in ('free', 'plus', 'pro');

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
  latest_period_end timestamptz;
  account_created_at timestamptz;
  cycle_index bigint;
begin
  if p_user_id is null then
    raise exception using
      errcode = '22023',
      message = 'MODEL_ACCOUNT_NOT_FOUND';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));

  select created_at
  into account_created_at
  from auth.users
  where id = p_user_id;

  if account_created_at is null then
    raise exception using
      errcode = 'P0001',
      message = 'MODEL_ACCOUNT_NOT_FOUND';
  end if;

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
  else
    select *
    into selected_plan
    from public.model_subscription_plans
    where plan_id = 'free'
      and active;
  end if;

  if selected_plan.plan_id is null then
    raise exception using
      errcode = 'P0001',
      message = 'MODEL_PLAN_UNAVAILABLE';
  end if;

  -- Reuse only a current seven-day window with the current plan contract.
  -- A paid entitlement may cap the last window below seven days.
  select *
  into selected_period
  from public.model_usage_periods
  where user_id = p_user_id
    and period_start <= now()
    and period_end > now()
    and period_end <= period_start + interval '7 days'
    and plan_id = selected_plan.plan_id
    and included_ai_credits = selected_plan.included_ai_credits
    and credit_policy_version = selected_plan.credit_policy_version
  order by period_start desc
  limit 1;

  if selected_period.period_id is not null then
    return selected_period;
  end if;

  -- Plan changes and legacy allowance windows end immediately. Historical
  -- requests remain attached to them for audit and usage reporting.
  update public.model_usage_periods
  set period_end = greatest(period_start + interval '1 microsecond', now()),
      updated_at = now()
  where user_id = p_user_id
    and period_start <= now()
    and period_end > now();

  select max(period_end)
  into latest_period_end
  from public.model_usage_periods
  where user_id = p_user_id
    and period_end <= now();

  if latest_period_end is not null then
    selected_anchor := latest_period_end;
  elsif entitlement.user_id is not null then
    selected_anchor := greatest(
      account_created_at,
      entitlement.current_period_start
    );
  else
    selected_anchor := account_created_at;
  end if;

  cycle_index := greatest(
    floor(extract(epoch from (now() - selected_anchor)) / 604800)::bigint,
    0
  );
  selected_start := selected_anchor + cycle_index * interval '7 days';
  selected_end := selected_start + interval '7 days';

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

-- End every legacy current window and create a new full weekly allowance for
-- every registered account. No historical request or usage record is deleted.
do $$
declare
  registered_user record;
begin
  update public.model_usage_periods
  set period_end = greatest(period_start + interval '1 microsecond', now()),
      updated_at = now()
  where period_start <= now()
    and period_end > now();

  for registered_user in
    select id from auth.users order by created_at, id
  loop
    perform public.model_access_ensure_period(registered_user.id);
  end loop;
end;
$$;

revoke all on function public.model_access_ensure_period(uuid) from public;
grant execute on function public.model_access_ensure_period(uuid)
  to service_role;

notify pgrst, 'reload schema';
