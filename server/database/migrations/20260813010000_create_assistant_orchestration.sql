-- Server-authoritative assistant conversations, serialized turn execution,
-- and edition-scoped draft artifacts. Browser clients never write these
-- tables directly; the assistant-orchestrator edge function authenticates the
-- caller and uses the service role to invoke the bounded transaction helpers.

create table if not exists public.assistant_conversations (
  conversation_id uuid primary key default gen_random_uuid(),
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  edition text not null check (edition in ('universal', 'sim', 'lab', 'field')),
  workspace_id text not null check (
    char_length(workspace_id) between 8 and 128
    and workspace_id ~ '^[A-Za-z0-9_-]+$'
  ),
  title text not null default 'Untitled draft' check (char_length(title) between 1 and 255),
  summary text not null default '' check (char_length(summary) <= 8000),
  status text not null default 'active' check (status in ('active', 'archived')),
  next_sequence bigint not null default 1 check (next_sequence >= 1),
  latest_completed_sequence bigint not null default 0 check (latest_completed_sequence >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (owner_user_id, edition, workspace_id),
  unique (conversation_id, owner_user_id, edition, workspace_id)
);

create index if not exists assistant_conversations_owner_updated_idx
  on public.assistant_conversations (owner_user_id, updated_at desc);

create table if not exists public.assistant_runs (
  run_id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  edition text not null check (edition in ('universal', 'sim', 'lab', 'field')),
  workspace_id text not null check (char_length(workspace_id) between 8 and 128),
  sequence bigint not null check (sequence >= 1),
  idempotency_key text not null check (
    char_length(idempotency_key) between 8 and 128
    and idempotency_key ~ '^[A-Za-z0-9_.:-]+$'
  ),
  provider text not null check (provider in ('openai', 'deepseek', 'kimi')),
  model text not null check (char_length(model) between 1 and 128),
  request_sha256 text not null check (request_sha256 ~ '^[0-9a-f]{64}$'),
  state text not null default 'queued'
    check (state in ('queued', 'processing', 'completed', 'failed')),
  stage text not null default 'queued'
    check (stage in ('queued', 'classifying', 'planning', 'creating', 'validating', 'completed', 'failed')),
  intent text,
  request_json jsonb not null default '{}'::jsonb,
  workflow_json jsonb not null default '[]'::jsonb,
  result_json jsonb,
  error_code text,
  error_message text,
  lease_token uuid,
  lease_expires_at timestamptz,
  queued_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now(),
  unique (conversation_id, sequence),
  unique (owner_user_id, idempotency_key),
  unique (run_id, conversation_id, owner_user_id, edition, workspace_id),
  unique (run_id, conversation_id, owner_user_id, edition, sequence),
  foreign key (conversation_id, owner_user_id, edition, workspace_id)
    references public.assistant_conversations(
      conversation_id, owner_user_id, edition, workspace_id
    ) on delete cascade
);

create index if not exists assistant_runs_queue_idx
  on public.assistant_runs (conversation_id, state, sequence);
create index if not exists assistant_runs_owner_updated_idx
  on public.assistant_runs (owner_user_id, updated_at desc);
create unique index if not exists assistant_runs_one_processing_per_conversation_idx
  on public.assistant_runs (conversation_id)
  where state = 'processing';

create table if not exists public.assistant_messages (
  message_id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null,
  run_id uuid not null,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  edition text not null check (edition in ('universal', 'sim', 'lab', 'field')),
  sequence bigint not null check (sequence >= 1),
  role text not null check (role in ('user', 'assistant')),
  content text not null check (char_length(content) between 1 and 12000),
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (conversation_id, sequence, role),
  foreign key (run_id, conversation_id, owner_user_id, edition, sequence)
    references public.assistant_runs(
      run_id, conversation_id, owner_user_id, edition, sequence
    ) on delete cascade
);

create index if not exists assistant_messages_conversation_sequence_idx
  on public.assistant_messages (conversation_id, sequence, created_at);

create table if not exists public.assistant_artifacts (
  artifact_id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null,
  run_id uuid not null unique,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  edition text not null check (edition in ('universal', 'sim', 'lab', 'field')),
  workspace_id text not null check (char_length(workspace_id) between 8 and 128),
  artifact_kind text not null check (
    artifact_kind in (
      'universal_vehicle_model',
      'universal_simulation_experiment',
      'simulation_experiment',
      'lab_validation_experiment',
      'field_task_plan'
    )
  ),
  title text not null check (char_length(title) between 1 and 255),
  payload_json jsonb not null,
  version integer not null default 1 check (version >= 1),
  status text not null default 'draft' check (status in ('draft', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (run_id, conversation_id, owner_user_id, edition, workspace_id)
    references public.assistant_runs(
      run_id, conversation_id, owner_user_id, edition, workspace_id
    ) on delete cascade
);

create index if not exists assistant_artifacts_owner_edition_updated_idx
  on public.assistant_artifacts (owner_user_id, edition, updated_at desc);

alter table public.assistant_conversations enable row level security;
alter table public.assistant_runs enable row level security;
alter table public.assistant_messages enable row level security;
alter table public.assistant_artifacts enable row level security;

drop policy if exists "Users read their own assistant conversations"
  on public.assistant_conversations;
create policy "Users read their own assistant conversations"
  on public.assistant_conversations for select to authenticated
  using (owner_user_id = auth.uid());

drop policy if exists "Users read their own assistant runs"
  on public.assistant_runs;
create policy "Users read their own assistant runs"
  on public.assistant_runs for select to authenticated
  using (owner_user_id = auth.uid());

drop policy if exists "Users read their own assistant messages"
  on public.assistant_messages;
create policy "Users read their own assistant messages"
  on public.assistant_messages for select to authenticated
  using (owner_user_id = auth.uid());

drop policy if exists "Users read their own assistant artifacts"
  on public.assistant_artifacts;
create policy "Users read their own assistant artifacts"
  on public.assistant_artifacts for select to authenticated
  using (owner_user_id = auth.uid());

create or replace function public.assistant_enqueue_turn(
  p_user_id uuid,
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
  selected_conversation public.assistant_conversations%rowtype;
  existing_run public.assistant_runs%rowtype;
  inserted_run public.assistant_runs%rowtype;
  selected_sequence bigint;
begin
  if p_user_id is null
    or p_edition is null
    or p_edition not in ('universal', 'sim', 'lab', 'field')
    or p_workspace_id is null
    or char_length(p_workspace_id) not between 8 and 128
    or p_workspace_id !~ '^[A-Za-z0-9_-]+$'
    or p_idempotency_key is null
    or char_length(p_idempotency_key) not between 8 and 128
    or p_idempotency_key !~ '^[A-Za-z0-9_.:-]+$'
    or p_provider is null
    or p_provider not in ('openai', 'deepseek', 'kimi')
    or p_model is null
    or char_length(p_model) not between 1 and 128
    or p_message is null
    or char_length(p_message) not between 1 and 12000
    or p_request_sha256 is null
    or p_request_sha256 !~ '^[0-9a-f]{64}$'
    or jsonb_typeof(coalesce(p_request_json, '{}'::jsonb)) <> 'object'
  then
    raise exception using errcode = '22023', message = 'INVALID_ASSISTANT_TURN';
  end if;

  -- Serialize concurrent first submissions for the same user-scoped key so
  -- retries deterministically reuse (or reject) the original request.
  perform pg_advisory_xact_lock(
    hashtextextended(p_user_id::text || ':' || p_idempotency_key, 0)
  );

  select * into existing_run
  from public.assistant_runs
  where owner_user_id = p_user_id and idempotency_key = p_idempotency_key;
  if found then
    if existing_run.edition <> p_edition
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
    owner_user_id, edition, workspace_id
  ) values (
    p_user_id, p_edition, p_workspace_id
  )
  on conflict (owner_user_id, edition, workspace_id) do nothing;

  select * into selected_conversation
  from public.assistant_conversations
  where owner_user_id = p_user_id
    and edition = p_edition
    and workspace_id = p_workspace_id
  for update;

  if selected_conversation.status <> 'active' then
    raise exception using errcode = '55000', message = 'ASSISTANT_CONVERSATION_ARCHIVED';
  end if;

  selected_sequence := selected_conversation.next_sequence;
  update public.assistant_conversations
  set next_sequence = next_sequence + 1, updated_at = now()
  where conversation_id = selected_conversation.conversation_id;

  insert into public.assistant_runs (
    conversation_id, owner_user_id, edition, workspace_id, sequence,
    idempotency_key, provider, model, request_sha256, request_json
  ) values (
    selected_conversation.conversation_id, p_user_id, p_edition,
    p_workspace_id, selected_sequence, p_idempotency_key, p_provider,
    p_model, p_request_sha256, coalesce(p_request_json, '{}'::jsonb)
  ) returning * into inserted_run;

  insert into public.assistant_messages (
    conversation_id, run_id, owner_user_id, edition, sequence, role, content
  ) values (
    selected_conversation.conversation_id, inserted_run.run_id, p_user_id,
    p_edition, selected_sequence, 'user', p_message
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
  selected_run public.assistant_runs%rowtype;
begin
  if p_user_id is null or p_conversation_id is null or p_lease_token is null then
    raise exception using errcode = '22023', message = 'INVALID_ASSISTANT_LEASE';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_conversation_id::text, 0));

  if not exists (
    select 1 from public.assistant_conversations
    where conversation_id = p_conversation_id and owner_user_id = p_user_id
  ) then
    raise exception using errcode = '42501', message = 'ASSISTANT_CONVERSATION_FORBIDDEN';
  end if;

  -- A provider call may already have consumed allowance when a worker dies.
  -- Do not replay an ambiguous paid call. Seal the abandoned run as failed,
  -- release the per-conversation slot, and require an explicit user retry.
  update public.assistant_runs
  set state = 'failed', stage = 'failed',
      error_code = 'ASSISTANT_WORKER_LEASE_EXPIRED',
      error_message = 'The assistant worker stopped before sealing the result. Retry this turn.',
      request_json = '{}'::jsonb,
      lease_token = null, lease_expires_at = null,
      completed_at = now(), updated_at = now()
  where conversation_id = p_conversation_id
    and state = 'processing'
    and lease_expires_at < now();

  if exists (
    select 1 from public.assistant_runs
    where conversation_id = p_conversation_id and state = 'processing'
  ) then
    return null;
  end if;

  select * into selected_run
  from public.assistant_runs
  where conversation_id = p_conversation_id
    and owner_user_id = p_user_id
    and state = 'queued'
  order by sequence
  limit 1
  for update skip locked;

  if not found then
    return null;
  end if;

  update public.assistant_runs
  set state = 'processing', stage = 'classifying', started_at = now(),
      lease_token = p_lease_token, lease_expires_at = now() + interval '3 minutes',
      updated_at = now()
  where run_id = selected_run.run_id
  returning * into selected_run;
  return selected_run;
end;
$$;

create or replace function public.assistant_update_run_stage(
  p_user_id uuid,
  p_run_id uuid,
  p_lease_token uuid,
  p_stage text,
  p_intent text,
  p_workflow_json jsonb
)
returns public.assistant_runs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  updated_run public.assistant_runs%rowtype;
begin
  if p_user_id is null or p_run_id is null or p_lease_token is null
    or p_stage is null
    or p_stage not in ('classifying', 'planning', 'creating', 'validating')
    or jsonb_typeof(coalesce(p_workflow_json, '[]'::jsonb)) <> 'array'
  then
    raise exception using errcode = '22023', message = 'INVALID_ASSISTANT_STAGE';
  end if;
  update public.assistant_runs
  set stage = p_stage,
      intent = nullif(left(coalesce(p_intent, ''), 64), ''),
      workflow_json = coalesce(p_workflow_json, '[]'::jsonb),
      lease_expires_at = now() + interval '3 minutes',
      updated_at = now()
  where run_id = p_run_id and owner_user_id = p_user_id and state = 'processing'
    and lease_token = p_lease_token and lease_expires_at >= now()
  returning * into updated_run;
  if not found then
    raise exception using errcode = '55000', message = 'ASSISTANT_RUN_NOT_PROCESSING';
  end if;
  return updated_run;
end;
$$;

create or replace function public.assistant_complete_run(
  p_user_id uuid,
  p_run_id uuid,
  p_lease_token uuid,
  p_intent text,
  p_workflow_json jsonb,
  p_result_json jsonb,
  p_assistant_message text,
  p_summary text,
  p_artifact_kind text,
  p_artifact_title text,
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
  inserted_artifact_id uuid;
  sealed_result jsonb;
begin
  select * into selected_run
  from public.assistant_runs
  where run_id = p_run_id and owner_user_id = p_user_id
    and lease_token = p_lease_token and lease_expires_at >= now()
  for update;
  if not found or selected_run.state <> 'processing' then
    raise exception using errcode = '55000', message = 'ASSISTANT_RUN_NOT_PROCESSING';
  end if;
  if p_user_id is null
    or p_run_id is null
    or p_lease_token is null
    or p_intent is null
    or char_length(p_intent) not between 1 and 64
    or p_workflow_json is null
    or jsonb_typeof(p_workflow_json) <> 'array'
    or p_result_json is null
    or jsonb_typeof(p_result_json) <> 'object'
    or p_assistant_message is null
    or char_length(p_assistant_message) not between 1 and 12000
    or p_summary is null
    or char_length(p_summary) > 8000
    or p_artifact_kind is null
    or p_artifact_kind not in (
      'universal_vehicle_model', 'universal_simulation_experiment',
      'simulation_experiment', 'lab_validation_experiment', 'field_task_plan'
    )
    or p_artifact_title is null
    or char_length(p_artifact_title) not between 1 and 255
    or p_artifact_payload is null
    or jsonb_typeof(p_artifact_payload) <> 'object'
  then
    raise exception using errcode = '22023', message = 'INVALID_ASSISTANT_RESULT';
  end if;
  if not (
    (selected_run.edition = 'universal' and p_artifact_kind in (
      'universal_vehicle_model', 'universal_simulation_experiment'
    ))
    or (selected_run.edition = 'sim' and p_artifact_kind = 'simulation_experiment')
    or (selected_run.edition = 'lab' and p_artifact_kind = 'lab_validation_experiment')
    or (selected_run.edition = 'field' and p_artifact_kind = 'field_task_plan')
  ) then
    raise exception using errcode = '22023', message = 'ASSISTANT_ARTIFACT_EDITION_MISMATCH';
  end if;

  insert into public.assistant_artifacts (
    conversation_id, run_id, owner_user_id, edition, workspace_id,
    artifact_kind, title, payload_json
  ) values (
    selected_run.conversation_id, selected_run.run_id, selected_run.owner_user_id,
    selected_run.edition, selected_run.workspace_id, p_artifact_kind,
    p_artifact_title, p_artifact_payload
  ) returning artifact_id into inserted_artifact_id;

  insert into public.assistant_messages (
    conversation_id, run_id, owner_user_id, edition, sequence, role, content,
    metadata_json
  ) values (
    selected_run.conversation_id, selected_run.run_id, selected_run.owner_user_id,
    selected_run.edition, selected_run.sequence, 'assistant', p_assistant_message,
    jsonb_build_object('artifact_id', inserted_artifact_id, 'intent', p_intent)
  );

  sealed_result := p_result_json || jsonb_build_object(
    'artifact_id', inserted_artifact_id,
    'conversation_id', selected_run.conversation_id,
    'run_id', selected_run.run_id,
    'sequence', selected_run.sequence
  );

  update public.assistant_runs
  set state = 'completed', stage = 'completed', intent = left(p_intent, 64),
      workflow_json = p_workflow_json, result_json = sealed_result,
      request_json = '{}'::jsonb, lease_token = null, lease_expires_at = null,
      completed_at = now(), updated_at = now()
  where run_id = selected_run.run_id
  returning * into updated_run;

  update public.assistant_conversations
  set summary = p_summary,
      title = case when title = 'Untitled draft' then p_artifact_title else title end,
      latest_completed_sequence = greatest(latest_completed_sequence, selected_run.sequence),
      updated_at = now()
  where conversation_id = selected_run.conversation_id;

  return updated_run;
end;
$$;

create or replace function public.assistant_fail_run(
  p_user_id uuid,
  p_run_id uuid,
  p_lease_token uuid,
  p_error_code text,
  p_error_message text
)
returns public.assistant_runs
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  updated_run public.assistant_runs%rowtype;
begin
  if p_user_id is null or p_run_id is null or p_lease_token is null then
    raise exception using errcode = '22023', message = 'INVALID_ASSISTANT_FAILURE';
  end if;
  update public.assistant_runs
  set state = 'failed', stage = 'failed',
      error_code = left(coalesce(p_error_code, 'ASSISTANT_FAILED'), 128),
      error_message = left(coalesce(p_error_message, 'The assistant could not complete the turn.'), 1000),
      request_json = '{}'::jsonb, lease_token = null, lease_expires_at = null,
      completed_at = now(), updated_at = now()
  where run_id = p_run_id and owner_user_id = p_user_id
    and lease_token = p_lease_token
    and state in ('queued', 'processing')
  returning * into updated_run;
  if not found then
    raise exception using errcode = '55000', message = 'ASSISTANT_RUN_NOT_ACTIVE';
  end if;
  return updated_run;
end;
$$;

revoke all on table public.assistant_conversations from anon, authenticated;
revoke all on table public.assistant_runs from anon, authenticated;
revoke all on table public.assistant_messages from anon, authenticated;
revoke all on table public.assistant_artifacts from anon, authenticated;
grant select on table public.assistant_conversations to authenticated;
grant select on table public.assistant_runs to authenticated;
grant select on table public.assistant_messages to authenticated;
grant select on table public.assistant_artifacts to authenticated;

revoke all on function public.assistant_enqueue_turn(
  uuid, text, text, text, text, text, text, text, jsonb
) from public;
revoke all on function public.assistant_claim_next_run(uuid, uuid, uuid) from public;
revoke all on function public.assistant_update_run_stage(
  uuid, uuid, uuid, text, text, jsonb
) from public;
revoke all on function public.assistant_complete_run(
  uuid, uuid, uuid, text, jsonb, jsonb, text, text, text, text, jsonb
) from public;
revoke all on function public.assistant_fail_run(uuid, uuid, uuid, text, text) from public;

grant execute on function public.assistant_enqueue_turn(
  uuid, text, text, text, text, text, text, text, jsonb
) to service_role;
grant execute on function public.assistant_claim_next_run(uuid, uuid, uuid) to service_role;
grant execute on function public.assistant_update_run_stage(
  uuid, uuid, uuid, text, text, jsonb
) to service_role;
grant execute on function public.assistant_complete_run(
  uuid, uuid, uuid, text, jsonb, jsonb, text, text, text, text, jsonb
) to service_role;
grant execute on function public.assistant_fail_run(uuid, uuid, uuid, text, text)
  to service_role;
