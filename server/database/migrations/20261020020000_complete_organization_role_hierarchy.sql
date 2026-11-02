-- Complete the Business organization hierarchy. The persisted `owner` role is
-- the single Founder shown by the product UI.

create sequence if not exists public.organization_public_code_seq start with 1;

alter table public.organizations
  add column if not exists public_code text,
  add column if not exists description text not null default '',
  add column if not exists structure_model text not null default 'flat';

alter table public.organizations
  drop constraint if exists organizations_plan_check;
alter table public.organizations
  add constraint organizations_plan_check check (plan in ('free', 'plus', 'pro'));

update public.organizations
set public_code = 'DD' || lpad(
  nextval('public.organization_public_code_seq')::text, 5, '0'
)
where public_code is null;

alter table public.organizations
  alter column public_code set not null,
  alter column public_code set default (
    'DD' || lpad(nextval('public.organization_public_code_seq')::text, 5, '0')
  );

alter table public.organizations
  drop constraint if exists organizations_public_code_format,
  add constraint organizations_public_code_format
    check (public_code ~ '^DD[0-9]{5}$'),
  drop constraint if exists organizations_description_length,
  add constraint organizations_description_length
    check (char_length(description) <= 500),
  drop constraint if exists organizations_structure_model,
  add constraint organizations_structure_model check (
    structure_model in ('flat', 'department_single', 'department_dual')
  );

create unique index if not exists organizations_public_code_idx
  on public.organizations (public_code);

create table if not exists public.organization_departments (
  department_id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(organization_id)
    on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  created_at timestamptz not null default now(),
  unique (organization_id, name)
);

create table if not exists public.organization_department_assignments (
  department_id uuid not null references public.organization_departments(department_id)
    on delete cascade,
  organization_id uuid not null references public.organizations(organization_id)
    on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  assignment_role text not null check (assignment_role in ('manager', 'member')),
  created_at timestamptz not null default now(),
  primary key (department_id, user_id),
  unique (organization_id, user_id)
);

create table if not exists public.organization_join_requests (
  request_id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(organization_id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  requested_plan text not null check (requested_plan in ('free', 'plus', 'pro')),
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz,
  reviewed_by uuid references auth.users(id) on delete restrict
);
create unique index if not exists organization_join_requests_pending_idx
  on public.organization_join_requests (user_id) where status = 'pending';

alter table public.organization_departments enable row level security;
alter table public.organization_department_assignments enable row level security;
alter table public.organization_join_requests enable row level security;
revoke all on table public.organization_departments from anon, authenticated;
revoke all on table public.organization_department_assignments from anon, authenticated;
revoke all on table public.organization_join_requests from anon, authenticated;
grant all on table public.organization_departments to service_role;
grant all on table public.organization_department_assignments to service_role;
grant all on table public.organization_join_requests to service_role;

alter table public.organization_audit_log
  drop constraint if exists organization_audit_log_action_check;
alter table public.organization_audit_log
  add constraint organization_audit_log_action_check check (action in (
    'organization.created', 'organization.plan_changed', 'founder.transferred',
    'member.added', 'member.role_changed', 'member.plan_changed', 'member.removed'
  ));

grant usage, select on sequence public.organization_public_code_seq to service_role;

create or replace function public.organization_create_v2(
  p_founder_user_id uuid,
  p_name text,
  p_description text,
  p_structure_model text,
  p_founder_plan text
)
returns public.organizations
language plpgsql
security definer
set search_path = ''
as $$
declare
  organization public.organizations%rowtype;
begin
  if p_founder_user_id is null
    or char_length(btrim(coalesce(p_name, ''))) not between 1 and 120
    or char_length(btrim(coalesce(p_description, ''))) > 500
    or p_structure_model not in ('flat', 'department_single', 'department_dual')
    or p_founder_plan not in ('free', 'plus', 'pro')
  then
    raise exception using errcode = '22023', message = 'ORGANIZATION_CREATE_INVALID';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_founder_user_id::text, 0));
  if exists (
    select 1 from public.organization_members
    where user_id = p_founder_user_id and status = 'active'
  ) then
    raise exception using errcode = '23505', message = 'ORGANIZATION_MEMBER_EXISTS';
  end if;
  insert into public.organizations (
    name, description, structure_model, owner_user_id, plan
  ) values (
    btrim(p_name), btrim(coalesce(p_description, '')), p_structure_model,
    p_founder_user_id, p_founder_plan
  ) returning * into organization;
  insert into public.account_entitlements (
    user_id, plan_id, status, current_period_start, current_period_end,
    source, billing_scope, organization_id
  ) values (
    p_founder_user_id, p_founder_plan, 'active', now(), now() + interval '30 days',
    'admin', 'business', organization.organization_id
  )
  on conflict (user_id) do update
  set plan_id = excluded.plan_id, status = 'active',
      current_period_start = excluded.current_period_start,
      current_period_end = excluded.current_period_end,
      source = 'admin', billing_scope = 'business',
      organization_id = excluded.organization_id,
      payment_provider = null, provider_subscription_reference = null,
      updated_at = now();
  insert into public.organization_audit_log (
    organization_id, actor_user_id, action, target_user_id, metadata
  ) values (
    organization.organization_id, p_founder_user_id, 'organization.created',
    p_founder_user_id,
    jsonb_build_object('plan_id', p_founder_plan, 'structure_model', p_structure_model)
  );
  return organization;
