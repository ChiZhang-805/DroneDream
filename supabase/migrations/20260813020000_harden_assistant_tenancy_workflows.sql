-- Defense-in-depth tenancy, auditable workflow steps, durable files, artifact
-- revisions, and recoverable provider back-pressure for assistant runs.

create extension if not exists pgcrypto with schema extensions;

alter table public.assistant_conversations
  add column if not exists tenant_id uuid,
  add column if not exists organization_id uuid references public.organizations(organization_id)
    on delete restrict;
update public.assistant_conversations
set tenant_id = coalesce(organization_id, owner_user_id)
where tenant_id is null;
alter table public.assistant_conversations alter column tenant_id set not null;
alter table public.assistant_conversations
  add constraint assistant_conversations_tenant_shape_check check (
    (organization_id is null and tenant_id = owner_user_id)
    or (organization_id is not null and tenant_id = organization_id)
  );
alter table public.assistant_conversations
  drop constraint if exists assistant_conversations_owner_user_id_edition_workspace_id_key;
alter table public.assistant_conversations
  add constraint assistant_conversations_tenant_workspace_key
  unique (tenant_id, owner_user_id, edition, workspace_id);
alter table public.assistant_conversations
  add constraint assistant_conversations_full_boundary_key
  unique (conversation_id, tenant_id, owner_user_id, edition, workspace_id);

alter table public.assistant_runs
  add column if not exists tenant_id uuid,
  add column if not exists organization_id uuid references public.organizations(organization_id)
    on delete restrict,
  add column if not exists attempt_count integer not null default 0,
  add column if not exists max_attempts integer not null default 3,
  add column if not exists next_attempt_at timestamptz,
  add column if not exists timeout_at timestamptz;
update public.assistant_runs run
set tenant_id = conversation.tenant_id,
    organization_id = conversation.organization_id
from public.assistant_conversations conversation
where run.conversation_id = conversation.conversation_id
  and run.tenant_id is null;
alter table public.assistant_runs alter column tenant_id set not null;
alter table public.assistant_runs
  drop constraint if exists assistant_runs_state_check,
  drop constraint if exists assistant_runs_stage_check;
alter table public.assistant_runs
  add constraint assistant_runs_state_check check (
    state in ('queued', 'processing', 'retry_wait', 'completed', 'failed')
  ),
  add constraint assistant_runs_stage_check check (
    stage in (
      'queued', 'analyzing', 'planning', 'calling_tools', 'validating',
      'retry_wait', 'completed', 'failed_recoverable', 'failed'
    )
  ),
  add constraint assistant_runs_attempt_check check (
    attempt_count between 0 and max_attempts and max_attempts between 1 and 8
  ),
  add constraint assistant_runs_tenant_shape_check check (
    (organization_id is null and tenant_id = owner_user_id)
    or (organization_id is not null and tenant_id = organization_id)
  ),
  add constraint assistant_runs_full_boundary_key
    unique (run_id, conversation_id, tenant_id, owner_user_id, edition, workspace_id),
  add constraint assistant_runs_conversation_tenant_fk
    foreign key (conversation_id, tenant_id, owner_user_id, edition, workspace_id)
    references public.assistant_conversations(
      conversation_id, tenant_id, owner_user_id, edition, workspace_id
    ) on delete cascade;

alter table public.assistant_messages
  add column if not exists tenant_id uuid,
  add column if not exists organization_id uuid references public.organizations(organization_id)
    on delete restrict,
  add column if not exists workspace_id text;
update public.assistant_messages message
set tenant_id = run.tenant_id,
    organization_id = run.organization_id,
    workspace_id = run.workspace_id
from public.assistant_runs run
where message.run_id = run.run_id and message.tenant_id is null;
alter table public.assistant_messages
  alter column tenant_id set not null,
  alter column workspace_id set not null;
alter table public.assistant_messages
  add constraint assistant_messages_tenant_shape_check check (
    (organization_id is null and tenant_id = owner_user_id)
    or (organization_id is not null and tenant_id = organization_id)
  ),
  add constraint assistant_messages_run_tenant_fk
    foreign key (
      run_id, conversation_id, tenant_id, owner_user_id, edition, workspace_id
    ) references public.assistant_runs(
      run_id, conversation_id, tenant_id, owner_user_id, edition, workspace_id
    ) on delete cascade;

alter table public.assistant_artifacts
  add column if not exists tenant_id uuid,
  add column if not exists organization_id uuid references public.organizations(organization_id)
    on delete restrict,
  add column if not exists artifact_series_id uuid default gen_random_uuid(),
  add column if not exists parent_artifact_id uuid references public.assistant_artifacts(artifact_id)
    on delete restrict;
