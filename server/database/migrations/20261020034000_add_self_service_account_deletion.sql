-- Let an authenticated account delete itself only when no retained business,
-- billing, moderation, or audit record still requires that identity.

create or replace function public.account_delete_self(p_user_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_user_id uuid;
  deleted_count integer;
begin
  if p_user_id is null then
    raise exception using errcode = '22023', message = 'ACCOUNT_DELETE_INVALID';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));

  select id into selected_user_id
  from auth.users
  where id = p_user_id
  for update;

  if selected_user_id is null then
    raise exception using errcode = 'P0002', message = 'ACCOUNT_DELETE_NOT_FOUND';
  end if;

  if exists (select 1 from public.organizations where owner_user_id = p_user_id) then
    raise exception using
      errcode = '23503', message = 'ACCOUNT_DELETE_TRANSFER_FOUNDER';
  end if;

  if exists (select 1 from public.app_admins where user_id = p_user_id)
    or exists (select 1 from public.admin_audit_log where actor_user_id = p_user_id)
    or exists (
      select 1 from public.organization_audit_log
      where actor_user_id = p_user_id or target_user_id = p_user_id
    )
    or exists (select 1 from public.payment_orders where user_id = p_user_id)
    or exists (select 1 from public.model_provider_policies where updated_by = p_user_id)
    or exists (select 1 from public.community_topics where hidden_by = p_user_id)
    or exists (select 1 from public.organization_join_requests where reviewed_by = p_user_id)
  then
    raise exception using
      errcode = '23503', message = 'ACCOUNT_DELETE_RETENTION_REQUIRED';
  end if;

  delete from auth.users where id = p_user_id;
  get diagnostics deleted_count = row_count;
  if deleted_count <> 1 then
    raise exception using errcode = 'P0002', message = 'ACCOUNT_DELETE_NOT_FOUND';
  end if;

  return jsonb_build_object('deleted_user_id', p_user_id, 'deleted', true);
end;
$$;

revoke all on function public.account_delete_self(uuid) from public;
grant execute on function public.account_delete_self(uuid) to service_role;

notify pgrst, 'reload schema';