end;
$$;

revoke all on function public.organization_create_v2(uuid, text, text, text, text)
  from public;
grant execute on function public.organization_create_v2(uuid, text, text, text, text)
  to service_role;

create or replace function public.organization_set_member_plan(
  p_actor_user_id uuid,
  p_target_user_id uuid,
  p_plan_id text
)
returns public.organization_members
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
  target public.organization_members%rowtype;
  structure text;
begin
  if p_plan_id not in ('free', 'plus', 'pro') then
    raise exception using errcode = '22023', message = 'ORGANIZATION_PLAN_INVALID';
  end if;
  actor := public.organization_assert_actor(p_actor_user_id, false);
  perform pg_advisory_xact_lock(hashtextextended(actor.organization_id::text, 0));
  select * into target
  from public.organization_members
  where organization_id = actor.organization_id
    and user_id = p_target_user_id
    and status = 'active'
  for update;
  if target.user_id is null
    or target.role = 'owner'
    or (actor.role = 'admin' and target.role <> 'member')
  then
    raise exception using errcode = '42501', message = 'ORGANIZATION_TARGET_PROTECTED';
  end if;
  if not exists (
    select 1 from public.organizations
    where organization_id = actor.organization_id
      and case plan
        when 'pro' then p_plan_id in ('free', 'plus', 'pro')
        when 'plus' then p_plan_id in ('free', 'plus')
        else p_plan_id = 'free'
      end
  ) then
    raise exception using errcode = '22023', message = 'ORGANIZATION_MEMBER_PLAN_EXCEEDS_FOUNDER';
  end if;
  select structure_model into structure
  from public.organizations where organization_id = actor.organization_id;
  if actor.role = 'admin' and structure <> 'flat' and not exists (
    select 1
    from public.organization_department_assignments actor_department
    join public.organization_department_assignments target_department
      on target_department.department_id = actor_department.department_id
    where actor_department.organization_id = actor.organization_id
      and actor_department.user_id = actor.user_id
      and actor_department.assignment_role = 'manager'
      and target_department.user_id = target.user_id
      and target_department.assignment_role = 'member'
  ) then
    raise exception using errcode = '42501', message = 'ORGANIZATION_DEPARTMENT_PERMISSION_REQUIRED';
  end if;

  insert into public.account_entitlements (
    user_id, plan_id, status, current_period_start, current_period_end,
    source, billing_scope, organization_id
  ) values (
    target.user_id, p_plan_id, 'active', now(), now() + interval '30 days',
    'admin', 'business', actor.organization_id
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
    actor.organization_id, actor.user_id, 'member.plan_changed', target.user_id,
    jsonb_build_object('plan_id', p_plan_id)
  );
  return target;
end;
$$;

revoke all on function public.organization_set_member_plan(uuid, uuid, text)
  from public;
grant execute on function public.organization_set_member_plan(uuid, uuid, text)
  to service_role;

create or replace function public.organization_transfer_founder(
  p_actor_user_id uuid,
  p_target_user_id uuid
)
returns public.organizations
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
  target public.organization_members%rowtype;
  organization public.organizations%rowtype;
