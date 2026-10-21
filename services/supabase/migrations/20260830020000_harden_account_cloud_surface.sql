-- Keep account/billing context authoritative and remove implicit Data API
-- execution rights from server-only RPCs.  PostgreSQL grants EXECUTE on new
-- functions to PUBLIC by default, while hosted projects may also have default
-- privileges for anon/authenticated.  RLS does not protect SECURITY DEFINER
-- functions, so every client-callable function is allow-listed below.

create or replace function public.model_access_account_snapshot(
  p_user_id uuid
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  selected_entitlement public.account_entitlements%rowtype;
  selected_organization_name text;
  selected_organization_role text;
begin
  if p_user_id is null then
    raise exception using errcode = '22023', message = 'MODEL_ACCOUNT_USER_REQUIRED';
  end if;

  select *
  into selected_entitlement
  from public.account_entitlements
  where user_id = p_user_id
    and status = 'active'
    and current_period_start <= now()
    and current_period_end > now();

  if not found then
    return jsonb_build_object(
      'billing_scope', 'individual',
      'organization_id', null,
      'organization_name', null,
      'organization_role', null
    );
  end if;

  if selected_entitlement.billing_scope = 'business' then
    select organization.name
    into selected_organization_name
    from public.organizations organization
    where organization.organization_id = selected_entitlement.organization_id;

    select member.role
    into selected_organization_role
    from public.organization_members member
    where member.organization_id = selected_entitlement.organization_id
      and member.user_id = p_user_id
      and member.status = 'active';
  end if;

  return jsonb_build_object(
    'billing_scope', selected_entitlement.billing_scope,
    'organization_id', selected_entitlement.organization_id,
    'organization_name', selected_organization_name,
    'organization_role', selected_organization_role
  );
end;
$$;

comment on function public.model_access_account_snapshot(uuid) is
  'Return the active billing boundary for one server-authenticated account; service-role only.';

-- Remove hosted/default broad table grants from billing data.  Client reads
-- remain narrowly governed by the existing RLS policies; grants and webhook
-- receipts stay server-only.
revoke all on table public.model_subscription_plans,
  public.account_entitlements,
  public.model_usage_periods,
  public.model_gateway_grants,
  public.model_usage_requests,
  public.payment_orders,
  public.payment_webhook_events
from anon, authenticated;

grant select on table public.model_subscription_plans to anon, authenticated;
grant select on table public.account_entitlements,
  public.model_usage_periods,
  public.model_usage_requests,
  public.payment_orders
to authenticated;

grant all on table public.model_subscription_plans,
  public.account_entitlements,
  public.model_usage_periods,
  public.model_gateway_grants,
  public.model_usage_requests,
  public.payment_orders,
  public.payment_webhook_events
to service_role;

-- Start from a closed RPC surface, then restore the small set intentionally
-- called by browser/desktop clients.  Edge Functions use service_role.
revoke execute on all functions in schema public from public, anon, authenticated;
grant execute on all functions in schema public to service_role;

grant execute on function public.community_list_topics(text, text, integer, integer)
  to anon, authenticated;
grant execute on function public.community_list_topics_v2(text, text, integer, integer)
  to anon, authenticated;
grant execute on function public.community_list_comments(uuid, integer, integer)
  to anon, authenticated;
grant execute on function public.community_count_topics(text, text)
  to anon, authenticated;
grant execute on function public.community_media_upload_allowed(text, jsonb)
  to authenticated;

grant execute on function public.console_memory_forget_current_user(
  uuid, uuid, text, text, text
) to authenticated;
grant execute on function public.console_memory_resolve_current_user(
  uuid, uuid, uuid, text
) to authenticated;
grant execute on function public.console_memory_permanently_delete_current_user(
  uuid, uuid, text, text, text
) to authenticated;
grant execute on function public.console_memory_permanently_delete_all_current_user(
  uuid, uuid
) to authenticated;
grant execute on function public.console_memory_release_deletion_tombstone_current_user(
  uuid, uuid, text, text, text, boolean
) to authenticated;
grant execute on function public.console_memory_stage_current_user(
  uuid, uuid, text, text, text, text, jsonb, text, text, uuid, uuid,
  text, text, jsonb, jsonb, text, numeric
) to authenticated;

-- Prevent the same implicit exposure when later migrations create functions.
alter default privileges in schema public
  revoke execute on functions from public, anon, authenticated;
alter default privileges in schema public
  grant execute on functions to service_role;

notify pgrst, 'reload schema';
