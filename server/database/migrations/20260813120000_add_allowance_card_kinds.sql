-- Distinguish a full-refill card from a fixed-credit gift card. Redemption is
-- serialized against the active usage period and can never exceed plan quota.

alter table public.model_allowance_reset_cards
  add column if not exists card_kind text not null default 'fixed_credit'
  check (card_kind in ('full_refill', 'fixed_credit'));

update public.model_allowance_reset_cards
set card_kind = 'full_refill'
where issued_reason = 'product-owner-preview';

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
  select * into selected_card from public.model_allowance_reset_cards
  where card_id = p_card_id and user_id = p_user_id for update;
  if selected_card.card_id is null then
    raise exception using errcode = 'P0001', message = 'RESET_CARD_NOT_FOUND';
  end if;
  if selected_card.status <> 'available' then
    raise exception using errcode = 'P0001', message = 'RESET_CARD_ALREADY_USED';
  end if;
  if selected_card.expires_at <= now() then
    update public.model_allowance_reset_cards set status = 'expired'
    where card_id = selected_card.card_id;
    raise exception using errcode = 'P0001', message = 'RESET_CARD_EXPIRED';
  end if;
  selected_period := public.model_access_ensure_period(p_user_id);
  select * into selected_period from public.model_usage_periods
  where period_id = selected_period.period_id for update;
  if selected_period.reserved_ai_credits <> 0 then
    raise exception using errcode = 'P0001', message = 'RESET_CARD_REQUESTS_IN_FLIGHT';
  end if;
  restored_credits := case
    when selected_card.card_kind = 'full_refill' then
      least(selected_period.consumed_ai_credits, selected_period.included_ai_credits)
    else least(selected_card.credits, selected_period.consumed_ai_credits)
  end;
  update public.model_usage_periods
  set consumed_ai_credits = greatest(0, consumed_ai_credits - restored_credits), updated_at = now()
  where period_id = selected_period.period_id;
  update public.model_allowance_reset_cards
  set status = 'redeemed', redeemed_at = now(), redeemed_period_id = selected_period.period_id
  where card_id = selected_card.card_id;
  insert into public.model_allowance_reset_events (
    card_id, user_id, period_id, previous_consumed_ai_credits,
    previous_reserved_ai_credits, restored_ai_credits
  ) values (
    selected_card.card_id, p_user_id, selected_period.period_id,
    selected_period.consumed_ai_credits, selected_period.reserved_ai_credits, restored_credits
  );
  return jsonb_build_object(
    'card_id', selected_card.card_id,
    'period_id', selected_period.period_id,
    'card_kind', selected_card.card_kind,
    'restored_ai_credits', restored_credits
  );
end;
$$;
