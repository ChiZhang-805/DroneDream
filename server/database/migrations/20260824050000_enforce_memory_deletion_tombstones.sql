-- Permanent deletion is a durable opt-out for the exact account/domain target.
-- Re-enabling ordinary memory consent alone must not silently relearn deleted
-- material: an authenticated, explicit relearn action releases the tombstone
-- while retaining the deletion/reconsent audit record.

alter table public.console_memory_deletion_tombstones
  add column if not exists released_at timestamptz,
  add column if not exists released_by uuid,
  add column if not exists release_reason text;

alter table public.console_memory_deletion_tombstones
  drop constraint if exists console_memory_deletion_tombstones_release_check;
alter table public.console_memory_deletion_tombstones
  add constraint console_memory_deletion_tombstones_release_check check (
    (
      released_at is null
      and released_by is null
      and release_reason is null
    ) or (
      released_at is not null
      and released_by is not null
      and release_reason = 'explicit_reconsent'
    )
  );

create index if not exists console_memory_active_tombstone_target_idx
  on public.console_memory_deletion_tombstones (
    user_id,
    tenant_id,
    organization_id,
    responsibility_namespace,
    scope,
    memory_key_sha256
  )
  where released_at is null;

create or replace function public.console_memory_require_write_consent()
returns trigger
language plpgsql
security definer
set search_path = public, extensions, pg_temp
as $$
declare
  memory_key_hash text;
begin
  -- Use the same owner/domain -> exact-key lock order as stage, forget, and
  -- permanent-delete RPCs. A writer can therefore never pass this check using
  -- a consent/tombstone snapshot from before a concurrent deletion.
  perform pg_advisory_xact_lock(hashtextextended(
    new.user_id::text || ':' || new.tenant_id::text || ':' ||
    new.organization_id::text || ':' || new.responsibility_namespace,
    0
  ));
  if new.memory_key is not null then
    perform pg_advisory_xact_lock(hashtextextended(
      new.user_id::text || ':' || new.tenant_id::text || ':' ||
      new.responsibility_namespace || ':' || new.scope || ':' || new.memory_key,
      0
    ));
    memory_key_hash := encode(
      digest(convert_to(new.memory_key, 'UTF8'), 'sha256'),
      'hex'
    );
  end if;

  if not exists (
    select 1
    from public.console_memory_consents consent
    where consent.user_id = new.user_id
      and consent.tenant_id = new.tenant_id
      and consent.organization_id = new.organization_id
      and consent.memory_enabled
      and new.responsibility_namespace = any(consent.write_namespaces)
      and consent.memory_scopes @> jsonb_build_object(new.scope, true)
  ) then
    raise exception using
      errcode = '42501',
      message = 'MEMORY_WRITE_CONSENT_REQUIRED';
  end if;

  if exists (
    select 1
    from public.console_memory_deletion_tombstones tombstone
    where tombstone.user_id = new.user_id
      and tombstone.tenant_id = new.tenant_id
      and tombstone.organization_id = new.organization_id
      and tombstone.released_at is null
      and (
        tombstone.responsibility_namespace = 'account.all'
        or (
          tombstone.responsibility_namespace = new.responsibility_namespace
          and (tombstone.scope is null or tombstone.scope = new.scope)
          and (
            tombstone.memory_key_sha256 is null
            or tombstone.memory_key_sha256 = memory_key_hash
          )
        )
      )
  ) then
    raise exception using
      errcode = '42501',
      message = 'MEMORY_SCOPE_TOMBSTONED';
  end if;
  return new;
end;
$$;

