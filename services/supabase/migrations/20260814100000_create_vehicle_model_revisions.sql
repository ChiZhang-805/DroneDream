-- Immutable Universal Vehicle Studio revision chain. Every row repeats the
-- complete account, tenant, organization, workspace and edition boundary.
-- The browser cannot weaken this boundary because RLS evaluates it again on
-- every select, insert, update and delete.

create table if not exists public.vehicle_model_revisions (
  user_id uuid not null references auth.users(id) on delete cascade,
  tenant_id uuid not null,
  organization_id uuid not null default '00000000-0000-0000-0000-000000000000',
  workspace_id text not null check (workspace_id = 'console-universal'),
  edition text not null check (edition = 'universal'),
  draft_id uuid not null,
  revision integer not null check (revision between 1 and 1000000),
  model jsonb not null check (
    jsonb_typeof(model) = 'object'
    and model ->> 'draftId' = draft_id::text
    and (model ->> 'revision')::integer = revision
    and model ->> 'schemaVersion' = '2'
    and jsonb_typeof(model -> 'components') = 'array'
    and jsonb_array_length(model -> 'components') between 1 and 256
    and jsonb_typeof(model -> 'constraints') = 'array'
  ),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (
    user_id, tenant_id, organization_id, workspace_id, edition, draft_id, revision
  ),
  check (
    (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = user_id)
    or (organization_id <> '00000000-0000-0000-0000-000000000000' and tenant_id = organization_id)
  )
);

create index if not exists vehicle_model_revisions_head_idx
  on public.vehicle_model_revisions (
    user_id, tenant_id, organization_id, workspace_id, edition, draft_id,
    revision desc, updated_at desc
  );

alter table public.vehicle_model_revisions enable row level security;

drop policy if exists "Users manage their bounded vehicle model revisions"
  on public.vehicle_model_revisions;
create policy "Users manage their bounded vehicle model revisions"
  on public.vehicle_model_revisions for all to authenticated
  using (
    user_id = auth.uid() and (
      (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = auth.uid())
      or exists (
        select 1 from public.organization_members membership
        where membership.organization_id = vehicle_model_revisions.organization_id
          and membership.organization_id = vehicle_model_revisions.tenant_id
          and membership.user_id = auth.uid()
          and membership.status = 'active'
      )
    )
  )
  with check (
    user_id = auth.uid() and (
      (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = auth.uid())
      or exists (
        select 1 from public.organization_members membership
        where membership.organization_id = vehicle_model_revisions.organization_id
          and membership.organization_id = vehicle_model_revisions.tenant_id
          and membership.user_id = auth.uid()
          and membership.status = 'active'
      )
    )
  );

revoke all on public.vehicle_model_revisions from anon;
grant select, insert, update, delete on public.vehicle_model_revisions to authenticated;
grant all on public.vehicle_model_revisions to service_role;
