-- User-requested account migration. Business entitlements are organization
-- scoped, so a direct upgrade creates the account's initial organization when
-- it does not already have one.
do $$
declare
  target_user_id uuid;
  target_name text;
  membership public.organization_members%rowtype;
begin
  select id,
    coalesce(
      nullif(btrim(raw_user_meta_data ->> 'display_name'), ''),
      nullif(btrim(raw_user_meta_data ->> 'full_name'), ''),
      'Chi Zhang'
    )
  into target_user_id, target_name
  from auth.users
  where lower(email) = 'cz91@illinois.edu';

  if target_user_id is null then
    raise exception using errcode = 'P0002', message = 'REQUESTED_BUSINESS_ACCOUNT_NOT_FOUND';
  end if;

  select * into membership
  from public.organization_members
  where user_id = target_user_id and status = 'active';

  if membership.user_id is null then
    perform public.organization_create_v2(
      target_user_id,
      left(target_name || ' Organization', 120),
      'DroneDream Business workspace.',
      'flat',
      'pro'
    );
  elsif membership.role = 'owner' then
    perform public.organization_set_founder_plan(target_user_id, 'pro');
  else
    if not exists (
      select 1 from public.organizations
      where organization_id = membership.organization_id and plan = 'pro'
    ) then
      raise exception using errcode = '23514', message = 'REQUESTED_BUSINESS_PLAN_EXCEEDS_ORGANIZATION';
    end if;
    update public.account_entitlements
    set plan_id = 'pro', status = 'active', billing_scope = 'business',
        organization_id = membership.organization_id, source = 'admin',
        payment_provider = null, provider_subscription_reference = null,
        updated_at = now()
    where user_id = target_user_id;
  end if;
end;
$$;