update public.assistant_artifacts artifact
set tenant_id = run.tenant_id,
    organization_id = run.organization_id,
    artifact_series_id = coalesce(artifact.artifact_series_id, artifact.artifact_id)
from public.assistant_runs run
where artifact.run_id = run.run_id and artifact.tenant_id is null;
alter table public.assistant_artifacts
  alter column tenant_id set not null,
  alter column artifact_series_id set not null;
alter table public.assistant_artifacts
  drop constraint if exists assistant_artifacts_artifact_kind_check;
alter table public.assistant_artifacts
  add constraint assistant_artifacts_artifact_kind_check check (
    artifact_kind in (
      'universal_vehicle_model', 'universal_simulation_experiment',
      'universal_cross_edition_workflow', 'simulation_experiment',
      'lab_simulation_experiment', 'lab_hardware_validation',
      'lab_calibration_workflow', 'lab_sim_to_real_workflow',
      'lab_real_to_sim_workflow', 'field_task_plan'
    )
  ),
  add constraint assistant_artifacts_tenant_shape_check check (
    (organization_id is null and tenant_id = owner_user_id)
    or (organization_id is not null and tenant_id = organization_id)
  ),
  add constraint assistant_artifacts_series_version_key
    unique (artifact_series_id, version),
  add constraint assistant_artifacts_run_tenant_fk
    foreign key (
      run_id, conversation_id, tenant_id, owner_user_id, edition, workspace_id
    ) references public.assistant_runs(
      run_id, conversation_id, tenant_id, owner_user_id, edition, workspace_id
    ) on delete cascade;

create table if not exists public.assistant_run_steps (
  step_id uuid primary key default gen_random_uuid(),
  run_id uuid not null,
  conversation_id uuid not null,
  tenant_id uuid not null,
  organization_id uuid references public.organizations(organization_id) on delete restrict,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  edition text not null check (edition in ('universal', 'sim', 'lab', 'field')),
  workspace_id text not null check (char_length(workspace_id) between 8 and 128),
  step_key text not null check (step_key ~ '^[a-z][a-z0-9_-]{1,63}$'),
  step_order integer not null check (step_order between 1 and 64),
  step_type text not null check (
    step_type in ('intent', 'plan', 'model', 'tool', 'validation', 'repair', 'persist')
  ),
  state text not null check (
    state in ('queued', 'running', 'completed', 'needs_input', 'retry_wait', 'failed')
  ),
  attempt integer not null default 1 check (attempt between 1 and 8),
  label text not null check (char_length(label) between 1 and 255),
  tool_name text check (tool_name is null or char_length(tool_name) between 1 and 128),
  input_json jsonb not null default '{}'::jsonb check (jsonb_typeof(input_json) = 'object'),
  output_json jsonb check (output_json is null or jsonb_typeof(output_json) = 'object'),
  error_code text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (run_id, step_key, attempt),
  check (
    (organization_id is null and tenant_id = owner_user_id)
    or (organization_id is not null and tenant_id = organization_id)
  ),
  foreign key (
    run_id, conversation_id, tenant_id, owner_user_id, edition, workspace_id
  ) references public.assistant_runs(
    run_id, conversation_id, tenant_id, owner_user_id, edition, workspace_id
  ) on delete cascade
);

create index if not exists assistant_run_steps_run_order_idx
  on public.assistant_run_steps (run_id, step_order, attempt);

create table if not exists public.assistant_files (
  file_id uuid primary key default gen_random_uuid(),
  run_id uuid not null,
  conversation_id uuid not null,
  tenant_id uuid not null,
  organization_id uuid references public.organizations(organization_id) on delete restrict,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  edition text not null check (edition in ('universal', 'sim', 'lab', 'field')),
  workspace_id text not null check (char_length(workspace_id) between 8 and 128),
  direction text not null check (direction in ('input', 'generated')),
  display_name text not null check (char_length(display_name) between 1 and 255),
  content_type text not null check (char_length(content_type) between 1 and 128),
  byte_size integer not null check (byte_size between 0 and 262144),
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  content_text text not null check (octet_length(content_text) <= 262144),
  version integer not null default 1 check (version between 1 and 10000),
  status text not null default 'active' check (status in ('active', 'archived')),
  created_at timestamptz not null default now(),
  unique (run_id, direction, display_name, content_sha256),
  check (octet_length(content_text) = byte_size),
  check (
    (organization_id is null and tenant_id = owner_user_id)
    or (organization_id is not null and tenant_id = organization_id)
  ),
  foreign key (
    run_id, conversation_id, tenant_id, owner_user_id, edition, workspace_id
  ) references public.assistant_runs(
    run_id, conversation_id, tenant_id, owner_user_id, edition, workspace_id
  ) on delete cascade
);

