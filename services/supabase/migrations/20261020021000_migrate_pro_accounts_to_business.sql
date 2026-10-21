-- Move existing active Pro accounts into the organization-backed business
-- model. The migration derives its targets from entitlement state so the same
-- schema migration behaves consistently in every environment.
do $$
declare
  target record;
  membership public.organization_members%rowtype;
begin
  for target in
    select users.id as user_id,
      coalesce(
        nullif(btrim(users.raw_user_meta_data ->> 'display_name'), ''),
        nullif(btrim(users.raw_user_meta_data ->> 'full_name'), ''),
        'DroneDream'
      ) as display_name
    from auth.users users
    join public.account_entitlements entitlement
      on entitlement.user_id = users.id
    where entitlement.plan_id = 'pro'
      and entitlement.status = 'active'
  loop
    membership := null;
    select * into membership
    from public.organization_members
    where user_id = target.user_id and status = 'active';

    if membership.user_id is null then
      perform public.organization_create_v2(
        target.user_id,
        left(target.display_name || ' Organization', 120),
        'DroneDream Business workspace.',
        'flat',
        'pro'
      );
    elsif membership.role = 'owner' then
      perform public.organization_set_founder_plan(target.user_id, 'pro');
    elsif exists (
      select 1 from public.organizations
      where organization_id = membership.organization_id and plan = 'pro'
    ) then
      update public.account_entitlements
      set plan_id = 'pro', status = 'active', billing_scope = 'business',
          organization_id = membership.organization_id, source = 'admin',
          payment_provider = null, provider_subscription_reference = null,
          updated_at = now()
      where user_id = target.user_id;
    end if;
  end loop;
end;
$$;
