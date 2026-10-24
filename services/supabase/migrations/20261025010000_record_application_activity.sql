create table if not exists public.user_application_activity (
  user_id uuid not null references auth.users(id) on delete cascade,
  edition text not null
    check (edition in ('universal', 'sim', 'lab', 'field', 'autonomy')),
  first_signed_in_at timestamptz not null default now(),
  last_signed_in_at timestamptz not null default now(),
  primary key (user_id, edition)
);

alter table public.user_application_activity enable row level security;
revoke all on table public.user_application_activity from anon, authenticated;
grant select on table public.user_application_activity to authenticated;
grant all on table public.user_application_activity to service_role;

drop policy if exists "Users read their own application activity"
  on public.user_application_activity;
create policy "Users read their own application activity"
  on public.user_application_activity
  for select to authenticated
  using (user_id = (select auth.uid()));

create or replace function public.record_user_application_activity(p_edition text)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  current_user_id uuid := auth.uid();
begin
  if current_user_id is null then
    raise exception using errcode = '42501', message = 'AUTH_REQUIRED';
  end if;
  if p_edition not in ('universal', 'sim', 'lab', 'field', 'autonomy') then
    raise exception using errcode = '22023', message = 'INVALID_EDITION';
  end if;

  insert into public.user_application_activity (
    user_id, edition, first_signed_in_at, last_signed_in_at
  ) values (
    current_user_id, p_edition, now(), now()
  )
  on conflict (user_id, edition) do update
    set last_signed_in_at = excluded.last_signed_in_at;
end;
$$;

revoke all on function public.record_user_application_activity(text) from public;
grant execute on function public.record_user_application_activity(text) to authenticated;
