-- Business organization membership and edition-license authority.
-- Browser roles may only read their own membership/license rows. Every
-- mutation is performed through service-role RPCs after an Edge Function has
-- verified the caller JWT; the RPCs repeat the hierarchy checks transactionally.

create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(btrim(name)) between 2 and 96),
  owner_user_id uuid not null unique references auth.users(id) on delete restrict,
  plan_id text not null references public.model_subscription_plans(plan_id)
    check (plan_id in ('plus', 'pro')),
  status text not null default 'active'
    check (status in ('active', 'suspended')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.organization_members (
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null unique references auth.users(id) on delete cascade,
  role text not null check (role in ('owner', 'admin', 'member')),
  joined_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (organization_id, user_id)
);

create index if not exists organization_members_role_idx
  on public.organization_members (organization_id, role, user_id);

create table if not exists public.user_software_licenses (
  user_id uuid not null references auth.users(id) on delete cascade,
  edition text not null check (edition in ('universal', 'sim', 'lab', 'field')),
  status text not null default 'active'
    check (status in ('active', 'expired', 'revoked')),
  source text not null default 'purchase'
    check (source in ('purchase', 'organization', 'grant')),
  organization_id uuid references public.organizations(id) on delete cascade,
  granted_at timestamptz not null default now(),
  expires_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (user_id, edition),
  check (
    (source = 'organization' and organization_id is not null)
    or (source <> 'organization' and organization_id is null)
  )
);

create table if not exists public.organization_audit_log (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  actor_user_id uuid not null references auth.users(id) on delete restrict,
  action text not null check (action in (
    'organization.created', 'member.added', 'member.role_changed', 'member.removed'
  )),
  target_user_id uuid references auth.users(id) on delete restrict,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (jsonb_typeof(metadata) = 'object'),
  check (octet_length(metadata::text) <= 2048)
);

alter table public.account_entitlements
  add column if not exists billing_scope text not null default 'individual'
    check (billing_scope in ('individual', 'business')),
  add column if not exists organization_id uuid
    references public.organizations(id) on delete set null;

alter table public.account_entitlements
  drop constraint if exists account_entitlements_scope_shape;
alter table public.account_entitlements
  add constraint account_entitlements_scope_shape check (
    (billing_scope = 'individual' and organization_id is null)
    or (billing_scope = 'business' and organization_id is not null)
  );

alter table public.payment_orders
  add column if not exists billing_scope text not null default 'individual'
    check (billing_scope in ('individual', 'business')),
  add column if not exists organization_id uuid
    references public.organizations(id) on delete restrict;

alter table public.payment_orders
  drop constraint if exists payment_orders_scope_shape;
alter table public.payment_orders
  add constraint payment_orders_scope_shape check (
    (billing_scope = 'individual' and organization_id is null)
    or (billing_scope = 'business' and organization_id is not null)
  );

alter table public.organizations enable row level security;
alter table public.organization_members enable row level security;
alter table public.user_software_licenses enable row level security;
alter table public.organization_audit_log enable row level security;

revoke all on table public.organizations from anon, authenticated;
revoke all on table public.organization_members from anon, authenticated;
revoke all on table public.user_software_licenses from anon, authenticated;
revoke all on table public.organization_audit_log from anon, authenticated;
grant all on table public.organizations to service_role;
grant all on table public.organization_members to service_role;
grant all on table public.user_software_licenses to service_role;
grant all on table public.organization_audit_log to service_role;

create policy "Users read their own organization membership"
  on public.organization_members
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy "Users read their own software licenses"
  on public.user_software_licenses
  for select to authenticated
  using (user_id = (select auth.uid()));

create or replace function public.organization_audit_append_only()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception using errcode = '42501', message = 'ORGANIZATION_AUDIT_APPEND_ONLY';
end;
$$;

revoke all on function public.organization_audit_append_only() from public;
drop trigger if exists organization_audit_log_append_only
  on public.organization_audit_log;
create trigger organization_audit_log_append_only
  before update or delete on public.organization_audit_log
  for each row execute function public.organization_audit_append_only();

create or replace function public.organization_enforce_admin_limit()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  admin_count integer;
begin
  if new.role <> 'admin' then
    return new;
  end if;
  perform pg_advisory_xact_lock(hashtextextended(new.organization_id::text, 0));
  select count(*) into admin_count
  from public.organization_members
  where organization_id = new.organization_id
    and role = 'admin'
    and user_id <> new.user_id;
  if admin_count >= 3 then
    raise exception using errcode = '23514', message = 'ORGANIZATION_ADMIN_LIMIT';
  end if;
  return new;
end;
$$;

revoke all on function public.organization_enforce_admin_limit() from public;
drop trigger if exists organization_members_admin_limit
  on public.organization_members;
create trigger organization_members_admin_limit
  before insert or update of role on public.organization_members
  for each row execute function public.organization_enforce_admin_limit();

create or replace function public.organization_assert_actor(
  p_actor_user_id uuid,
  p_required_owner boolean default false
)
returns public.organization_members
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
begin
  select * into actor
  from public.organization_members
  where user_id = p_actor_user_id
  for share;
  if actor.user_id is null
    or actor.role not in ('owner', 'admin')
    or (p_required_owner and actor.role <> 'owner')
  then
    raise exception using errcode = '42501', message = 'ORGANIZATION_PERMISSION_REQUIRED';
  end if;
  return actor;
end;
$$;

revoke all on function public.organization_assert_actor(uuid, boolean) from public;
grant execute on function public.organization_assert_actor(uuid, boolean) to service_role;

create or replace function public.organization_find_user_id_by_email(p_email text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  matched_user_id uuid;
begin
  if char_length(btrim(coalesce(p_email, ''))) not between 3 and 320 then
    raise exception using errcode = '22023', message = 'ORGANIZATION_EMAIL_INVALID';
  end if;
  select id into matched_user_id
  from auth.users
  where lower(email) = lower(btrim(p_email));
  if matched_user_id is null then
    raise exception using errcode = 'P0002', message = 'ORGANIZATION_USER_NOT_FOUND';
  end if;
  return matched_user_id;
end;
$$;

revoke all on function public.organization_find_user_id_by_email(text) from public;
grant execute on function public.organization_find_user_id_by_email(text) to service_role;

create or replace function public.organization_create(
  p_owner_user_id uuid,
  p_name text,
  p_plan_id text
)
returns public.organizations
language plpgsql
security definer
set search_path = ''
as $$
declare
  organization public.organizations%rowtype;
begin
  if p_owner_user_id is null
    or char_length(btrim(coalesce(p_name, ''))) not between 2 and 96
    or p_plan_id not in ('plus', 'pro')
  then
    raise exception using errcode = '22023', message = 'ORGANIZATION_CREATE_INVALID';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_owner_user_id::text, 0));
  if exists (select 1 from public.organization_members where user_id = p_owner_user_id) then
    raise exception using errcode = '23505', message = 'ORGANIZATION_MEMBER_EXISTS';
  end if;
  insert into public.organizations (name, owner_user_id, plan_id)
  values (btrim(p_name), p_owner_user_id, p_plan_id)
  returning * into organization;
  insert into public.organization_members (organization_id, user_id, role)
  values (organization.id, p_owner_user_id, 'owner');
  insert into public.account_entitlements (
    user_id, plan_id, status, current_period_start, current_period_end,
    source, billing_scope, organization_id
  ) values (
    p_owner_user_id, p_plan_id, 'active', now(), now() + interval '1 month',
    'admin', 'business', organization.id
  )
  on conflict (user_id) do update
  set plan_id = excluded.plan_id,
      status = 'active',
      current_period_start = excluded.current_period_start,
      current_period_end = excluded.current_period_end,
      source = 'admin',
      billing_scope = 'business',
      organization_id = excluded.organization_id,
      payment_provider = null,
      provider_subscription_reference = null,
      updated_at = now();
  insert into public.organization_audit_log (
    organization_id, actor_user_id, action, target_user_id,
    metadata
  ) values (
    organization.id, p_owner_user_id, 'organization.created', p_owner_user_id,
    jsonb_build_object('plan_id', p_plan_id)
  );
  return organization;