begin
  if p_target_user_id is null or p_target_user_id = p_actor_user_id then
    raise exception using errcode = '22023', message = 'ORGANIZATION_FOUNDER_TRANSFER_INVALID';
  end if;
  actor := public.organization_assert_actor(p_actor_user_id, true);
  perform pg_advisory_xact_lock(hashtextextended(actor.organization_id::text, 0));
  select * into target
  from public.organization_members
  where organization_id = actor.organization_id
    and user_id = p_target_user_id
    and status = 'active'
  for update;
  if target.user_id is null or target.role <> 'admin' then
    raise exception using errcode = '42501', message = 'ORGANIZATION_FOUNDER_REQUIRES_ADMIN';
  end if;

  -- The unique Founder invariant is preserved inside one transaction: the
  -- current Founder steps down exactly when the selected admin steps up.
  update public.organization_members
  set role = 'member', updated_at = now()
  where organization_id = actor.organization_id and user_id = actor.user_id;
  update public.organization_members
  set role = 'owner', updated_at = now()
  where organization_id = actor.organization_id and user_id = target.user_id;
  update public.organization_members
  set role = 'admin', updated_at = now()
  where organization_id = actor.organization_id and user_id = actor.user_id;

  update public.organizations
  set owner_user_id = target.user_id, updated_at = now()
  where organization_id = actor.organization_id
  returning * into organization;

  insert into public.account_entitlements (
    user_id, plan_id, status, current_period_start, current_period_end,
    source, billing_scope, organization_id
  ) values (
    target.user_id, organization.plan, 'active', now(), now() + interval '30 days',
    'admin', 'business', actor.organization_id
  )
  on conflict (user_id) do update
  set plan_id = excluded.plan_id, status = 'active',
      current_period_start = excluded.current_period_start,
      current_period_end = excluded.current_period_end,
      source = 'admin', billing_scope = 'business',
      organization_id = excluded.organization_id,
      payment_provider = null, provider_subscription_reference = null,
      updated_at = now();

  insert into public.organization_audit_log (
    organization_id, actor_user_id, action, target_user_id,
    metadata
  ) values (
    actor.organization_id, actor.user_id, 'founder.transferred', target.user_id,
    jsonb_build_object('previous_founder_role', 'admin', 'new_founder_plan', organization.plan)
  );
  return organization;
end;
$$;

revoke all on function public.organization_transfer_founder(uuid, uuid)
  from public;
grant execute on function public.organization_transfer_founder(uuid, uuid)
  to service_role;

create or replace function public.organization_set_founder_plan(
  p_actor_user_id uuid,
  p_plan_id text
)
returns public.organizations
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
  organization public.organizations%rowtype;
begin
  if p_plan_id not in ('free', 'plus', 'pro') then
    raise exception using errcode = '22023', message = 'ORGANIZATION_PLAN_INVALID';
  end if;
  actor := public.organization_assert_actor(p_actor_user_id, true);
  perform pg_advisory_xact_lock(hashtextextended(actor.organization_id::text, 0));
  update public.organizations
  set plan = p_plan_id, updated_at = now()
  where organization_id = actor.organization_id
  returning * into organization;

  update public.account_entitlements
  set plan_id = p_plan_id, status = 'active', billing_scope = 'business',
      organization_id = actor.organization_id, updated_at = now()
  where user_id = actor.user_id;

  -- A Founder upgrade never changes members. A downgrade clamps only plans
  -- that no longer fit the new organization ceiling.
  if p_plan_id = 'free' then
    update public.account_entitlements entitlement
    set plan_id = 'free', updated_at = now()
    from public.organization_members membership
    where membership.organization_id = actor.organization_id
      and membership.user_id = entitlement.user_id
      and membership.user_id <> actor.user_id
      and membership.status = 'active'
      and entitlement.plan_id <> 'free';
  elsif p_plan_id = 'plus' then
    update public.account_entitlements entitlement
    set plan_id = 'plus', updated_at = now()
    from public.organization_members membership
    where membership.organization_id = actor.organization_id
      and membership.user_id = entitlement.user_id
      and membership.user_id <> actor.user_id
      and membership.status = 'active'
      and entitlement.plan_id = 'pro';
  end if;

  insert into public.organization_audit_log (
    organization_id, actor_user_id, action, target_user_id, metadata
  ) values (
    actor.organization_id, actor.user_id, 'organization.plan_changed',
    actor.user_id, jsonb_build_object('plan_id', p_plan_id)
  );
  return organization;
end;
$$;

revoke all on function public.organization_set_founder_plan(uuid, text)
  from public;
grant execute on function public.organization_set_founder_plan(uuid, text)
  to service_role;

create or replace function public.organization_create_department(
  p_actor_user_id uuid,
  p_name text
)
returns public.organization_departments
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
  department public.organization_departments%rowtype;
begin
  if char_length(btrim(coalesce(p_name, ''))) not between 1 and 80 then
    raise exception using errcode = '22023', message = 'ORGANIZATION_DEPARTMENT_INVALID';
  end if;
  actor := public.organization_assert_actor(p_actor_user_id, true);
  if not exists (
    select 1 from public.organizations
    where organization_id = actor.organization_id
      and structure_model in ('department_single', 'department_dual')
  ) then
    raise exception using errcode = '22023', message = 'ORGANIZATION_DEPARTMENTS_DISABLED';
  end if;
  insert into public.organization_departments (organization_id, name)
  values (actor.organization_id, btrim(p_name))
  returning * into department;
  return department;
end;
$$;

revoke all on function public.organization_create_department(uuid, text) from public;
grant execute on function public.organization_create_department(uuid, text) to service_role;

