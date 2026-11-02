-- Authenticated console preferences and structured memory. Every row carries
-- the complete account, tenant, organization, workspace, and edition boundary;
-- RLS repeats that boundary server-side so a hidden UI control is never the
-- authorization mechanism.

create table if not exists public.console_preferences (
  user_id uuid not null references auth.users(id) on delete cascade,
  tenant_id uuid not null,
  organization_id uuid not null default '00000000-0000-0000-0000-000000000000',
  workspace_id text not null check (workspace_id ~ '^console-(universal|sim|lab|field)$'),
  edition text not null check (edition in ('universal', 'sim', 'lab', 'field')),
  interface_locale text not null default 'en'
    check (interface_locale in ('en', 'zh-CN', 'zh-TW', 'es', 'ja', 'ko')),
  appearance_mode text not null default 'system'
    check (appearance_mode in ('dark', 'light', 'system', 'custom')),
  custom_accent text not null default '#8d72ee'
    check (custom_accent ~ '^#[0-9A-Fa-f]{6}$'),
  notifications jsonb not null default '{}'::jsonb
    check (jsonb_typeof(notifications) = 'object'),
  memory_enabled boolean not null default false,
  memory_scopes jsonb not null default '{}'::jsonb
    check (jsonb_typeof(memory_scopes) = 'object'),
  defaults jsonb not null default '{}'::jsonb
    check (jsonb_typeof(defaults) = 'object'),
  updated_at timestamptz not null default now(),
  primary key (user_id, tenant_id, organization_id, workspace_id, edition),
  check (
    (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = user_id)
    or (organization_id <> '00000000-0000-0000-0000-000000000000' and tenant_id = organization_id)
  ),
  check (workspace_id = 'console-' || edition)
);

create table if not exists public.console_memory_records (
  memory_id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  tenant_id uuid not null,
  organization_id uuid not null default '00000000-0000-0000-0000-000000000000',
  workspace_id text not null check (
    char_length(workspace_id) between 1 and 160
    and workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
  ),
  edition text not null check (edition in ('universal', 'sim', 'lab', 'field')),
  conversation_id uuid,
  scope text not null check (scope in (
    'chat_preferences', 'experiment_defaults', 'device_vehicle',
    'metrics_constraints', 'safety_approvals', 'workflow_tools',
    'reports_delivery'
  )),
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  source_version integer not null default 1 check (source_version between 1 and 10000),
  expires_at timestamptz not null default (now() + interval '180 days'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (
    (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = user_id)
    or (organization_id <> '00000000-0000-0000-0000-000000000000' and tenant_id = organization_id)
  )
);

create index if not exists console_memory_records_boundary_idx
  on public.console_memory_records (
    user_id, tenant_id, organization_id, workspace_id, edition, scope, updated_at desc
  );

alter table public.console_preferences enable row level security;
alter table public.console_memory_records enable row level security;

drop policy if exists "Users manage their bounded console preferences" on public.console_preferences;
create policy "Users manage their bounded console preferences"
  on public.console_preferences for all to authenticated
  using (
    user_id = auth.uid() and (
      (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = auth.uid())
      or exists (
        select 1 from public.organization_members membership
        where membership.organization_id = console_preferences.organization_id
          and membership.organization_id = console_preferences.tenant_id
          and membership.user_id = auth.uid() and membership.status = 'active'
      )
    )
  )
  with check (
    user_id = auth.uid() and (
      (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = auth.uid())
      or exists (
        select 1 from public.organization_members membership
        where membership.organization_id = console_preferences.organization_id
          and membership.organization_id = console_preferences.tenant_id
          and membership.user_id = auth.uid() and membership.status = 'active'
      )
    )
  );

drop policy if exists "Users manage their bounded console memory" on public.console_memory_records;
create policy "Users manage their bounded console memory"
  on public.console_memory_records for all to authenticated
  using (
    user_id = auth.uid() and (
      (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = auth.uid())
      or exists (
        select 1 from public.organization_members membership
        where membership.organization_id = console_memory_records.organization_id
          and membership.organization_id = console_memory_records.tenant_id
          and membership.user_id = auth.uid() and membership.status = 'active'
      )
    )
  )
  with check (
    user_id = auth.uid() and (
      (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = auth.uid())
      or exists (
        select 1 from public.organization_members membership
        where membership.organization_id = console_memory_records.organization_id
          and membership.organization_id = console_memory_records.tenant_id
          and membership.user_id = auth.uid() and membership.status = 'active'
      )
    )
  );

revoke all on public.console_preferences, public.console_memory_records from anon;
grant select, insert, update, delete on public.console_preferences to authenticated;
grant select, insert, update, delete on public.console_memory_records to authenticated;
grant all on public.console_preferences, public.console_memory_records to service_role;
