-- Restore the account-level cloud contracts that were lost when the website
-- and five-edition histories were consolidated.  The current organization
-- tables use organization_id/plan and soft membership removal, so this
-- migration deliberately extends that live schema instead of replaying the
-- incompatible legacy organization migration.

create table if not exists public.user_software_licenses (
  user_id uuid not null references auth.users(id) on delete cascade,
  edition text not null
    check (edition in ('universal', 'sim', 'lab', 'field', 'autonomy')),
  status text not null default 'active'
    check (status in ('active', 'expired', 'revoked')),
  source text not null default 'purchase'
    check (source in ('purchase', 'organization', 'grant')),
  organization_id uuid
    references public.organizations(organization_id) on delete cascade,
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
  organization_id uuid not null
    references public.organizations(organization_id) on delete cascade,
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
    references public.organizations(organization_id) on delete set null;

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
    references public.organizations(organization_id) on delete restrict;

alter table public.payment_orders
  drop constraint if exists payment_orders_scope_shape;
alter table public.payment_orders
  add constraint payment_orders_scope_shape check (
    (billing_scope = 'individual' and organization_id is null)
    or (billing_scope = 'business' and organization_id is not null)
  );

alter table public.user_software_licenses enable row level security;
alter table public.organization_audit_log enable row level security;

revoke all on table public.user_software_licenses from anon, authenticated;
revoke all on table public.organization_audit_log from anon, authenticated;
grant select on table public.user_software_licenses to authenticated;
grant all on table public.user_software_licenses to service_role;
grant all on table public.organization_audit_log to service_role;

drop policy if exists "Users read their own software licenses"
  on public.user_software_licenses;
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
  raise exception using
    errcode = '42501', message = 'ORGANIZATION_AUDIT_APPEND_ONLY';
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
  if new.role <> 'admin' or new.status <> 'active' then
    return new;
  end if;
  perform pg_advisory_xact_lock(hashtextextended(new.organization_id::text, 0));
  select count(*) into admin_count
  from public.organization_members
  where organization_id = new.organization_id
    and role = 'admin'
    and status = 'active'
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
  before insert or update of role, status on public.organization_members
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
  select membership.* into actor
  from public.organization_members membership
  join public.organizations organization
    on organization.organization_id = membership.organization_id
  where membership.user_id = p_actor_user_id
    and membership.status = 'active'
    and organization.status = 'active'
  for share of membership;
  if actor.user_id is null
    or actor.role not in ('owner', 'admin')
    or (p_required_owner and actor.role <> 'owner')
  then
    raise exception using
      errcode = '42501', message = 'ORGANIZATION_PERMISSION_REQUIRED';
  end if;
  return actor;
end;
$$;

revoke all on function public.organization_assert_actor(uuid, boolean) from public;
grant execute on function public.organization_assert_actor(uuid, boolean)
  to service_role;

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
grant execute on function public.organization_find_user_id_by_email(text)
  to service_role;

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
    or char_length(btrim(coalesce(p_name, ''))) not between 1 and 120
    or p_plan_id not in ('plus', 'pro')
  then
    raise exception using errcode = '22023', message = 'ORGANIZATION_CREATE_INVALID';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_owner_user_id::text, 0));
  if exists (
    select 1 from public.organization_members
    where user_id = p_owner_user_id and status = 'active'
  ) then
    raise exception using errcode = '23505', message = 'ORGANIZATION_MEMBER_EXISTS';
  end if;
  insert into public.organizations (name, owner_user_id, plan)
  values (btrim(p_name), p_owner_user_id, p_plan_id)
  returning * into organization;
  insert into public.account_entitlements (
    user_id, plan_id, status, current_period_start, current_period_end,
    source, billing_scope, organization_id
  ) values (
    p_owner_user_id, p_plan_id, 'active', now(), now() + interval '30 days',
    'admin', 'business', organization.organization_id
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
    organization.organization_id, p_owner_user_id, 'organization.created',
    p_owner_user_id, jsonb_build_object('plan_id', p_plan_id)
  );
  return organization;
end;
$$;

revoke all on function public.organization_create(uuid, text, text) from public;
grant execute on function public.organization_create(uuid, text, text)
  to service_role;

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
    select 1 from public.organization_members
    where user_id = p_target_user_id and status = 'active'
  ) then
    raise exception using errcode = '23505', message = 'ORGANIZATION_MEMBER_EXISTS';
  end if;
  select * into organization
  from public.organizations
  where organization_id = actor.organization_id and status = 'active'
  for update;
  if organization.organization_id is null then
    raise exception using errcode = '42501', message = 'ORGANIZATION_NOT_ACTIVE';
  end if;
  insert into public.organization_members (
    organization_id, user_id, role, status
  ) values (
    actor.organization_id, p_target_user_id, p_role, 'active'
  )
  on conflict (organization_id, user_id) do update
  set role = excluded.role, status = 'active', updated_at = now()
  returning * into member;
  insert into public.account_entitlements (
    user_id, plan_id, status, current_period_start, current_period_end,
    source, billing_scope, organization_id
  ) values (
    p_target_user_id, organization.plan, 'active', now(),
    now() + interval '30 days', 'admin', 'business', organization.organization_id
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
grant execute on function public.organization_add_member(uuid, uuid, text)
  to service_role;

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
  where organization_id = actor.organization_id
    and user_id = p_target_user_id
    and status = 'active'
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
    actor.organization_id, p_actor_user_id, 'member.role_changed',
    p_target_user_id, jsonb_build_object('role', p_role)
  );
  return target;
