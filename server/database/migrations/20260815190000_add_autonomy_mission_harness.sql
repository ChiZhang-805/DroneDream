begin;

alter table public.assistant_artifacts
  drop constraint if exists assistant_artifacts_artifact_kind_check;
alter table public.assistant_artifacts
  add constraint assistant_artifacts_artifact_kind_check check (
    artifact_kind in (
      'autonomy_mission_plan',
      'universal_vehicle_model', 'universal_simulation_experiment',
      'universal_cross_edition_workflow', 'simulation_experiment',
      'lab_simulation_experiment', 'lab_hardware_validation',
      'lab_calibration_workflow', 'lab_sim_to_real_workflow',
      'lab_real_to_sim_workflow', 'field_task_plan'
    )
  );

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

commit;
