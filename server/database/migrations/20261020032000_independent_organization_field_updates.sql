create or replace function public.organization_update_name(
  p_actor_user_id uuid,
  p_name text
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.organization_members%rowtype;
begin
  if char_length(btrim(coalesce(p_name, ''))) not between 1 and 120 then
    raise exception using errcode = '22023', message = 'ORGANIZATION_NAME_INVALID';
  end if;

  actor := public.organization_assert_actor(p_actor_user_id, true);

  update public.organizations
  set name = btrim(p_name), updated_at = now()
  where organization_id = actor.organization_id;

  insert into public.organization_audit_log (
    organization_id,
    actor_user_id,
    action,
    target_user_id,
    metadata
  ) values (
    actor.organization_id,
    actor.user_id,
    'organization.profile_changed',
    actor.user_id,
    jsonb_build_object('field', 'name', 'name', btrim(p_name))
  );
end;
$$;

revoke all on function public.organization_update_name(uuid, text) from public;
grant execute on function public.organization_update_name(uuid, text) to service_role;
