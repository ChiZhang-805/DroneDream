-- Organization tenancy used by both the organization console and the
-- assistant orchestration boundary. Membership is server-authoritative; a
-- browser-supplied organization id is never sufficient to gain access.

create table if not exists public.organizations (
  organization_id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 1 and 120),
  plan text not null check (plan in ('plus', 'pro')),
  status text not null default 'active' check (status in ('active', 'suspended')),
  owner_user_id uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists organizations_owner_active_idx
  on public.organizations (owner_user_id)
  where status = 'active';

create table if not exists public.organization_members (
  organization_id uuid not null references public.organizations(organization_id)
    on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('owner', 'admin', 'member')),
  status text not null default 'active' check (status in ('active', 'removed')),
  joined_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (organization_id, user_id)
);

-- The current product exposes one active organization context per account.
-- This makes omission of organization_id deterministic while still requiring
-- every request to re-check the live membership row.
create unique index if not exists organization_members_one_active_org_idx
  on public.organization_members (user_id)
  where status = 'active';

create or replace function public.organization_owner_membership()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  insert into public.organization_members (
    organization_id, user_id, role, status
  ) values (
    new.organization_id, new.owner_user_id, 'owner', 'active'
  )
  on conflict (organization_id, user_id) do update
  set role = 'owner', status = 'active', updated_at = now();
  return new;
end;
$$;

drop trigger if exists organizations_create_owner_membership
  on public.organizations;
create trigger organizations_create_owner_membership
  after insert on public.organizations
  for each row execute function public.organization_owner_membership();

alter table public.organizations enable row level security;
alter table public.organization_members enable row level security;

drop policy if exists "Members read their organization" on public.organizations;
create policy "Members read their organization"
  on public.organizations for select to authenticated
  using (
    exists (
      select 1 from public.organization_members membership
      where membership.organization_id = organizations.organization_id
        and membership.user_id = auth.uid()
        and membership.status = 'active'
    )
  );

drop policy if exists "Members read organization membership"
  on public.organization_members;
create policy "Members read organization membership"
  on public.organization_members for select to authenticated
  using (user_id = auth.uid());

revoke all on table public.organizations from anon, authenticated;
revoke all on table public.organization_members from anon, authenticated;
grant select on table public.organizations to authenticated;
grant select on table public.organization_members to authenticated;
grant all on table public.organizations to service_role;
grant all on table public.organization_members to service_role;

create or replace function public.organization_resolve_membership(
  p_user_id uuid,
  p_requested_organization_id uuid default null
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  resolved_id uuid;
begin
  if p_user_id is null then
    raise exception using errcode = '22023', message = 'ORGANIZATION_USER_INVALID';
  end if;
  -- Organization selection is always explicit. A null request means the
  -- caller's personal tenant even when that user belongs to one or more
  -- organizations; silently choosing an arbitrary membership would cross the
  -- personal/organization workspace boundary.
  if p_requested_organization_id is null then
    return null;
  end if;
  select membership.organization_id into resolved_id
  from public.organization_members membership
  join public.organizations organization
    on organization.organization_id = membership.organization_id
  where membership.user_id = p_user_id
    and membership.status = 'active'
    and organization.status = 'active'
    and membership.organization_id = p_requested_organization_id;
  if resolved_id is null then
    raise exception using errcode = '42501', message = 'ORGANIZATION_ACCESS_FORBIDDEN';
  end if;
  return resolved_id;
end;
$$;

revoke all on function public.organization_resolve_membership(uuid, uuid)
  from public;
grant execute on function public.organization_resolve_membership(uuid, uuid)
  to service_role;
