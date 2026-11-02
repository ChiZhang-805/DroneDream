-- Account-wide memory consent is separate from per-edition preferences.
-- Permanent deletion is distinct from soft forget and leaves only a minimal,
-- payload-free tombstone. All broad operations use owner/domain advisory locks.

create table if not exists public.console_memory_consents (
  user_id uuid not null references auth.users(id) on delete cascade,
  tenant_id uuid not null,
  organization_id uuid not null default '00000000-0000-0000-0000-000000000000',
  memory_enabled boolean not null default false,
  read_namespaces text[] not null default '{}'::text[],
  write_namespaces text[] not null default '{}'::text[],
  memory_scopes jsonb not null default '{}'::jsonb
    check (jsonb_typeof(memory_scopes) = 'object'),
  updated_at timestamptz not null default now(),
  primary key (user_id, tenant_id, organization_id),
  check (
    (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = user_id)
    or (organization_id <> '00000000-0000-0000-0000-000000000000' and tenant_id = organization_id)
  ),
  check (read_namespaces <@ array[
    'account.shared', 'optimization.control_tuning', 'autonomy.mission',
    'asset.qualification', 'experiment.simulation', 'workflow.cross_edition',
    'validation.hardware', 'calibration.system', 'transfer.sim_to_real',
    'transfer.real_to_sim', 'operations.field'
  ]::text[]),
  check (write_namespaces <@ array[
    'account.shared', 'optimization.control_tuning', 'autonomy.mission',
    'asset.qualification', 'experiment.simulation', 'workflow.cross_edition',
    'validation.hardware', 'calibration.system', 'transfer.sim_to_real',
    'transfer.real_to_sim', 'operations.field'
  ]::text[])
);

alter table public.console_memory_consents enable row level security;
alter table public.console_memory_consents force row level security;

drop policy if exists "Users manage their account memory consent"
  on public.console_memory_consents;
create policy "Users manage their account memory consent"
  on public.console_memory_consents for all to authenticated
  using (
    user_id = auth.uid() and (
      (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = auth.uid())
      or exists (
        select 1 from public.organization_members membership
        where membership.organization_id = console_memory_consents.organization_id
          and membership.organization_id = console_memory_consents.tenant_id
          and membership.user_id = auth.uid() and membership.status = 'active'
      )
    )
  )
  with check (
    user_id = auth.uid() and (
      (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = auth.uid())
      or exists (
        select 1 from public.organization_members membership
        where membership.organization_id = console_memory_consents.organization_id
          and membership.organization_id = console_memory_consents.tenant_id
          and membership.user_id = auth.uid() and membership.status = 'active'
      )
    )
  );

create table if not exists public.console_memory_deletion_tombstones (
  tombstone_id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  tenant_id uuid not null,
  organization_id uuid not null,
  responsibility_namespace text not null,
  scope text,
  memory_key_sha256 text check (
    memory_key_sha256 is null or memory_key_sha256 ~ '^[0-9a-f]{64}$'
  ),
  deleted_records integer not null check (deleted_records >= 0),
  deleted_candidates integer not null check (deleted_candidates >= 0),
  deleted_at timestamptz not null default now(),
  check (
    (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = user_id)
    or (organization_id <> '00000000-0000-0000-0000-000000000000' and tenant_id = organization_id)
  )
);

create or replace function public.console_memory_require_write_consent()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if not exists (
    select 1
    from public.console_memory_consents consent
    where consent.user_id = new.user_id
      and consent.tenant_id = new.tenant_id
      and consent.organization_id = new.organization_id
      and consent.memory_enabled
      and new.responsibility_namespace = any(consent.write_namespaces)
  ) then
    raise exception using
      errcode = '42501',
      message = 'MEMORY_WRITE_CONSENT_REQUIRED';
  end if;
  return new;
end;
$$;

drop trigger if exists console_memory_candidates_require_write_consent
  on public.console_memory_candidates;
create trigger console_memory_candidates_require_write_consent
  before insert on public.console_memory_candidates
  for each row execute function public.console_memory_require_write_consent();

drop trigger if exists console_memory_records_require_write_consent
  on public.console_memory_records;
create trigger console_memory_records_require_write_consent
  before insert on public.console_memory_records
  for each row execute function public.console_memory_require_write_consent();

