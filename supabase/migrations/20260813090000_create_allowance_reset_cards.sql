-- One-time, user-owned allowance reset cards. Redemptions are serialized,
-- audited, and can only refill the authenticated user's active allowance.

create table if not exists public.model_allowance_reset_cards (
  card_id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  credits bigint not null check (credits > 0),
  status text not null default 'available'
    check (status in ('available', 'redeemed', 'expired', 'revoked')),
  expires_at timestamptz not null,
  redeemed_at timestamptz,
  redeemed_period_id uuid references public.model_usage_periods(period_id)
    on delete restrict,
  issued_reason text not null default 'support'
    check (length(issued_reason) between 1 and 128),
  created_at timestamptz not null default now(),
  check (
    (status = 'redeemed' and redeemed_at is not null and redeemed_period_id is not null)
    or (status <> 'redeemed' and redeemed_at is null and redeemed_period_id is null)
  )
);

create index if not exists model_allowance_reset_cards_user_status_expiry_idx
  on public.model_allowance_reset_cards (user_id, status, expires_at);

create table if not exists public.model_allowance_reset_events (
  event_id uuid primary key default gen_random_uuid(),
  card_id uuid not null references public.model_allowance_reset_cards(card_id)
    on delete restrict,
  user_id uuid not null references auth.users(id) on delete cascade,
  period_id uuid not null references public.model_usage_periods(period_id)
    on delete restrict,
  previous_consumed_ai_credits bigint not null check (previous_consumed_ai_credits >= 0),
  previous_reserved_ai_credits bigint not null check (previous_reserved_ai_credits >= 0),
  restored_ai_credits bigint not null check (restored_ai_credits >= 0),
  created_at timestamptz not null default now(),
  unique (card_id)
);

alter table public.model_allowance_reset_cards enable row level security;
alter table public.model_allowance_reset_events enable row level security;

drop policy if exists model_allowance_reset_cards_select_own
  on public.model_allowance_reset_cards;
create policy model_allowance_reset_cards_select_own
  on public.model_allowance_reset_cards
  for select
  to authenticated
  using (user_id = auth.uid());

drop policy if exists model_allowance_reset_events_select_own
  on public.model_allowance_reset_events;
create policy model_allowance_reset_events_select_own
  on public.model_allowance_reset_events
  for select
  to authenticated
  using (user_id = auth.uid());

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
begin
  if p_user_id is null or p_card_id is null then
    raise exception using errcode = '22023', message = 'RESET_CARD_INVALID';
  end if;

  select *
  into selected_card
  from public.model_allowance_reset_cards
  where card_id = p_card_id
    and user_id = p_user_id
  for update;

  if selected_card.card_id is null then
    raise exception using errcode = 'P0001', message = 'RESET_CARD_NOT_FOUND';
  end if;
  if selected_card.status <> 'available' then
    raise exception using errcode = 'P0001', message = 'RESET_CARD_ALREADY_USED';
  end if;
  if selected_card.expires_at <= now() then
    update public.model_allowance_reset_cards
    set status = 'expired'
    where card_id = selected_card.card_id;
    raise exception using errcode = 'P0001', message = 'RESET_CARD_EXPIRED';
  end if;

  selected_period := public.model_access_ensure_period(p_user_id);
  select *
  into selected_period
  from public.model_usage_periods
  where period_id = selected_period.period_id
  for update;

  -- A reset while provider work is reserved would make the accounting receipt
  -- ambiguous. The client can retry after the in-flight request settles.
  if selected_period.reserved_ai_credits <> 0 then
    raise exception using errcode = 'P0001', message = 'RESET_CARD_REQUESTS_IN_FLIGHT';
  end if;

  restored_credits := least(
    selected_period.consumed_ai_credits,
    selected_period.included_ai_credits
  );

  update public.model_usage_periods
  set consumed_ai_credits = 0, updated_at = now()
  where period_id = selected_period.period_id;

  update public.model_allowance_reset_cards
  set
    status = 'redeemed',
    redeemed_at = now(),
    redeemed_period_id = selected_period.period_id
  where card_id = selected_card.card_id;

  insert into public.model_allowance_reset_events (
    card_id,
    user_id,
    period_id,
    previous_consumed_ai_credits,
    previous_reserved_ai_credits,
    restored_ai_credits
  ) values (
    selected_card.card_id,
    p_user_id,
    selected_period.period_id,
    selected_period.consumed_ai_credits,
    selected_period.reserved_ai_credits,
    restored_credits
  );

  return jsonb_build_object(
    'card_id', selected_card.card_id,
    'period_id', selected_period.period_id,
    'restored_ai_credits', restored_credits
  );
end;
$$;

revoke all on table public.model_allowance_reset_cards from anon;
revoke all on table public.model_allowance_reset_events from anon;
revoke insert, update, delete on table public.model_allowance_reset_cards from authenticated;
revoke insert, update, delete on table public.model_allowance_reset_events from authenticated;
revoke all on function public.model_allowance_reset_redeem(uuid, uuid) from public;
grant execute on function public.model_allowance_reset_redeem(uuid, uuid)
  to service_role;
