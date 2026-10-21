alter table public.organizations
  add column if not exists join_password_hash text;

alter table public.organization_audit_log
  drop constraint if exists organization_audit_log_action_check;
alter table public.organization_audit_log
  add constraint organization_audit_log_action_check check (action in (
    'organization.created', 'organization.plan_changed', 'organization.profile_changed',
    'organization.password_changed', 'founder.transferred', 'member.added',
    'member.role_changed', 'member.plan_changed', 'member.removed'
  ));

create or replace function public.organization_set_join_password(
  p_actor_user_id uuid,
  p_password text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
begin
  if char_length(coalesce(p_password, '')) not between 8 and 72 then
    raise exception using errcode = '22023', message = 'ORGANIZATION_PASSWORD_INVALID';
  end if;
  actor := public.organization_assert_actor(p_actor_user_id, true);
  update public.organizations
  set join_password_hash = extensions.crypt(p_password, extensions.gen_salt('bf', 12)),
      updated_at = now()
  where organization_id = actor.organization_id;
  insert into public.organization_audit_log (
    organization_id, actor_user_id, action, target_user_id, metadata
  ) values (
    actor.organization_id, actor.user_id, 'organization.password_changed',
    actor.user_id, '{}'::jsonb
  );
end;
$$;
revoke all on function public.organization_set_join_password(uuid, text) from public;
grant execute on function public.organization_set_join_password(uuid, text) to service_role;

create or replace function public.organization_update_profile(
  p_actor_user_id uuid,
  p_name text,
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
  if char_length(btrim(coalesce(p_name, ''))) not between 1 and 120
    or p_plan_id not in ('free', 'plus', 'pro')
  then
    raise exception using errcode = '22023', message = 'ORGANIZATION_PROFILE_INVALID';
  end if;
  actor := public.organization_assert_actor(p_actor_user_id, true);
  perform public.organization_set_founder_plan(actor.user_id, p_plan_id);
  update public.organizations
  set name = btrim(p_name), updated_at = now()
  where organization_id = actor.organization_id
  returning * into organization;
  insert into public.organization_audit_log (
    organization_id, actor_user_id, action, target_user_id, metadata
  ) values (
    actor.organization_id, actor.user_id, 'organization.profile_changed',
    actor.user_id, jsonb_build_object('name', organization.name)
  );
  return organization;
end;
$$;
revoke all on function public.organization_update_profile(uuid, text, text) from public;
grant execute on function public.organization_update_profile(uuid, text, text) to service_role;

create or replace function public.organization_create_v3(
  p_founder_user_id uuid,
  p_name text,
  p_description text,
  p_structure_model text,
  p_founder_plan text,
  p_password text
)
returns public.organizations
language plpgsql
security definer
set search_path = ''
as $$
declare
  organization public.organizations%rowtype;
  created_organization_id uuid;
begin
  organization := public.organization_create_v2(
    p_founder_user_id, p_name, p_description, p_structure_model, p_founder_plan
  );
  created_organization_id := organization.organization_id;
  perform public.organization_set_join_password(p_founder_user_id, p_password);
  select * into organization from public.organizations
  where organization_id = created_organization_id;
  return organization;
end;
$$;
revoke all on function public.organization_create_v3(uuid, text, text, text, text, text) from public;
grant execute on function public.organization_create_v3(uuid, text, text, text, text, text) to service_role;

drop function if exists public.organization_request_join(uuid, text, text);
create function public.organization_request_join(
  p_user_id uuid,
  p_public_code text,
  p_plan_id text,
  p_password text
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
  if p_user_id is null or p_plan_id not in ('free', 'plus', 'pro')
    or char_length(coalesce(p_password, '')) not between 1 and 72
  then
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
  if organization.join_password_hash is null
    or extensions.crypt(p_password, organization.join_password_hash) <> organization.join_password_hash
  then
    raise exception using errcode = '28000', message = 'ORGANIZATION_PASSWORD_INCORRECT';
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
revoke all on function public.organization_request_join(uuid, text, text, text) from public;
grant execute on function public.organization_request_join(uuid, text, text, text) to service_role;
