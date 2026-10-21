-- Human-readable allowance-card identity and a complete lifecycle audit. The
-- UUID remains the authorization key; this number is presentation-only.

alter table public.model_allowance_reset_cards
  add column if not exists card_number text;

update public.model_allowance_reset_cards
set card_number = upper(
  'DD-' || substring(replace(card_id::text, '-', '') from 1 for 4) || '-'
  || substring(replace(card_id::text, '-', '') from 5 for 4) || '-'
  || substring(replace(card_id::text, '-', '') from 9 for 4)
)
where card_number is null;

alter table public.model_allowance_reset_cards
  alter column card_number set not null;

create unique index if not exists model_allowance_reset_cards_number_uidx
  on public.model_allowance_reset_cards (card_number);

alter table public.model_allowance_reset_events
  add column if not exists event_type text not null default 'redeemed'
    check (event_type in ('issued', 'redeemed', 'expired', 'revoked')),
  add column if not exists allowance_before bigint,
  add column if not exists allowance_after bigint;

alter table public.model_allowance_reset_events
  drop constraint if exists model_allowance_reset_events_card_id_key;

update public.model_allowance_reset_events events
set allowance_before = greatest(
      0,
      periods.included_ai_credits - events.previous_consumed_ai_credits
    ),
    allowance_after = least(
      periods.included_ai_credits,
      greatest(0, periods.included_ai_credits - events.previous_consumed_ai_credits)
      + events.restored_ai_credits
    )
from public.model_usage_periods periods
where periods.period_id = events.period_id
  and (events.allowance_before is null or events.allowance_after is null);

alter table public.model_allowance_reset_events
  alter column allowance_before set not null,
  alter column allowance_after set not null;

create table if not exists public.model_allowance_card_lifecycle_events (
  lifecycle_event_id uuid primary key default gen_random_uuid(),
  card_id uuid not null references public.model_allowance_reset_cards(card_id)
    on delete restrict,
  user_id uuid not null references auth.users(id) on delete cascade,
  event_type text not null check (event_type in ('issued', 'redeemed', 'expired', 'revoked')),
  period_id uuid references public.model_usage_periods(period_id) on delete restrict,
  allowance_before bigint check (allowance_before is null or allowance_before >= 0),
  allowance_after bigint check (allowance_after is null or allowance_after >= 0),
  created_at timestamptz not null default now(),
  unique (card_id, event_type)
);

insert into public.model_allowance_card_lifecycle_events (
  card_id, user_id, event_type, created_at
)
select card_id, user_id, 'issued', created_at
from public.model_allowance_reset_cards
on conflict (card_id, event_type) do nothing;

insert into public.model_allowance_card_lifecycle_events (
  card_id, user_id, event_type, period_id, allowance_before, allowance_after, created_at
)
select events.card_id, events.user_id, 'redeemed', events.period_id,
  events.allowance_before, events.allowance_after, events.created_at
from public.model_allowance_reset_events events
on conflict (card_id, event_type) do nothing;

insert into public.model_allowance_card_lifecycle_events (
  card_id, user_id, event_type, created_at
)
select card_id, user_id, status, coalesce(redeemed_at, created_at)
from public.model_allowance_reset_cards
where status in ('expired', 'revoked')
on conflict (card_id, event_type) do nothing;

alter table public.model_allowance_card_lifecycle_events enable row level security;
drop policy if exists model_allowance_card_lifecycle_events_select_own
  on public.model_allowance_card_lifecycle_events;
create policy model_allowance_card_lifecycle_events_select_own
  on public.model_allowance_card_lifecycle_events
  for select to authenticated using (user_id = auth.uid());
revoke all on public.model_allowance_card_lifecycle_events from anon;
revoke insert, update, delete on public.model_allowance_card_lifecycle_events from authenticated;
grant select on public.model_allowance_card_lifecycle_events to authenticated;
grant all on public.model_allowance_card_lifecycle_events to service_role;

create or replace function public.model_allowance_expire_cards(p_user_id uuid)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  expired_count bigint;
begin
  with expired_cards as (
    update public.model_allowance_reset_cards
    set status = 'expired'
    where user_id = p_user_id
      and status = 'available'
      and expires_at <= now()
    returning card_id, user_id
  ), recorded_events as (
    insert into public.model_allowance_card_lifecycle_events (
      card_id, user_id, event_type
    )
    select card_id, user_id, 'expired'
    from expired_cards
    on conflict (card_id, event_type) do nothing
    returning 1
  )
  select count(*) into expired_count from recorded_events;
  return expired_count;
