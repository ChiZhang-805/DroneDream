-- A bounded, zero-filled daily usage series powers the 7-day, 30-day and
-- one-year allowance views without exposing raw provider requests.
create or replace function public.model_usage_daily_history(
  p_user_id uuid,
  p_days integer default 365
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  utc_today date := (timezone('utc', now()))::date;
  history jsonb;
begin
  if p_user_id is null or p_days not between 1 and 366 then
    raise exception using errcode = '22023', message = 'INVALID_MODEL_USAGE_HISTORY_RANGE';
  end if;

  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'date', days.day::date,
        'consumed_ai_credits', coalesce(usage.consumed_ai_credits, 0),
        'request_count', coalesce(usage.request_count, 0),
        'input_tokens', coalesce(usage.input_tokens, 0),
        'output_tokens', coalesce(usage.output_tokens, 0),
        'total_tokens', coalesce(usage.total_tokens, 0)
      ) order by days.day::date
    ),
    '[]'::jsonb
  )
  into history
  from generate_series(
    utc_today - (p_days - 1),
    utc_today,
    interval '1 day'
  ) as days(day)
  left join (
    select
      (timezone('utc', coalesce(settled_at, created_at)))::date as day,
      coalesce(sum(consumed_ai_credits), 0)::bigint as consumed_ai_credits,
      count(*)::bigint as request_count,
      coalesce(sum(input_tokens), 0)::bigint as input_tokens,
      coalesce(sum(output_tokens), 0)::bigint as output_tokens,
      coalesce(sum(total_tokens), 0)::bigint as total_tokens
    from public.model_usage_requests
    where user_id = p_user_id
      and status = 'completed'
      and (timezone('utc', coalesce(settled_at, created_at)))::date
        between utc_today - (p_days - 1) and utc_today
    group by (timezone('utc', coalesce(settled_at, created_at)))::date
  ) as usage on usage.day = days.day::date;

  return history;
end;
$$;

revoke all on function public.model_usage_daily_history(uuid, integer) from public;
grant execute on function public.model_usage_daily_history(uuid, integer) to service_role;
