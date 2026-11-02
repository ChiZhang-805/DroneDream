-- Extend the server-authoritative assistant and console boundaries to the
-- fifth product. The AUTONOMY frontend must not be selectable until these
-- database checks and the enqueue RPC accept the same edition identity.

alter table public.assistant_conversations
  drop constraint if exists assistant_conversations_edition_check;
alter table public.assistant_conversations
  add constraint assistant_conversations_edition_check
  check (edition in ('universal', 'sim', 'lab', 'field', 'autonomy'));

alter table public.assistant_runs
  drop constraint if exists assistant_runs_edition_check;
alter table public.assistant_runs
  add constraint assistant_runs_edition_check
  check (edition in ('universal', 'sim', 'lab', 'field', 'autonomy'));

alter table public.assistant_messages
  drop constraint if exists assistant_messages_edition_check;
alter table public.assistant_messages
  add constraint assistant_messages_edition_check
  check (edition in ('universal', 'sim', 'lab', 'field', 'autonomy'));

alter table public.assistant_artifacts
  drop constraint if exists assistant_artifacts_edition_check;
alter table public.assistant_artifacts
  add constraint assistant_artifacts_edition_check
  check (edition in ('universal', 'sim', 'lab', 'field', 'autonomy'));

alter table public.assistant_run_steps
  drop constraint if exists assistant_run_steps_edition_check;
alter table public.assistant_run_steps
  add constraint assistant_run_steps_edition_check
  check (edition in ('universal', 'sim', 'lab', 'field', 'autonomy'));

alter table public.assistant_files
  drop constraint if exists assistant_files_edition_check;
alter table public.assistant_files
  add constraint assistant_files_edition_check
  check (edition in ('universal', 'sim', 'lab', 'field', 'autonomy'));

alter table public.assistant_artifact_versions
  drop constraint if exists assistant_artifact_versions_edition_check;
alter table public.assistant_artifact_versions
  add constraint assistant_artifact_versions_edition_check
  check (edition in ('universal', 'sim', 'lab', 'field', 'autonomy'));

alter table public.console_preferences
  drop constraint if exists console_preferences_workspace_id_check;
alter table public.console_preferences
  add constraint console_preferences_workspace_id_check
  check (workspace_id ~ '^console-(universal|sim|lab|field|autonomy)$');

alter table public.console_preferences
  drop constraint if exists console_preferences_edition_check;
alter table public.console_preferences
  add constraint console_preferences_edition_check
  check (edition in ('universal', 'sim', 'lab', 'field', 'autonomy'));

alter table public.console_memory_records
  drop constraint if exists console_memory_records_edition_check;
alter table public.console_memory_records
  add constraint console_memory_records_edition_check
  check (edition in ('universal', 'sim', 'lab', 'field', 'autonomy'));

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
    or p_edition not in ('universal', 'sim', 'lab', 'field', 'autonomy')
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

  perform pg_advisory_xact_lock(hashtextextended(
    'assistant-conversation:' || resolved_tenant_id::text || ':' ||
    p_user_id::text || ':' || p_edition || ':' || p_workspace_id,
    0
  ));

  select * into selected_conversation from public.assistant_conversations
  where tenant_id = resolved_tenant_id and owner_user_id = p_user_id
    and edition = p_edition and workspace_id = p_workspace_id
  for update;

  if not found then
    insert into public.assistant_conversations (
      tenant_id, organization_id, owner_user_id, edition, workspace_id
    ) values (
      resolved_tenant_id, resolved_organization_id, p_user_id,
      p_edition, p_workspace_id
    ) returning * into selected_conversation;
  end if;

  if selected_conversation.organization_id is distinct from resolved_organization_id then
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

revoke all on function public.assistant_enqueue_turn(
  uuid, uuid, text, text, text, text, text, text, text, jsonb
) from public;
grant execute on function public.assistant_enqueue_turn(
  uuid, uuid, text, text, text, text, text, text, text, jsonb
) to service_role;

-- The completion boundary is independent from enqueue validation. Keep the
-- server-authoritative artifact/edition matrix aligned with the AUTONOMY
-- tasks exposed by the orchestrator, or valid runs fail only after planning
-- and generated-file registration have already completed.
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
  if not found then
    raise exception using errcode = '55000', message = 'ASSISTANT_RUN_NOT_PROCESSING';
  end if;
  if p_intent is null or char_length(p_intent) not between 1 and 64
    or jsonb_typeof(p_workflow_json) <> 'array'
    or jsonb_typeof(p_result_json) <> 'object'
    or p_assistant_message is null or char_length(p_assistant_message) not between 1 and 12000
    or p_summary is null or char_length(p_summary) > 8000
    or p_artifact_title is null or char_length(p_artifact_title) not between 1 and 255
    or jsonb_typeof(p_artifact_payload) <> 'object'
  then
    raise exception using errcode = '22023', message = 'INVALID_ASSISTANT_RESULT';
  end if;
  if not (
    p_artifact_kind = 'autonomy_mission_plan'
    or (selected_run.edition = 'universal' and p_artifact_kind in (
      'universal_vehicle_model', 'universal_simulation_experiment',
      'universal_cross_edition_workflow'))
    or (selected_run.edition = 'sim' and p_artifact_kind = 'simulation_experiment')
    or (selected_run.edition = 'lab' and p_artifact_kind in (
      'lab_simulation_experiment', 'lab_hardware_validation', 'lab_calibration_workflow',
      'lab_sim_to_real_workflow', 'lab_real_to_sim_workflow'))
    or (selected_run.edition = 'field' and p_artifact_kind = 'field_task_plan')
    or (selected_run.edition = 'autonomy' and p_artifact_kind in (
      'universal_vehicle_model', 'simulation_experiment'))
  ) then
    raise exception using errcode = '22023', message = 'ASSISTANT_ARTIFACT_EDITION_MISMATCH';
  end if;

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
    jsonb_build_object(
      'artifact_id', inserted_artifact.artifact_id,
      'artifact_version', inserted_artifact.version,
      'intent', p_intent
    )
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
    'run_id', selected_run.run_id,
    'sequence', selected_run.sequence,
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
      latest_completed_sequence = greatest(
        latest_completed_sequence,
        selected_run.sequence
      ),
      updated_at = now()
  where conversation_id = selected_run.conversation_id
    and tenant_id = selected_run.tenant_id
    and owner_user_id = selected_run.owner_user_id
    and edition = selected_run.edition
    and workspace_id = selected_run.workspace_id;
  return updated_run;
end;
$$;