create index if not exists assistant_files_boundary_idx
  on public.assistant_files (
    tenant_id, owner_user_id, edition, workspace_id, conversation_id, created_at
  );

create table if not exists public.assistant_artifact_versions (
  artifact_id uuid not null references public.assistant_artifacts(artifact_id)
    on delete cascade,
  artifact_series_id uuid not null,
  version integer not null check (version between 1 and 10000),
  run_id uuid not null,
  conversation_id uuid not null,
  tenant_id uuid not null,
  organization_id uuid references public.organizations(organization_id) on delete restrict,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  edition text not null check (edition in ('universal', 'sim', 'lab', 'field')),
  workspace_id text not null,
  artifact_kind text not null,
  title text not null,
  payload_json jsonb not null check (jsonb_typeof(payload_json) = 'object'),
  created_at timestamptz not null default now(),
  primary key (artifact_series_id, version),
  check (
    (organization_id is null and tenant_id = owner_user_id)
    or (organization_id is not null and tenant_id = organization_id)
  ),
  foreign key (
    run_id, conversation_id, tenant_id, owner_user_id, edition, workspace_id
  ) references public.assistant_runs(
    run_id, conversation_id, tenant_id, owner_user_id, edition, workspace_id
  ) on delete restrict
);

create or replace function public.assistant_snapshot_artifact_version()
returns trigger
language plpgsql
security definer
set search_path = public, extensions, pg_temp
as $$
begin
  insert into public.assistant_artifact_versions (
    artifact_id, artifact_series_id, version, run_id, conversation_id, tenant_id,
    organization_id, owner_user_id, edition, workspace_id, artifact_kind,
    title, payload_json
  ) values (
    new.artifact_id, new.artifact_series_id, new.version, new.run_id,
    new.conversation_id,
    new.tenant_id, new.organization_id, new.owner_user_id, new.edition,
    new.workspace_id, new.artifact_kind, new.title, new.payload_json
  );
  return new;
end;
$$;

drop trigger if exists assistant_artifact_version_snapshot
  on public.assistant_artifacts;
create trigger assistant_artifact_version_snapshot
  after insert on public.assistant_artifacts
  for each row execute function public.assistant_snapshot_artifact_version();

alter table public.assistant_run_steps enable row level security;
alter table public.assistant_files enable row level security;
alter table public.assistant_artifact_versions enable row level security;

create policy "Users read their own assistant steps"
  on public.assistant_run_steps for select to authenticated
  using (owner_user_id = auth.uid());
create policy "Users read their own assistant files"
  on public.assistant_files for select to authenticated
  using (owner_user_id = auth.uid());
create policy "Users read their own assistant artifact versions"
  on public.assistant_artifact_versions for select to authenticated
  using (owner_user_id = auth.uid());

revoke all on table public.assistant_run_steps from anon, authenticated;
revoke all on table public.assistant_files from anon, authenticated;
revoke all on table public.assistant_artifact_versions from anon, authenticated;
grant select on table public.assistant_run_steps to authenticated;
grant select on table public.assistant_files to authenticated;
grant select on table public.assistant_artifact_versions to authenticated;
grant all on table public.assistant_run_steps to service_role;
grant all on table public.assistant_files to service_role;
grant all on table public.assistant_artifact_versions to service_role;

create or replace function public.assistant_record_step(
  p_user_id uuid,
  p_run_id uuid,
  p_lease_token uuid,
  p_step_key text,
  p_step_order integer,
  p_step_type text,
  p_state text,
  p_label text,
  p_tool_name text,
  p_input_json jsonb,
  p_output_json jsonb,
  p_error_code text
)
returns public.assistant_run_steps
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  selected_run public.assistant_runs%rowtype;
  selected_step public.assistant_run_steps%rowtype;