end;
$$;

revoke all on function public.model_allowance_expire_cards(uuid) from public;
grant execute on function public.model_allowance_expire_cards(uuid) to service_role;

create or replace function public.model_allowance_reset_redeem(
  p_user_id uuid,
  p_card_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_card public.model_allowance_reset_cards%rowtype;
  selected_period public.model_usage_periods%rowtype;
  restored_credits bigint;
  allowance_before bigint;
  allowance_after bigint;
begin
  if p_user_id is null or p_card_id is null then
    raise exception using errcode = '22023', message = 'RESET_CARD_INVALID';
  end if;
  select * into selected_card from public.model_allowance_reset_cards
  where card_id = p_card_id and user_id = p_user_id for update;
  if selected_card.card_id is null then
    raise exception using errcode = 'P0001', message = 'RESET_CARD_NOT_FOUND';
  end if;
  if selected_card.status = 'expired' then
    raise exception using errcode = 'P0001', message = 'RESET_CARD_EXPIRED';
  end if;
  if selected_card.status <> 'available' then
    raise exception using errcode = 'P0001', message = 'RESET_CARD_ALREADY_USED';
  end if;
  if selected_card.expires_at <= now() then
    update public.model_allowance_reset_cards set status = 'expired'
    where card_id = selected_card.card_id;
    insert into public.model_allowance_card_lifecycle_events (card_id, user_id, event_type)
    values (selected_card.card_id, p_user_id, 'expired')
    on conflict (card_id, event_type) do nothing;
    return jsonb_build_object(
      'card_id', selected_card.card_id,
      'card_number', selected_card.card_number,
      'error_code', 'RESET_CARD_EXPIRED'
    );
  end if;
  selected_period := public.model_access_ensure_period(p_user_id);
  select * into selected_period from public.model_usage_periods
  where period_id = selected_period.period_id for update;
  if selected_period.reserved_ai_credits <> 0 then
    raise exception using errcode = 'P0001', message = 'RESET_CARD_REQUESTS_IN_FLIGHT';
  end if;
  allowance_before := greatest(
    0,
    selected_period.included_ai_credits - selected_period.consumed_ai_credits
  );
  restored_credits := case
    when selected_card.card_kind = 'full_refill' then
      least(selected_period.consumed_ai_credits, selected_period.included_ai_credits)
    else least(selected_card.credits, selected_period.consumed_ai_credits)
  end;
  allowance_after := least(
    selected_period.included_ai_credits,
    allowance_before + restored_credits
  );
  update public.model_usage_periods
  set consumed_ai_credits = greatest(0, consumed_ai_credits - restored_credits), updated_at = now()
  where period_id = selected_period.period_id;
  update public.model_allowance_reset_cards
  set status = 'redeemed', redeemed_at = now(), redeemed_period_id = selected_period.period_id
  where card_id = selected_card.card_id;
  insert into public.model_allowance_reset_events (
    card_id, user_id, period_id, previous_consumed_ai_credits,
    previous_reserved_ai_credits, restored_ai_credits, event_type,
    allowance_before, allowance_after
  ) values (
    selected_card.card_id, p_user_id, selected_period.period_id,
    selected_period.consumed_ai_credits, selected_period.reserved_ai_credits,
    restored_credits, 'redeemed', allowance_before, allowance_after
  );
  insert into public.model_allowance_card_lifecycle_events (
    card_id, user_id, event_type, period_id, allowance_before, allowance_after
  ) values (
    selected_card.card_id, p_user_id, 'redeemed', selected_period.period_id,
    allowance_before, allowance_after
  ) on conflict (card_id, event_type) do nothing;
  return jsonb_build_object(
    'card_id', selected_card.card_id,
    'card_number', selected_card.card_number,
    'period_id', selected_period.period_id,
    'card_kind', selected_card.card_kind,
    'restored_ai_credits', restored_credits,
    'allowance_before', allowance_before,
    'allowance_after', allowance_after
  );
end;
$$;

revoke all on function public.model_allowance_reset_redeem(uuid, uuid) from public;
grant execute on function public.model_allowance_reset_redeem(uuid, uuid) to service_role;
