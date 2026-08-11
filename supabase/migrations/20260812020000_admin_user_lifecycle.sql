-- Owner-only user-account deletion with an atomic audit receipt.
--
-- This operation intentionally refuses to delete administrators, organization
-- owners, or accounts whose immutable financial/administrative history is
-- protected by restrictive foreign keys.  Those accounts require a separate
-- retention-aware lifecycle rather than a destructive shortcut.

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

create or replace function public.admin_bootstrap_owner(p_user_id uuid)
returns public.app_admins
language plpgsql
security definer
set search_path = ''
as $$
declare
  owner_row public.app_admins%rowtype;
begin
  if p_user_id is null or not exists (select 1 from auth.users where id = p_user_id) then
    raise exception using errcode = '22023', message = 'ADMIN_BOOTSTRAP_USER_INVALID';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('dronedream-admin-owner', 0));
  select * into owner_row
  from public.app_admins
  where role = 'owner' and active
  for update;
  if owner_row.user_id is not null and owner_row.user_id <> p_user_id then
    raise exception using errcode = '42501', message = 'ADMIN_OWNER_ALREADY_BOUND';
  end if;
  insert into public.app_admins (user_id, role, permissions, active)
  values (
    p_user_id,
    'owner',
    array[
      'dashboard.read', 'models.read', 'models.write', 'users.read',
      'users.export', 'users.delete', 'community.read', 'community.remove',
      'audit.read'
    ]::text[],
    true
  )
  on conflict (user_id) do update
  set role = 'owner', permissions = excluded.permissions, active = true,
      updated_at = now()
  returning * into owner_row;
  return owner_row;
end;
$$;

revoke all on function public.admin_bootstrap_owner(uuid) from public;
grant execute on function public.admin_bootstrap_owner(uuid) to service_role;

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
    raise exception using errcode = '42501', message = 'ADMIN_USER_DELETE_OWNER_REQUIRED';
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
    or exists (select 1 from public.organizations where owner_user_id = p_target_user_id)
    or exists (select 1 from public.admin_audit_log where actor_user_id = p_target_user_id)
    or exists (select 1 from public.organization_audit_log where actor_user_id = p_target_user_id or target_user_id = p_target_user_id)
    or exists (select 1 from public.payment_orders where user_id = p_target_user_id)
    or exists (select 1 from public.model_provider_policies where updated_by = p_target_user_id)
    or exists (select 1 from public.community_topics where hidden_by = p_target_user_id)
  then
    raise exception using errcode = '23503', message = 'ADMIN_USER_DELETE_RETENTION_REQUIRED';
  end if;

  insert into public.admin_audit_log (
    actor_user_id, action, target_type, target_id, reason, metadata
  ) values (
    p_actor_user_id,
    'user.deleted',
    'user_account',
    p_target_user_id::text,
    btrim(p_reason),
    '{}'::jsonb
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