begin
  select * into selected_run from public.assistant_runs
  where run_id = p_run_id and owner_user_id = p_user_id
    and state = 'processing' and lease_token = p_lease_token
    and lease_expires_at >= now();
  if not found then
    raise exception using errcode = '55000', message = 'ASSISTANT_RUN_NOT_PROCESSING';
  end if;
  insert into public.assistant_run_steps (
    run_id, conversation_id, tenant_id, organization_id, owner_user_id,
    edition, workspace_id, step_key, step_order, step_type, state, attempt, label,
    tool_name, input_json, output_json, error_code, started_at, completed_at
  ) values (
    selected_run.run_id, selected_run.conversation_id, selected_run.tenant_id,
    selected_run.organization_id, selected_run.owner_user_id,
    selected_run.edition, selected_run.workspace_id, p_step_key,
    p_step_order, p_step_type, p_state, greatest(selected_run.attempt_count, 1),
    p_label, nullif(p_tool_name, ''),
    coalesce(p_input_json, '{}'::jsonb), p_output_json, p_error_code,
    case when p_state in ('running', 'completed', 'needs_input', 'failed') then now() end,
    case when p_state in ('completed', 'needs_input', 'failed') then now() end
  )
  on conflict (run_id, step_key, attempt) do update
  set state = excluded.state,
      label = excluded.label,
      tool_name = excluded.tool_name,
      input_json = excluded.input_json,
      output_json = excluded.output_json,
      error_code = excluded.error_code,
      started_at = coalesce(public.assistant_run_steps.started_at, excluded.started_at),
      completed_at = excluded.completed_at,
      updated_at = now()
  returning * into selected_step;
  update public.assistant_runs
  set lease_expires_at = now() + interval '3 minutes', updated_at = now()
  where run_id = selected_run.run_id;
  return selected_step;
end;
$$;

create or replace function public.assistant_register_file(
  p_user_id uuid,
  p_run_id uuid,
  p_direction text,
  p_display_name text,
  p_content_type text,
  p_content_sha256 text,
  p_content_text text
)
returns public.assistant_files
language plpgsql
security definer
set search_path = public, extensions, pg_temp
as $$
declare
  selected_run public.assistant_runs%rowtype;
  selected_file public.assistant_files%rowtype;
begin
  select * into selected_run from public.assistant_runs
  where run_id = p_run_id and owner_user_id = p_user_id;
  if not found then
    raise exception using errcode = '42501', message = 'ASSISTANT_RUN_FORBIDDEN';
  end if;
  if p_direction not in ('input', 'generated')
    or p_display_name is null or char_length(p_display_name) not between 1 and 255
    or p_content_type is null or char_length(p_content_type) not between 1 and 128
    or p_content_sha256 is null or p_content_sha256 !~ '^[0-9a-f]{64}$'
    or p_content_text is null or octet_length(p_content_text) > 262144
    or encode(extensions.digest(convert_to(p_content_text, 'UTF8'), 'sha256'), 'hex') <> p_content_sha256
  then
    raise exception using errcode = '22023', message = 'ASSISTANT_FILE_INVALID';
  end if;
  insert into public.assistant_files (
    run_id, conversation_id, tenant_id, organization_id, owner_user_id,
    edition, workspace_id, direction, display_name, content_type, byte_size,
    content_sha256, content_text
  ) values (
    selected_run.run_id, selected_run.conversation_id, selected_run.tenant_id,
    selected_run.organization_id, selected_run.owner_user_id,
    selected_run.edition, selected_run.workspace_id, p_direction,
    p_display_name, p_content_type, octet_length(p_content_text),
    p_content_sha256, p_content_text
  )
  on conflict (run_id, direction, display_name, content_sha256) do update
  set status = 'active'
  returning * into selected_file;
  return selected_file;
end;
$$;

create or replace function public.assistant_defer_run(
  p_user_id uuid,
  p_run_id uuid,
  p_lease_token uuid,
  p_error_code text,
  p_retry_after_seconds integer
)
returns public.assistant_runs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  updated_run public.assistant_runs%rowtype;
begin
  if p_retry_after_seconds not between 1 and 300 then
    raise exception using errcode = '22023', message = 'ASSISTANT_RETRY_INVALID';
  end if;
  update public.assistant_runs
  -- assistant_claim_next_run already increments attempt_count immediately
  -- before a provider call. Deferral must never increment it a second time.
  set state = case when attempt_count < max_attempts then 'retry_wait' else 'failed' end,
      stage = case when attempt_count < max_attempts then 'retry_wait' else 'failed_recoverable' end,
      next_attempt_at = case when attempt_count < max_attempts
        then now() + make_interval(secs => p_retry_after_seconds) end,
      error_code = left(coalesce(p_error_code, 'MODEL_PROVIDER_BUSY'), 128),
      error_message = 'The selected managed model is busy. This task is safely queued for retry.',
      lease_token = null, lease_expires_at = null,
      completed_at = case when attempt_count >= max_attempts then now() end,
      updated_at = now()
  where run_id = p_run_id and owner_user_id = p_user_id
    and state = 'processing' and lease_token = p_lease_token
  returning * into updated_run;
  if not found then
    raise exception using errcode = '55000', message = 'ASSISTANT_RUN_NOT_PROCESSING';
  end if;
  return updated_run;
