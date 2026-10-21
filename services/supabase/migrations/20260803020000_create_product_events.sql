-- Privacy-bounded product analytics. Browser roles receive no direct table or
-- RPC access; the product-events Edge Function validates the envelope and
-- derives user_id from a verified JWT before calling this service-role RPC.

create table if not exists public.product_events (
  user_id uuid not null references auth.users(id) on delete cascade,
  event_id uuid not null,
  schema_version integer not null default 1 check (schema_version = 1),
  name text not null check (name in (
    'registration_verified', 'runtime_ready', 'draft_saved', 'job_created',
    'job_succeeded', 'job_failed', 'assistant_turn_succeeded',
    'assistant_turn_failed', 'report_exported', 'fixed_scenario_selected',
    'community_contributed'
  )),
  occurred_at timestamptz not null,
  received_at timestamptz not null default now(),
  properties jsonb not null default '{}'::jsonb,
  primary key (user_id, event_id),
  check (jsonb_typeof(properties) = 'object'),
  check (octet_length(properties::text) <= 4096)
);

create index if not exists product_events_received_idx
  on public.product_events (received_at desc, name);
create index if not exists product_events_user_received_idx
  on public.product_events (user_id, received_at desc);

alter table public.product_events enable row level security;
revoke all on table public.product_events from anon, authenticated;
grant select, insert on table public.product_events to service_role;

create or replace function public.record_product_event(
  p_user_id uuid,
  p_event_id uuid,
  p_schema_version integer,
  p_name text,
  p_occurred_at timestamptz,
  p_properties jsonb
)
returns table (inserted boolean, received_at timestamptz)
language plpgsql
security definer
set search_path = ''
as $$
declare
  stored_received_at timestamptz;
begin
  insert into public.product_events (
    user_id, event_id, schema_version, name, occurred_at, properties
  ) values (
    p_user_id, p_event_id, p_schema_version, p_name, p_occurred_at,
    coalesce(p_properties, '{}'::jsonb)
  )
  on conflict (user_id, event_id) do nothing
  returning product_events.received_at into stored_received_at;
  if stored_received_at is not null then
    return query select true, stored_received_at;
    return;
  end if;
  select event.received_at into stored_received_at
  from public.product_events as event
  where event.user_id = p_user_id and event.event_id = p_event_id;
  return query select false, stored_received_at;
end;
$$;

revoke all on function public.record_product_event(
  uuid, uuid, integer, text, timestamptz, jsonb
) from public;
grant execute on function public.record_product_event(
  uuid, uuid, integer, text, timestamptz, jsonb
) to service_role;

notify pgrst, 'reload schema';