alter table public.console_memory_deletion_tombstones enable row level security;
alter table public.console_memory_deletion_tombstones force row level security;

drop policy if exists "Users read their memory deletion tombstones"
  on public.console_memory_deletion_tombstones;
create policy "Users read their memory deletion tombstones"
  on public.console_memory_deletion_tombstones for select to authenticated
  using (
    user_id = auth.uid() and (
      (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = auth.uid())
      or exists (
        select 1 from public.organization_members membership
        where membership.organization_id = console_memory_deletion_tombstones.organization_id
          and membership.organization_id = console_memory_deletion_tombstones.tenant_id
          and membership.user_id = auth.uid() and membership.status = 'active'
      )
    )
  );

create or replace function public.console_memory_permanently_delete_current_user(
  p_tenant_id uuid,
  p_organization_id uuid,
  p_responsibility_namespace text,
  p_scope text default null,
  p_memory_key text default null
)
returns integer
language plpgsql
security definer
set search_path = public, extensions, pg_temp
as $$
declare
  caller_user_id uuid := auth.uid();
  deleted_records integer := 0;
  deleted_candidates integer := 0;
begin
  perform set_config('lock_timeout', '2s', true);
  perform set_config('statement_timeout', '10s', true);
  if caller_user_id is null then
    raise exception using errcode = '42501', message = 'AUTHENTICATION_REQUIRED';
  end if;
  if not public.console_memory_boundary_allowed(
    caller_user_id, p_tenant_id, p_organization_id
  ) then
    raise exception using errcode = '42501', message = 'MEMORY_TENANT_MISMATCH';
  end if;
  if p_responsibility_namespace is null or p_responsibility_namespace not in (
      'account.shared', 'optimization.control_tuning', 'autonomy.mission',
      'asset.qualification', 'experiment.simulation', 'workflow.cross_edition',
      'validation.hardware', 'calibration.system', 'transfer.sim_to_real',
      'transfer.real_to_sim', 'operations.field'
    )
    or (p_scope is not null and p_scope not in (
      'chat_preferences', 'experiment_defaults', 'device_vehicle',
      'metrics_constraints', 'safety_approvals', 'workflow_tools',
      'reports_delivery', 'collaboration_organization', 'files_artifacts'
    ))
    or (p_memory_key is not null and (
      p_scope is null or p_memory_key !~ '^[a-z][a-z0-9_.:-]{2,159}$'
    ))
  then
    raise exception using errcode = '22023', message = 'INVALID_MEMORY_DELETE_TARGET';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(
    caller_user_id::text || ':' || p_tenant_id::text || ':' ||
    p_organization_id::text || ':' || p_responsibility_namespace,
    0
  ));
  if p_memory_key is not null then
    perform pg_advisory_xact_lock(hashtextextended(
      caller_user_id::text || ':' || p_tenant_id::text || ':' ||
      p_responsibility_namespace || ':' || p_scope || ':' || p_memory_key,
      0
    ));
  end if;

  delete from public.console_memory_candidates candidate
  where candidate.user_id = caller_user_id
    and candidate.tenant_id = p_tenant_id
    and candidate.organization_id = p_organization_id
    and candidate.responsibility_namespace = p_responsibility_namespace
    and (p_scope is null or candidate.scope = p_scope)
    and (p_memory_key is null or candidate.memory_key = p_memory_key);
  get diagnostics deleted_candidates = row_count;

  delete from public.console_memory_records memory
  where memory.user_id = caller_user_id
    and memory.tenant_id = p_tenant_id
    and memory.organization_id = p_organization_id
    and memory.responsibility_namespace = p_responsibility_namespace
    and (p_scope is null or memory.scope = p_scope)
    and (p_memory_key is null or memory.memory_key = p_memory_key);
  get diagnostics deleted_records = row_count;

  insert into public.console_memory_deletion_tombstones (
    user_id, tenant_id, organization_id, responsibility_namespace, scope,
    memory_key_sha256, deleted_records, deleted_candidates
  ) values (
    caller_user_id, p_tenant_id, p_organization_id, p_responsibility_namespace,
    p_scope,
    case when p_memory_key is null then null else
      encode(digest(convert_to(p_memory_key, 'UTF8'), 'sha256'), 'hex') end,
    deleted_records, deleted_candidates
  );
  return deleted_records + deleted_candidates;