end;
$$;

revoke all on function public.organization_set_member_role(uuid, uuid, text)
  from public;
grant execute on function public.organization_set_member_role(uuid, uuid, text)
  to service_role;

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
  where organization_id = actor.organization_id
    and user_id = p_target_user_id
    and status = 'active'
  for update;
  if target.user_id is null or target.role = 'owner'
    or (actor.role = 'admin' and target.role <> 'member')
  then
    raise exception using errcode = '42501', message = 'ORGANIZATION_TARGET_PROTECTED';
  end if;
  update public.organization_members
  set status = 'removed', updated_at = now()
  where organization_id = actor.organization_id and user_id = p_target_user_id;
  delete from public.user_software_licenses
  where user_id = p_target_user_id
    and organization_id = actor.organization_id
    and source = 'organization';
  insert into public.account_entitlements (
    user_id, plan_id, status, current_period_start, current_period_end,
    source, billing_scope, organization_id
  ) values (
    p_target_user_id, 'free', 'active', now(), now() + interval '30 days',
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
grant execute on function public.organization_remove_member(uuid, uuid)
  to service_role;

alter table public.app_admins
  drop constraint if exists app_admins_permissions_check;
alter table public.app_admins
  add constraint app_admins_permissions_check check (
    permissions <@ array[
      'dashboard.read', 'models.read', 'models.write', 'users.read',
      'users.export', 'users.delete', 'community.read', 'community.remove',
      'audit.read'
    ]::text[]
  );

update public.app_admins
set permissions = array[
      'dashboard.read', 'models.read', 'models.write', 'users.read',
      'users.export', 'users.delete', 'community.read', 'community.remove',
      'audit.read'
    ]::text[],
    updated_at = now()
where role = 'owner';

create or replace function public.admin_delete_user(
  p_actor_user_id uuid,
  p_target_user_id uuid,
  p_reason text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor_row public.app_admins%rowtype;
  target_row_id uuid;
  deleted_count integer;
begin
  if p_actor_user_id is null
    or p_target_user_id is null
    or char_length(btrim(coalesce(p_reason, ''))) not between 8 and 500
  then
    raise exception using errcode = '22023', message = 'ADMIN_USER_DELETE_INVALID';
  end if;
  if p_actor_user_id = p_target_user_id then
    raise exception using errcode = '42501', message = 'ADMIN_USER_DELETE_SELF';
  end if;
  select * into actor_row
  from public.app_admins
  where user_id = p_actor_user_id
  for share;
  if actor_row.user_id is null or actor_row.role <> 'owner' or not actor_row.active then
    raise exception using
      errcode = '42501', message = 'ADMIN_USER_DELETE_OWNER_REQUIRED';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_target_user_id::text, 0));
  select id into target_row_id
  from auth.users
  where id = p_target_user_id
  for update;
  if target_row_id is null then
    raise exception using errcode = 'P0002', message = 'ADMIN_USER_DELETE_NOT_FOUND';
  end if;
  if exists (select 1 from public.app_admins where user_id = p_target_user_id)
    or exists (
      select 1 from public.organizations where owner_user_id = p_target_user_id
    )
    or exists (
      select 1 from public.admin_audit_log where actor_user_id = p_target_user_id
    )
    or exists (
      select 1 from public.organization_audit_log
      where actor_user_id = p_target_user_id or target_user_id = p_target_user_id
    )
    or exists (
      select 1 from public.payment_orders where user_id = p_target_user_id
    )
    or exists (
      select 1 from public.model_provider_policies where updated_by = p_target_user_id
    )
    or exists (
      select 1 from public.community_topics where hidden_by = p_target_user_id
    )
  then
    raise exception using
      errcode = '23503', message = 'ADMIN_USER_DELETE_RETENTION_REQUIRED';
  end if;
  insert into public.admin_audit_log (
    actor_user_id, action, target_type, target_id, reason, metadata
  ) values (
    p_actor_user_id, 'user.deleted', 'user_account',
    p_target_user_id::text, btrim(p_reason), '{}'::jsonb
  );
  delete from auth.users where id = p_target_user_id;
  get diagnostics deleted_count = row_count;
  if deleted_count <> 1 then
    raise exception using errcode = 'P0002', message = 'ADMIN_USER_DELETE_NOT_FOUND';
  end if;
  return jsonb_build_object(
    'deleted_user_id', p_target_user_id,
    'deleted', true
  );
end;
$$;

revoke all on function public.admin_delete_user(uuid, uuid, text) from public;
grant execute on function public.admin_delete_user(uuid, uuid, text)
  to service_role;

notify pgrst, 'reload schema';
