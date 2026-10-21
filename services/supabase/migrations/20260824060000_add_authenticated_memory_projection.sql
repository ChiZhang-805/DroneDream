-- Desktop account-memory projection uses the caller's real JWT and the public
-- Supabase key.  It must never require or accept a service-role credential.
-- Authenticated desktop callers may only stage a validated-plan candidate;
-- promotion remains a separate, explicit authenticated resolution.

alter table public.console_memory_records
  add column if not exists projection_revision bigint not null default 1
    check (projection_revision between 1 and 9223372036854775807);

create or replace function public.console_memory_increment_projection_revision()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  new.projection_revision := old.projection_revision + 1;
  return new;
end;
$$;

drop trigger if exists zz_console_memory_projection_revision
  on public.console_memory_records;
create trigger zz_console_memory_projection_revision
  before update on public.console_memory_records
  for each row execute function public.console_memory_increment_projection_revision();

create or replace function public.console_memory_stage_current_user(
  p_tenant_id uuid,
  p_organization_id uuid,
  p_responsibility_namespace text,
  p_scope text,
  p_memory_key text,
  p_memory_kind text,
  p_payload jsonb,
  p_source_edition text,
  p_source_workspace_id text,
  p_conversation_id uuid,
  p_run_id uuid,
  p_source_receipt_id text,
  p_source_receipt_sha256 text,
  p_source_metadata jsonb,
  p_retrieval_metadata jsonb,
  p_evidence_sha256 text,
  p_confidence numeric
)
returns public.console_memory_candidates
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  caller_user_id uuid := auth.uid();
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

  -- A public desktop client cannot attest a product-owned receipt and cannot
  -- claim a direct-user promotion.  The accepted row stays staged/conflict
  -- until console_memory_resolve_current_user records an explicit decision.
  return public.console_memory_stage_candidate(
    caller_user_id,
    p_tenant_id,
    p_organization_id,
    p_responsibility_namespace,
    p_scope,
    p_memory_key,
    p_memory_kind,
    p_payload,
    'validated_plan_candidate',
    p_source_edition,
    p_source_workspace_id,
    p_conversation_id,
    p_run_id,
    p_source_receipt_id,
    p_source_receipt_sha256,
    coalesce(p_source_metadata, '{}'::jsonb)
      || jsonb_build_object('projection_actor', 'authenticated_desktop'),
    coalesce(p_retrieval_metadata, '{}'::jsonb),
    p_evidence_sha256,
    p_confidence
  );
end;
$$;

revoke all on function public.console_memory_increment_projection_revision()
  from public, anon, authenticated;
grant execute on function public.console_memory_increment_projection_revision()
  to service_role;

revoke all on function public.console_memory_stage_current_user(
  uuid, uuid, text, text, text, text, jsonb, text, text, uuid, uuid,
  text, text, jsonb, jsonb, text, numeric
) from public, anon, authenticated;
grant execute on function public.console_memory_stage_current_user(
  uuid, uuid, text, text, text, text, jsonb, text, text, uuid, uuid,
  text, text, jsonb, jsonb, text, numeric
) to authenticated;

comment on column public.console_memory_records.projection_revision is
  'Monotonic revision used by authenticated desktop projections to detect stale or conflicting cloud state.';
comment on function public.console_memory_stage_current_user(
  uuid, uuid, text, text, text, text, jsonb, text, text, uuid, uuid,
  text, text, jsonb, jsonb, text, numeric
) is 'Stage one caller-owned desktop candidate as validated_plan_candidate; never promotes without a separate authenticated resolution.';