end;
$$;

revoke all on function public.assistant_record_step(
  uuid, uuid, uuid, text, integer, text, text, text, text, jsonb, jsonb, text
) from public;
revoke all on function public.assistant_register_file(
  uuid, uuid, text, text, text, text, text
) from public;
revoke all on function public.assistant_defer_run(
  uuid, uuid, uuid, text, integer
) from public;
grant execute on function public.assistant_record_step(
  uuid, uuid, uuid, text, integer, text, text, text, text, jsonb, jsonb, text
) to service_role;
grant execute on function public.assistant_register_file(
  uuid, uuid, text, text, text, text, text
) to service_role;
grant execute on function public.assistant_defer_run(
  uuid, uuid, uuid, text, integer
) to service_role;

-- Replace the first-generation orchestration RPCs after the tenant columns
-- become mandatory. Every transaction derives organization membership on the
-- server and copies the complete boundary into every child row.
create or replace function public.assistant_enqueue_turn(
  p_user_id uuid,
  p_organization_id uuid,
  p_edition text,
  p_workspace_id text,
  p_idempotency_key text,
  p_provider text,
  p_model text,
  p_message text,
  p_request_sha256 text,
  p_request_json jsonb
)
returns public.assistant_runs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  resolved_organization_id uuid;
  resolved_tenant_id uuid;
  selected_conversation public.assistant_conversations%rowtype;
  existing_run public.assistant_runs%rowtype;
  inserted_run public.assistant_runs%rowtype;
  selected_sequence bigint;
begin
  if p_user_id is null
    or p_edition not in ('universal', 'sim', 'lab', 'field')
    or p_workspace_id is null
    or char_length(p_workspace_id) not between 8 and 128
    or p_workspace_id !~ '^[A-Za-z0-9_-]+$'
    or p_idempotency_key is null
    or char_length(p_idempotency_key) not between 8 and 128
    or p_idempotency_key !~ '^[A-Za-z0-9_.:-]+$'
    or p_provider not in ('openai', 'deepseek', 'kimi')
    or p_model is null or char_length(p_model) not between 1 and 128
    or p_message is null or char_length(p_message) not between 1 and 12000
    or p_request_sha256 is null or p_request_sha256 !~ '^[0-9a-f]{64}$'
    or jsonb_typeof(coalesce(p_request_json, '{}'::jsonb)) <> 'object'
  then
    raise exception using errcode = '22023', message = 'INVALID_ASSISTANT_TURN';
  end if;

  resolved_organization_id := public.organization_resolve_membership(
    p_user_id, p_organization_id
  );
  resolved_tenant_id := coalesce(resolved_organization_id, p_user_id);

  perform pg_advisory_xact_lock(
    hashtextextended(p_user_id::text || ':' || p_idempotency_key, 0)
  );
  select * into existing_run from public.assistant_runs
  where owner_user_id = p_user_id and idempotency_key = p_idempotency_key;
  if found then
    if existing_run.tenant_id <> resolved_tenant_id
      or existing_run.organization_id is distinct from resolved_organization_id
      or existing_run.edition <> p_edition
      or existing_run.workspace_id <> p_workspace_id
      or existing_run.provider <> p_provider
      or existing_run.model <> p_model
      or existing_run.request_sha256 <> p_request_sha256
    then
      raise exception using errcode = '23505', message = 'ASSISTANT_IDEMPOTENCY_CONFLICT';
    end if;
    return existing_run;
  end if;

  insert into public.assistant_conversations (
    tenant_id, organization_id, owner_user_id, edition, workspace_id
  ) values (
    resolved_tenant_id, resolved_organization_id, p_user_id, p_edition, p_workspace_id
  ) on conflict (tenant_id, owner_user_id, edition, workspace_id) do nothing;

  select * into selected_conversation from public.assistant_conversations
  where tenant_id = resolved_tenant_id and owner_user_id = p_user_id
    and edition = p_edition and workspace_id = p_workspace_id
  for update;
  if not found or selected_conversation.organization_id is distinct from resolved_organization_id then
    raise exception using errcode = '42501', message = 'ASSISTANT_TENANT_MISMATCH';
  end if;
  if selected_conversation.status <> 'active' then
    raise exception using errcode = '55000', message = 'ASSISTANT_CONVERSATION_ARCHIVED';
  end if;

  selected_sequence := selected_conversation.next_sequence;
  update public.assistant_conversations
  set next_sequence = next_sequence + 1, updated_at = now()
  where conversation_id = selected_conversation.conversation_id;

  insert into public.assistant_runs (
    conversation_id, tenant_id, organization_id, owner_user_id, edition,
    workspace_id, sequence, idempotency_key, provider, model,
    request_sha256, request_json, timeout_at
  ) values (
    selected_conversation.conversation_id, resolved_tenant_id,
    resolved_organization_id, p_user_id, p_edition, p_workspace_id,
    selected_sequence, p_idempotency_key, p_provider, p_model,
    p_request_sha256, coalesce(p_request_json, '{}'::jsonb), now() + interval '15 minutes'
  ) returning * into inserted_run;

  insert into public.assistant_messages (
    conversation_id, run_id, tenant_id, organization_id, owner_user_id,
    edition, workspace_id, sequence, role, content
  ) values (
    selected_conversation.conversation_id, inserted_run.run_id,
    resolved_tenant_id, resolved_organization_id, p_user_id, p_edition,
    p_workspace_id, selected_sequence, 'user', p_message
  );
  return inserted_run;