create or replace function public.console_memory_release_deletion_tombstone_current_user(
  p_tenant_id uuid,
  p_organization_id uuid,
  p_responsibility_namespace text,
  p_scope text default null,
  p_memory_key text default null,
  p_confirm_relearn boolean default false
)
returns integer
language plpgsql
security definer
set search_path = public, extensions, pg_temp
as $$
declare
  caller_user_id uuid := auth.uid();
  namespace text;
  memory_key_hash text;
  released_count integer := 0;
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
  if p_confirm_relearn is distinct from true then
    raise exception using errcode = '22023', message = 'EXPLICIT_RELEARN_CONFIRMATION_REQUIRED';
  end if;
  if p_responsibility_namespace is null
    or (
      p_responsibility_namespace <> 'account.all'
      and p_responsibility_namespace not in (
        'account.shared', 'optimization.control_tuning', 'autonomy.mission',
        'asset.qualification', 'experiment.simulation', 'workflow.cross_edition',
        'validation.hardware', 'calibration.system', 'transfer.sim_to_real',
        'transfer.real_to_sim', 'operations.field'
      )
    )
    or (
      p_responsibility_namespace = 'account.all'
      and (p_scope is not null or p_memory_key is not null)
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
    raise exception using errcode = '22023', message = 'INVALID_MEMORY_RELEARN_TARGET';
  end if;

  -- Account-wide deletion locked every domain in canonical order. Releasing
  -- its tombstone follows the same order; scoped release uses just one domain.
  if p_responsibility_namespace = 'account.all' then
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
  else
    perform pg_advisory_xact_lock(hashtextextended(
      caller_user_id::text || ':' || p_tenant_id::text || ':' ||
      p_organization_id::text || ':' || p_responsibility_namespace,
      0
    ));
  end if;
  if p_memory_key is not null then
    perform pg_advisory_xact_lock(hashtextextended(
      caller_user_id::text || ':' || p_tenant_id::text || ':' ||
      p_responsibility_namespace || ':' || p_scope || ':' || p_memory_key,
      0
    ));
    memory_key_hash := encode(
      digest(convert_to(p_memory_key, 'UTF8'), 'sha256'),
      'hex'
    );
  end if;

  -- A tombstone may be released only after the user has separately restored
  -- account consent for the target namespace and scope. This RPC is the second,
  -- explicit confirmation that relearning the permanently deleted target is OK.
  if not exists (
    select 1
    from public.console_memory_consents consent
    where consent.user_id = caller_user_id
      and consent.tenant_id = p_tenant_id
      and consent.organization_id = p_organization_id
      and consent.memory_enabled
      and (
        (
          p_responsibility_namespace = 'account.all'
          and cardinality(consent.write_namespaces) > 0
        )
        or p_responsibility_namespace = any(consent.write_namespaces)
      )
      and case
        when p_scope is null then exists (
          select 1
          from jsonb_each(consent.memory_scopes) enabled_scope
          where enabled_scope.value = 'true'::jsonb
        )
        else consent.memory_scopes @> jsonb_build_object(p_scope, true)
      end
  ) then
    raise exception using errcode = '42501', message = 'MEMORY_RECONSENT_REQUIRED';
  end if;

  update public.console_memory_deletion_tombstones tombstone
  set released_at = now(),
      released_by = caller_user_id,
      release_reason = 'explicit_reconsent'
  where tombstone.user_id = caller_user_id
    and tombstone.tenant_id = p_tenant_id
    and tombstone.organization_id = p_organization_id
    and tombstone.responsibility_namespace = p_responsibility_namespace
    and tombstone.scope is not distinct from p_scope
    and tombstone.memory_key_sha256 is not distinct from memory_key_hash
    and tombstone.released_at is null;
  get diagnostics released_count = row_count;
  return released_count;
end;
$$;

revoke all on function public.console_memory_require_write_consent()
  from public, anon, authenticated;
grant execute on function public.console_memory_require_write_consent()
  to service_role;

revoke all on function public.console_memory_release_deletion_tombstone_current_user(
  uuid, uuid, text, text, text, boolean
) from public, anon, authenticated;
grant execute on function public.console_memory_release_deletion_tombstone_current_user(
  uuid, uuid, text, text, text, boolean
) to authenticated;

comment on function public.console_memory_release_deletion_tombstone_current_user(
  uuid, uuid, text, text, text, boolean
) is 'After separately restored consent, explicitly release an exact deletion tombstone while preserving its audit record; broader active tombstones continue to block writes.';