end;
$$;

revoke all on function public.organization_create(uuid, text, text) from public;
grant execute on function public.organization_create(uuid, text, text) to service_role;

create or replace function public.organization_add_member(
  p_actor_user_id uuid,
  p_target_user_id uuid,
  p_role text default 'member'
)
returns public.organization_members
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
  organization public.organizations%rowtype;
  member public.organization_members%rowtype;
begin
  if p_target_user_id is null or p_role not in ('admin', 'member') then
    raise exception using errcode = '22023', message = 'ORGANIZATION_MEMBER_INVALID';
  end if;
  actor := public.organization_assert_actor(p_actor_user_id, p_role = 'admin');
  perform pg_advisory_xact_lock(hashtextextended(actor.organization_id::text, 0));
  if exists (
    select 1 from public.organization_members where user_id = p_target_user_id
  ) then
    raise exception using errcode = '23505', message = 'ORGANIZATION_MEMBER_EXISTS';
  end if;
  select * into organization from public.organizations
  where id = actor.organization_id and status = 'active'
  for update;
  if organization.id is null then
    raise exception using errcode = '42501', message = 'ORGANIZATION_NOT_ACTIVE';
  end if;
  insert into public.organization_members (organization_id, user_id, role)
  values (actor.organization_id, p_target_user_id, p_role)
  returning * into member;
  insert into public.account_entitlements (
    user_id, plan_id, status, current_period_start, current_period_end,
    source, billing_scope, organization_id
  ) values (
    p_target_user_id, organization.plan_id, 'active', now(),
    now() + interval '1 month', 'admin', 'business', organization.id
  )
  on conflict (user_id) do update
  set plan_id = excluded.plan_id,
      status = 'active',
      current_period_start = excluded.current_period_start,
      current_period_end = excluded.current_period_end,
      source = 'admin',
      billing_scope = 'business',
      organization_id = excluded.organization_id,
      payment_provider = null,
      provider_subscription_reference = null,
      updated_at = now();
  insert into public.organization_audit_log (
    organization_id, actor_user_id, action, target_user_id, metadata
  ) values (
    actor.organization_id, p_actor_user_id, 'member.added', p_target_user_id,
    jsonb_build_object('role', p_role)
  );
  return member;
