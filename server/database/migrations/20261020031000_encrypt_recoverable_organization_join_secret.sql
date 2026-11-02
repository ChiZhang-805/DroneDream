alter table public.organizations
  add column if not exists join_password_ciphertext text;

drop function if exists public.organization_create_v3(uuid, text, text, text, text, text);
drop function if exists public.organization_set_join_password(uuid, text);

create function public.organization_set_join_password(
  p_actor_user_id uuid,
  p_password text,
  p_password_ciphertext text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
begin
  if char_length(coalesce(p_password, '')) not between 8 and 72
    or char_length(coalesce(p_password_ciphertext, '')) not between 40 and 1024
  then
    raise exception using errcode = '22023', message = 'ORGANIZATION_PASSWORD_INVALID';
  end if;
  actor := public.organization_assert_actor(p_actor_user_id, true);
  update public.organizations
  set join_password_hash = extensions.crypt(p_password, extensions.gen_salt('bf', 12)),
      join_password_ciphertext = p_password_ciphertext,
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
revoke all on function public.organization_set_join_password(uuid, text, text) from public;
grant execute on function public.organization_set_join_password(uuid, text, text) to service_role;

create function public.organization_create_v4(
  p_founder_user_id uuid,
  p_name text,
  p_description text,
  p_structure_model text,
  p_founder_plan text,
  p_password text,
  p_password_ciphertext text
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
  perform public.organization_set_join_password(
    p_founder_user_id, p_password, p_password_ciphertext
  );
  select * into organization from public.organizations
  where organization_id = created_organization_id;
  return organization;
end;
$$;
revoke all on function public.organization_create_v4(uuid, text, text, text, text, text, text) from public;
grant execute on function public.organization_create_v4(uuid, text, text, text, text, text, text) to service_role;