end;
$$;

create or replace function public.assistant_claim_next_run(
  p_user_id uuid,
  p_conversation_id uuid,
  p_lease_token uuid
)
returns public.assistant_runs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  selected_conversation public.assistant_conversations%rowtype;
  selected_run public.assistant_runs%rowtype;
  live_organization_id uuid;
begin
  if p_user_id is null or p_conversation_id is null or p_lease_token is null then
    raise exception using errcode = '22023', message = 'INVALID_ASSISTANT_LEASE';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_conversation_id::text, 0));
  select * into selected_conversation from public.assistant_conversations
  where conversation_id = p_conversation_id and owner_user_id = p_user_id;
  if not found then
    raise exception using errcode = '42501', message = 'ASSISTANT_CONVERSATION_FORBIDDEN';
  end if;
  live_organization_id := public.organization_resolve_membership(
    p_user_id, selected_conversation.organization_id
  );
  if selected_conversation.organization_id is distinct from live_organization_id
    or selected_conversation.tenant_id <> coalesce(live_organization_id, p_user_id)
  then
    raise exception using errcode = '42501', message = 'ASSISTANT_TENANT_MEMBERSHIP_REVOKED';
  end if;

  update public.assistant_runs
  set state = 'failed', stage = 'failed_recoverable',
      error_code = 'ASSISTANT_WORKER_LEASE_EXPIRED',
      error_message = 'The worker stopped before sealing the result. Retry this turn.',
      request_json = '{}'::jsonb, lease_token = null, lease_expires_at = null,
      completed_at = now(), updated_at = now()
  where conversation_id = p_conversation_id and state = 'processing'
    and lease_expires_at < now();

  if exists (select 1 from public.assistant_runs
    where conversation_id = p_conversation_id and state = 'processing') then
    return null;
  end if;

  loop
    select * into selected_run from public.assistant_runs
    where conversation_id = p_conversation_id
      and owner_user_id = p_user_id
      and state in ('queued', 'retry_wait')
    order by sequence limit 1 for update skip locked;
    if not found then return null; end if;
    if selected_run.timeout_at is not null and selected_run.timeout_at <= now() then
      update public.assistant_runs
      set state = 'failed', stage = 'failed_recoverable',
          error_code = 'ASSISTANT_RUN_TIMEOUT',
          error_message = 'The queued task timed out before execution. Retry this turn.',
          request_json = '{}'::jsonb, completed_at = now(), updated_at = now()
      where run_id = selected_run.run_id;
      -- A terminal head item must not strand later sequence numbers.
      continue;
    end if;
    if selected_run.state = 'retry_wait'
      and selected_run.next_attempt_at is not null
      and selected_run.next_attempt_at > now()
    then
      return null;
    end if;
    if selected_run.attempt_count >= selected_run.max_attempts then
      update public.assistant_runs set state = 'failed', stage = 'failed_recoverable',
        error_code = 'ASSISTANT_RETRY_EXHAUSTED', completed_at = now(), updated_at = now()
      where run_id = selected_run.run_id;
      -- Preserve FIFO while allowing the next valid turn to proceed.
      continue;
    end if;
    exit;
  end loop;

  update public.assistant_runs
  set state = 'processing', stage = 'analyzing',
      attempt_count = attempt_count + 1,
      started_at = coalesce(started_at, now()), next_attempt_at = null,
      lease_token = p_lease_token, lease_expires_at = now() + interval '3 minutes',
      updated_at = now()
  where run_id = selected_run.run_id
  returning * into selected_run;
  return selected_run;
