-- Authenticated users may manage only their own account/tenant memory through
-- narrow RPCs. The caller identity always comes from auth.uid(); no public RPC
-- accepts a user id supplied by the browser.

create or replace function public.console_memory_forget_current_user(
  p_tenant_id uuid,
  p_organization_id uuid,
  p_responsibility_namespace text,
  p_scope text default null,
  p_memory_key text default null
)
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  caller_user_id uuid := auth.uid();
  changed integer := 0;
  affected integer := 0;
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
    raise exception using errcode = '22023', message = 'INVALID_MEMORY_FORGET_TARGET';
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

  update public.console_memory_records memory
  set status = 'forgotten', last_seen = now(), updated_at = now()
  where memory.user_id = caller_user_id
    and memory.tenant_id = p_tenant_id
    and memory.organization_id = p_organization_id
    and memory.responsibility_namespace = p_responsibility_namespace
    and (p_scope is null or memory.scope = p_scope)
    and (p_memory_key is null or memory.memory_key = p_memory_key)
    and memory.status = 'active';
  get diagnostics changed = row_count;

  update public.console_memory_candidates candidate
  set status = 'rejected', updated_at = now()
  where candidate.user_id = caller_user_id
    and candidate.tenant_id = p_tenant_id
    and candidate.organization_id = p_organization_id
    and candidate.responsibility_namespace = p_responsibility_namespace
    and (p_scope is null or candidate.scope = p_scope)
    and (p_memory_key is null or candidate.memory_key = p_memory_key)
    and candidate.status in ('staged', 'accepted', 'conflict');
  get diagnostics affected = row_count;

  return changed + affected;
end;
$$;

create or replace function public.console_memory_resolve_current_user(
  p_tenant_id uuid,
  p_organization_id uuid,
  p_candidate_id uuid,
  p_resolution text
)
returns public.console_memory_candidates
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  caller_user_id uuid := auth.uid();
  selected_candidate public.console_memory_candidates%rowtype;
  resolved_candidate public.console_memory_candidates%rowtype;
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
  if p_candidate_id is null or p_resolution not in ('promote', 'reject') then
    raise exception using errcode = '22023', message = 'INVALID_MEMORY_RESOLUTION';
  end if;

  select candidate.* into selected_candidate
  from public.console_memory_candidates candidate
  where candidate.candidate_id = p_candidate_id
    and candidate.user_id = caller_user_id
    and candidate.tenant_id = p_tenant_id
    and candidate.organization_id = p_organization_id;
  if not found then
    raise exception using errcode = '42501', message = 'MEMORY_CANDIDATE_NOT_ACCESSIBLE';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(
    caller_user_id::text || ':' || p_tenant_id::text || ':' ||
    p_organization_id::text || ':' || selected_candidate.responsibility_namespace,
    0
  ));
  perform pg_advisory_xact_lock(hashtextextended(
    caller_user_id::text || ':' || p_tenant_id::text || ':' ||
    selected_candidate.responsibility_namespace || ':' ||
    selected_candidate.scope || ':' || selected_candidate.memory_key,
    0
  ));
  resolved_candidate := public.console_memory_resolve_candidate(
    caller_user_id, p_candidate_id, p_resolution
  );
  return resolved_candidate;
end;
$$;

revoke all on function public.console_memory_forget_current_user(
  uuid, uuid, text, text, text
) from public, anon, authenticated;
revoke all on function public.console_memory_resolve_current_user(
  uuid, uuid, uuid, text
) from public, anon, authenticated;

grant execute on function public.console_memory_forget_current_user(
  uuid, uuid, text, text, text
) to authenticated;
grant execute on function public.console_memory_resolve_current_user(
  uuid, uuid, uuid, text
) to authenticated;
grant select on public.console_memory_candidates to authenticated;

comment on function public.console_memory_forget_current_user(
  uuid, uuid, text, text, text
) is 'Forget one memory, one scope, or one responsibility domain for auth.uid() only.';
comment on function public.console_memory_resolve_current_user(
  uuid, uuid, uuid, text
) is 'Promote or reject one accessible staged memory candidate for auth.uid() only.';