end;
$$;

create or replace function public.console_memory_permanently_delete_all_current_user(
  p_tenant_id uuid,
  p_organization_id uuid
)
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  caller_user_id uuid := auth.uid();
  namespace text;
  deleted_records integer := 0;
  deleted_candidates integer := 0;
begin
  perform set_config('lock_timeout', '2s', true);
  perform set_config('statement_timeout', '15s', true);
  if caller_user_id is null then
    raise exception using errcode = '42501', message = 'AUTHENTICATION_REQUIRED';
  end if;
  if not public.console_memory_boundary_allowed(
    caller_user_id, p_tenant_id, p_organization_id
  ) then
    raise exception using errcode = '42501', message = 'MEMORY_TENANT_MISMATCH';
  end if;
  foreach namespace in array array[
    'account.shared', 'optimization.control_tuning', 'autonomy.mission',
    'asset.qualification', 'experiment.simulation', 'workflow.cross_edition',
    'validation.hardware', 'calibration.system', 'transfer.sim_to_real',
    'transfer.real_to_sim', 'operations.field'
  ]::text[] loop
    perform pg_advisory_xact_lock(hashtextextended(
      caller_user_id::text || ':' || p_tenant_id::text || ':' ||
      p_organization_id::text || ':' || namespace,
      0
    ));
  end loop;

  -- Close the write gate in the same transaction before erasing payloads.
  -- Writers use the same namespace advisory locks and the insert triggers above
  -- re-check this row after acquiring their lock, so a stale application-side
  -- consent snapshot cannot recreate memory after account-wide deletion.
  update public.console_memory_consents consent
  set memory_enabled = false,
      read_namespaces = '{}'::text[],
      write_namespaces = '{}'::text[],
      memory_scopes = '{}'::jsonb,
      updated_at = now()
  where consent.user_id = caller_user_id
    and consent.tenant_id = p_tenant_id
    and consent.organization_id = p_organization_id;

  delete from public.console_memory_candidates candidate
  where candidate.user_id = caller_user_id
    and candidate.tenant_id = p_tenant_id
    and candidate.organization_id = p_organization_id;
  get diagnostics deleted_candidates = row_count;
  delete from public.console_memory_records memory
  where memory.user_id = caller_user_id
    and memory.tenant_id = p_tenant_id
    and memory.organization_id = p_organization_id;
  get diagnostics deleted_records = row_count;

  insert into public.console_memory_deletion_tombstones (
    user_id, tenant_id, organization_id, responsibility_namespace,
    deleted_records, deleted_candidates
  ) values (
    caller_user_id, p_tenant_id, p_organization_id, 'account.all',
    deleted_records, deleted_candidates
  );
  return deleted_records + deleted_candidates;
end;
$$;

revoke all on public.console_memory_consents,
  public.console_memory_deletion_tombstones from public, anon;
revoke all on function public.console_memory_require_write_consent()
  from public, anon, authenticated;
grant select, insert, update, delete on public.console_memory_consents to authenticated;
grant select on public.console_memory_deletion_tombstones to authenticated;
grant all on public.console_memory_consents,
  public.console_memory_deletion_tombstones to service_role;
grant execute on function public.console_memory_require_write_consent()
  to service_role;

revoke all on function public.console_memory_permanently_delete_current_user(
  uuid, uuid, text, text, text
) from public, anon, authenticated;
grant execute on function public.console_memory_permanently_delete_current_user(
  uuid, uuid, text, text, text
) to authenticated;
revoke all on function public.console_memory_permanently_delete_all_current_user(
  uuid, uuid
) from public, anon, authenticated;
grant execute on function public.console_memory_permanently_delete_all_current_user(
  uuid, uuid
) to authenticated;

comment on function public.console_memory_forget_current_user(
  uuid, uuid, text, text, text
) is 'Soft-forget memory for auth.uid(): exclude it from retrieval while retaining governed audit data.';
comment on function public.console_memory_permanently_delete_current_user(
  uuid, uuid, text, text, text
) is 'Permanently erase scoped memory payloads for auth.uid() and retain only a payload-free deletion tombstone.';
comment on function public.console_memory_permanently_delete_all_current_user(
  uuid, uuid
) is 'Atomically erase all account memory payloads for auth.uid() after locking every responsibility namespace.';