end;
$$;

create or replace function public.assistant_update_run_stage(
  p_user_id uuid, p_run_id uuid, p_lease_token uuid, p_stage text,
  p_intent text, p_workflow_json jsonb
)
returns public.assistant_runs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare updated_run public.assistant_runs%rowtype;
begin
  if p_stage not in ('analyzing', 'planning', 'calling_tools', 'validating')
    or jsonb_typeof(coalesce(p_workflow_json, '[]'::jsonb)) <> 'array'
  then raise exception using errcode = '22023', message = 'INVALID_ASSISTANT_STAGE';
  end if;
  update public.assistant_runs
  set stage = p_stage, intent = nullif(left(coalesce(p_intent, ''), 64), ''),
      workflow_json = coalesce(p_workflow_json, '[]'::jsonb),
      lease_expires_at = now() + interval '3 minutes', updated_at = now()
  where run_id = p_run_id and owner_user_id = p_user_id
    and state = 'processing' and lease_token = p_lease_token
    and lease_expires_at >= now()
  returning * into updated_run;
  if not found then raise exception using errcode = '55000', message = 'ASSISTANT_RUN_NOT_PROCESSING'; end if;
  return updated_run;
end;
$$;

create or replace function public.assistant_complete_run(
  p_user_id uuid, p_run_id uuid, p_lease_token uuid, p_intent text,
  p_workflow_json jsonb, p_result_json jsonb, p_assistant_message text,
  p_summary text, p_artifact_kind text, p_artifact_title text,
  p_artifact_payload jsonb
)
returns public.assistant_runs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  selected_run public.assistant_runs%rowtype;
  updated_run public.assistant_runs%rowtype;
  inserted_artifact public.assistant_artifacts%rowtype;
  sealed_result jsonb;
  generated_files jsonb;