end;
$$;

revoke all on function public.organization_add_member(uuid, uuid, text) from public;
grant execute on function public.organization_add_member(uuid, uuid, text) to service_role;

create or replace function public.organization_set_member_role(
  p_actor_user_id uuid,
  p_target_user_id uuid,
  p_role text
)
returns public.organization_members
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
  target public.organization_members%rowtype;
begin
  if p_role not in ('admin', 'member') then
    raise exception using errcode = '22023', message = 'ORGANIZATION_ROLE_INVALID';
  end if;
  actor := public.organization_assert_actor(p_actor_user_id, true);
  perform pg_advisory_xact_lock(hashtextextended(actor.organization_id::text, 0));
  select * into target from public.organization_members
  where organization_id = actor.organization_id and user_id = p_target_user_id
  for update;
  if target.user_id is null or target.role = 'owner' then
    raise exception using errcode = '42501', message = 'ORGANIZATION_TARGET_PROTECTED';
  end if;
  update public.organization_members
  set role = p_role, updated_at = now()
  where organization_id = actor.organization_id and user_id = p_target_user_id
  returning * into target;
  insert into public.organization_audit_log (
    organization_id, actor_user_id, action, target_user_id, metadata
  ) values (
    actor.organization_id, p_actor_user_id, 'member.role_changed', p_target_user_id,
    jsonb_build_object('role', p_role)
  );
  return target;
end;
$$;

revoke all on function public.organization_set_member_role(uuid, uuid, text) from public;
grant execute on function public.organization_set_member_role(uuid, uuid, text) to service_role;

create or replace function public.organization_remove_member(
  p_actor_user_id uuid,
  p_target_user_id uuid
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
  target public.organization_members%rowtype;
begin
  actor := public.organization_assert_actor(p_actor_user_id, false);
  perform pg_advisory_xact_lock(hashtextextended(actor.organization_id::text, 0));
  select * into target from public.organization_members
  where organization_id = actor.organization_id and user_id = p_target_user_id
  for update;
  if target.user_id is null or target.role = 'owner'
    or (actor.role = 'admin' and target.role <> 'member')
  then
    raise exception using errcode = '42501', message = 'ORGANIZATION_TARGET_PROTECTED';
  end if;
  delete from public.organization_members
  where organization_id = actor.organization_id and user_id = p_target_user_id;
  delete from public.user_software_licenses
  where user_id = p_target_user_id
    and organization_id = actor.organization_id
    and source = 'organization';
  insert into public.account_entitlements (
    user_id, plan_id, status, current_period_start, current_period_end,
    source, billing_scope, organization_id
  ) values (
    p_target_user_id, 'free', 'active',
    date_trunc('month', now()), date_trunc('month', now()) + interval '1 month',
    'free', 'individual', null
  )
  on conflict (user_id) do update
  set plan_id = 'free',
      status = 'active',
      current_period_start = excluded.current_period_start,
      current_period_end = excluded.current_period_end,
      source = 'free',
      billing_scope = 'individual',
      organization_id = null,
      payment_provider = null,
      provider_subscription_reference = null,
      updated_at = now();
  insert into public.organization_audit_log (
    organization_id, actor_user_id, action, target_user_id
  ) values (
    actor.organization_id, p_actor_user_id, 'member.removed', p_target_user_id
  );
  return p_target_user_id;
end;
$$;

revoke all on function public.organization_remove_member(uuid, uuid) from public;
grant execute on function public.organization_remove_member(uuid, uuid) to service_role;

notify pgrst, 'reload schema';