create or replace function public.organization_assign_department(
  p_actor_user_id uuid,
  p_target_user_id uuid,
  p_department_id uuid
)
returns public.organization_department_assignments
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
  target public.organization_members%rowtype;
  assignment public.organization_department_assignments%rowtype;
  structure text;
  manager_limit integer;
begin
  actor := public.organization_assert_actor(p_actor_user_id, true);
  perform pg_advisory_xact_lock(hashtextextended(actor.organization_id::text, 0));
  select * into target from public.organization_members
  where organization_id = actor.organization_id and user_id = p_target_user_id
    and status = 'active' for update;
  select structure_model into structure from public.organizations
  where organization_id = actor.organization_id;
  if target.user_id is null or target.role = 'owner' or structure = 'flat'
    or not exists (
      select 1 from public.organization_departments
      where department_id = p_department_id
        and organization_id = actor.organization_id
    )
  then
    raise exception using errcode = '22023', message = 'ORGANIZATION_DEPARTMENT_ASSIGNMENT_INVALID';
  end if;
  if target.role = 'admin' then
    manager_limit := case when structure = 'department_single' then 1 else 2 end;
    if (
      select count(*) from public.organization_department_assignments
      where department_id = p_department_id and assignment_role = 'manager'
        and user_id <> target.user_id
    ) >= manager_limit then
      raise exception using errcode = '23514', message = 'ORGANIZATION_DEPARTMENT_MANAGER_LIMIT';
    end if;
  end if;
  delete from public.organization_department_assignments
  where organization_id = actor.organization_id and user_id = target.user_id;
  insert into public.organization_department_assignments (
    department_id, organization_id, user_id, assignment_role
  ) values (
    p_department_id, actor.organization_id, target.user_id,
    case when target.role = 'admin' then 'manager' else 'member' end
  ) returning * into assignment;
  return assignment;
end;
$$;

revoke all on function public.organization_assign_department(uuid, uuid, uuid)
  from public;
grant execute on function public.organization_assign_department(uuid, uuid, uuid)
  to service_role;

create or replace function public.organization_request_join(
  p_user_id uuid,
  p_public_code text,
  p_plan_id text
)
returns public.organization_join_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  organization public.organizations%rowtype;
  request public.organization_join_requests%rowtype;
begin
  if p_user_id is null or p_plan_id not in ('free', 'plus', 'pro') then
    raise exception using errcode = '22023', message = 'ORGANIZATION_JOIN_INVALID';
  end if;
  if exists (select 1 from public.organization_members where user_id = p_user_id and status = 'active') then
    raise exception using errcode = '23505', message = 'ORGANIZATION_MEMBER_EXISTS';
  end if;
  select * into organization from public.organizations
  where public_code = upper(btrim(p_public_code)) and status = 'active';
  if organization.organization_id is null then
    raise exception using errcode = 'P0002', message = 'ORGANIZATION_NOT_FOUND';
  end if;
  if (organization.plan = 'free' and p_plan_id <> 'free')
    or (organization.plan = 'plus' and p_plan_id = 'pro')
  then
    raise exception using errcode = '23514', message = 'ORGANIZATION_MEMBER_PLAN_EXCEEDS_FOUNDER';
  end if;
  insert into public.organization_join_requests (organization_id, user_id, requested_plan)
  values (organization.organization_id, p_user_id, p_plan_id)
  returning * into request;
  return request;
end;
$$;
revoke all on function public.organization_request_join(uuid, text, text) from public;
grant execute on function public.organization_request_join(uuid, text, text) to service_role;

create or replace function public.organization_review_join_request(
  p_actor_user_id uuid,
  p_request_id uuid,
  p_approved boolean
)
returns public.organization_join_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
  request public.organization_join_requests%rowtype;
begin
  actor := public.organization_assert_actor(p_actor_user_id, true);
  select * into request from public.organization_join_requests
  where request_id = p_request_id and organization_id = actor.organization_id
    and status = 'pending' for update;
  if request.request_id is null then
    raise exception using errcode = 'P0002', message = 'ORGANIZATION_JOIN_REQUEST_NOT_FOUND';
  end if;
  if p_approved then
    perform public.organization_add_member(actor.user_id, request.user_id, 'member');
    perform public.organization_set_member_plan(actor.user_id, request.user_id, request.requested_plan);
  end if;
  update public.organization_join_requests
  set status = case when p_approved then 'approved' else 'rejected' end,
      reviewed_at = now(), reviewed_by = actor.user_id
  where request_id = request.request_id
  returning * into request;
  return request;
end;
$$;
revoke all on function public.organization_review_join_request(uuid, uuid, boolean) from public;
grant execute on function public.organization_review_join_request(uuid, uuid, boolean) to service_role;
