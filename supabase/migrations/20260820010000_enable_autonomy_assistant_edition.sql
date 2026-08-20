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