begin
  select * into selected_run from public.assistant_runs
  where run_id = p_run_id and owner_user_id = p_user_id
    and state = 'processing' and lease_token = p_lease_token
    and lease_expires_at >= now() for update;
  if not found then raise exception using errcode = '55000', message = 'ASSISTANT_RUN_NOT_PROCESSING'; end if;
  if p_intent is null or char_length(p_intent) not between 1 and 64
    or jsonb_typeof(p_workflow_json) <> 'array'
    or jsonb_typeof(p_result_json) <> 'object'
    or p_assistant_message is null or char_length(p_assistant_message) not between 1 and 12000
    or p_summary is null or char_length(p_summary) > 8000
    or p_artifact_title is null or char_length(p_artifact_title) not between 1 and 255
    or jsonb_typeof(p_artifact_payload) <> 'object'
  then raise exception using errcode = '22023', message = 'INVALID_ASSISTANT_RESULT'; end if;
  if not (
    (selected_run.edition = 'universal' and p_artifact_kind in (
      'universal_vehicle_model', 'universal_simulation_experiment', 'universal_cross_edition_workflow'))
    or (selected_run.edition = 'sim' and p_artifact_kind = 'simulation_experiment')
    or (selected_run.edition = 'lab' and p_artifact_kind in (
      'lab_simulation_experiment', 'lab_hardware_validation', 'lab_calibration_workflow',
      'lab_sim_to_real_workflow', 'lab_real_to_sim_workflow'))
    or (selected_run.edition = 'field' and p_artifact_kind = 'field_task_plan')
  ) then raise exception using errcode = '22023', message = 'ASSISTANT_ARTIFACT_EDITION_MISMATCH'; end if;

  insert into public.assistant_artifacts (
    conversation_id, run_id, tenant_id, organization_id, owner_user_id,
    edition, workspace_id, artifact_kind, title, payload_json
  ) values (
    selected_run.conversation_id, selected_run.run_id, selected_run.tenant_id,
    selected_run.organization_id, selected_run.owner_user_id, selected_run.edition,
    selected_run.workspace_id, p_artifact_kind, p_artifact_title, p_artifact_payload
  ) returning * into inserted_artifact;
  insert into public.assistant_messages (
    conversation_id, run_id, tenant_id, organization_id, owner_user_id,
    edition, workspace_id, sequence, role, content, metadata_json
  ) values (
    selected_run.conversation_id, selected_run.run_id, selected_run.tenant_id,
    selected_run.organization_id, selected_run.owner_user_id, selected_run.edition,
    selected_run.workspace_id, selected_run.sequence, 'assistant', p_assistant_message,
    jsonb_build_object('artifact_id', inserted_artifact.artifact_id,
      'artifact_version', inserted_artifact.version, 'intent', p_intent)
  );
  select coalesce(jsonb_agg(jsonb_build_object(
    'file_id', file.file_id,
    'display_name', file.display_name,
    'content_type', file.content_type,
    'byte_size', file.byte_size,
    'content_sha256', file.content_sha256,
    'version', file.version
  ) order by file.created_at), '[]'::jsonb)
  into generated_files
  from public.assistant_files file
  where file.run_id = selected_run.run_id
    and file.conversation_id = selected_run.conversation_id
    and file.tenant_id = selected_run.tenant_id
    and file.owner_user_id = selected_run.owner_user_id
    and file.edition = selected_run.edition
    and file.workspace_id = selected_run.workspace_id
    and file.direction = 'generated' and file.status = 'active';
  if jsonb_array_length(generated_files) < 1 then
    raise exception using errcode = '55000', message = 'ASSISTANT_GENERATED_FILE_REQUIRED';
  end if;
  sealed_result := p_result_json || jsonb_build_object(
    'artifact_id', inserted_artifact.artifact_id,
    'artifact_version', inserted_artifact.version,
    'conversation_id', selected_run.conversation_id,
    'run_id', selected_run.run_id, 'sequence', selected_run.sequence,
    'tenant_id', selected_run.tenant_id,
    'organization_id', selected_run.organization_id,
    'workspace_id', selected_run.workspace_id,
    'edition', selected_run.edition,
    'generated_files', generated_files,
    'product_link', '/console/assistant?edition=' || selected_run.edition
      || '&experiment=' || selected_run.workspace_id
      || '&artifact=' || inserted_artifact.artifact_id::text
  );
  update public.assistant_runs
  set state = 'completed', stage = 'completed', intent = left(p_intent, 64),
      workflow_json = p_workflow_json, result_json = sealed_result,
      request_json = '{}'::jsonb, lease_token = null, lease_expires_at = null,
      completed_at = now(), updated_at = now()
  where run_id = selected_run.run_id returning * into updated_run;
  update public.assistant_conversations
  set summary = p_summary,
      title = case when title = 'Untitled draft' then p_artifact_title else title end,
      latest_completed_sequence = greatest(latest_completed_sequence, selected_run.sequence),
      updated_at = now()
  where conversation_id = selected_run.conversation_id
    and tenant_id = selected_run.tenant_id and owner_user_id = selected_run.owner_user_id
    and edition = selected_run.edition and workspace_id = selected_run.workspace_id;
  return updated_run;
end;
$$;

create or replace function public.assistant_defer_run(
  p_user_id uuid, p_run_id uuid, p_lease_token uuid,
  p_error_code text, p_retry_after_seconds integer
)
returns public.assistant_runs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare updated_run public.assistant_runs%rowtype;
begin
  if p_retry_after_seconds not between 1 and 300 then
    raise exception using errcode = '22023', message = 'ASSISTANT_RETRY_INVALID';
  end if;
  update public.assistant_runs
  set state = case when attempt_count < max_attempts then 'retry_wait' else 'failed' end,
      stage = case when attempt_count < max_attempts then 'retry_wait' else 'failed_recoverable' end,
      next_attempt_at = case when attempt_count < max_attempts
        then now() + make_interval(secs => p_retry_after_seconds) end,
      error_code = left(coalesce(p_error_code, 'MODEL_PROVIDER_BUSY'), 128),
      error_message = 'The selected model is busy. This task is safely queued for retry.',
      lease_token = null, lease_expires_at = null,
      completed_at = case when attempt_count >= max_attempts then now() end,
      updated_at = now()
  where run_id = p_run_id and owner_user_id = p_user_id
    and state = 'processing' and lease_token = p_lease_token
  returning * into updated_run;
  if not found then raise exception using errcode = '55000', message = 'ASSISTANT_RUN_NOT_PROCESSING'; end if;
  return updated_run;
end;
$$;

revoke execute on function public.assistant_enqueue_turn(
  uuid, text, text, text, text, text, text, text, jsonb
) from service_role;
revoke all on function public.assistant_enqueue_turn(
  uuid, uuid, text, text, text, text, text, text, text, jsonb
) from public;
grant execute on function public.assistant_enqueue_turn(
  uuid, uuid, text, text, text, text, text, text, text, jsonb
) to service_role;
