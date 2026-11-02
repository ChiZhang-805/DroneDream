-- Two-stage long-term memory:
--   validated session candidate -> account + responsibility consolidation.
-- A single model-produced value is never promoted as a durable fact. Repeated
-- evidence or an explicit future user-resolution path is required.

create or replace function public.console_memory_payload_is_safe(input jsonb)
returns boolean
language plpgsql
immutable
security definer
set search_path = public, pg_temp
as $$
declare
  entry record;
  normalized_key text;
begin
  if input is null or public.console_memory_strip_task_authority(input) <> input then
    return false;
  end if;
  case jsonb_typeof(input)
    when 'object' then
      for entry in select key, value from jsonb_each(input)
      loop
        normalized_key := regexp_replace(lower(entry.key), '[^a-z0-9]', '', 'g');
        if normalized_key ~ '(apikey|authorization|cookie|credential|password|privatekey|clientsecret|secret|token)'
          or normalized_key in (
            'systemprompt', 'developerprompt', 'prompt', 'instruction', 'instructions',
            'command', 'shellcommand', 'toolcall', 'assistantmessage', 'conversationmessage'
          )
          or not public.console_memory_payload_is_safe(entry.value)
        then
          return false;
        end if;
      end loop;
      return true;
    when 'array' then
      for entry in select value from jsonb_array_elements(input)
      loop
        if not public.console_memory_payload_is_safe(entry.value) then
          return false;
        end if;
      end loop;
      return true;
    when 'string' then
      return trim(both '"' from input::text) !~* (
        '(ignore|disregard)[[:space:]]+(all[[:space:]]+|any[[:space:]]+)?(previous|prior)[[:space:]]+instructions'
        || '|system[[:space:]_-]*prompt|developer[[:space:]_-]*message'
        || '|execute[[:space:]]+(this[[:space:]]+)?(command|tool)'
        || '|call[[:space:]]+(the[[:space:]]+)?tool|<script'
        || '|bearer[[:space:]]+[a-z0-9._-]{8,}|sk-[a-z0-9_-]{10,}'
        || '|(approval|confirmation)[[:space:]_-]*(granted|approved|confirmed|valid)'
        || '|(operator|human|user)[[:space:]_-]*(approved|confirmed)([[:space:]]+(flight|execution|write|arming|control))?'
        || '|(flight|execution|write|arming|actuator|control)[[:space:]_-]*authority[[:space:]_-]*(:|=)?[[:space:]_-]*(granted|true|enabled|active)'
        || '|(armed|execute[[:space:]_-]*now)[[:space:]]*[:=][[:space:]]*true'
      );
    else
      return true;
  end case;
end;
$$;

alter table public.console_memory_records
  add column if not exists memory_key text,
  add column if not exists memory_kind text,
  add column if not exists payload_sha256 text,
  add column if not exists source_kind text,
  add column if not exists source_metadata jsonb,
  add column if not exists evidence_count integer,
  add column if not exists confidence numeric(4, 3),
  add column if not exists first_seen timestamptz,
  add column if not exists last_seen timestamptz,
  add column if not exists status text,
  add column if not exists retrieval_metadata jsonb;

update public.console_memory_records
set memory_key = coalesce(memory_key, 'legacy.' || replace(memory_id::text, '-', '')),
    memory_kind = coalesce(memory_kind, 'structured_state'),
    payload_sha256 = coalesce(
      payload_sha256,
      encode(extensions.digest(convert_to(payload::text, 'UTF8'), 'sha256'), 'hex')
    ),
    source_kind = coalesce(source_kind, 'legacy'),
    source_metadata = coalesce(source_metadata, jsonb_build_object(
      'source_edition', edition,
      'source_workspace_id', workspace_id,
      'source_conversation_id', conversation_id
    )),
    evidence_count = coalesce(evidence_count, 1),
    confidence = coalesce(confidence, 0.500),
    first_seen = coalesce(first_seen, created_at),
    last_seen = coalesce(last_seen, updated_at),
    status = coalesce(status, 'active'),
    retrieval_metadata = coalesce(retrieval_metadata, '{}'::jsonb);

-- Legacy unsafe content is neither injected nor retained verbatim.
update public.console_memory_records
set payload = jsonb_build_object('redacted', true),
    payload_sha256 = encode(
      extensions.digest(convert_to(jsonb_build_object('redacted', true)::text, 'UTF8'), 'sha256'),
      'hex'
    ),
    status = 'rejected',
    source_metadata = source_metadata || jsonb_build_object('rejection_reason', 'unsafe_legacy_payload')
where not public.console_memory_payload_is_safe(payload);

alter table public.console_memory_records
  alter column memory_key set not null,
  alter column memory_kind set not null,
  alter column payload_sha256 set not null,
  alter column source_kind set not null,
  alter column source_metadata set default '{}'::jsonb,
  alter column source_metadata set not null,
  alter column evidence_count set default 1,
  alter column evidence_count set not null,
  alter column confidence set default 0.500,
  alter column confidence set not null,
  alter column first_seen set default now(),
  alter column first_seen set not null,
  alter column last_seen set default now(),
  alter column last_seen set not null,
  alter column status set default 'active',
  alter column status set not null,
  alter column retrieval_metadata set default '{}'::jsonb,
  alter column retrieval_metadata set not null;

alter table public.console_memory_records
  drop constraint if exists console_memory_records_memory_key_check,
  drop constraint if exists console_memory_records_memory_kind_check,
  drop constraint if exists console_memory_records_payload_sha256_check,
  drop constraint if exists console_memory_records_source_kind_check,
  drop constraint if exists console_memory_records_evidence_count_check,
  drop constraint if exists console_memory_records_confidence_check,
  drop constraint if exists console_memory_records_status_check,
  drop constraint if exists console_memory_records_source_metadata_check,
  drop constraint if exists console_memory_records_retrieval_metadata_check;

alter table public.console_memory_records
  add constraint console_memory_records_memory_key_check
    check (memory_key ~ '^[a-z][a-z0-9_.:-]{2,159}$'),
  add constraint console_memory_records_memory_kind_check
    check (memory_kind in ('structured_state', 'curated_note')),
  add constraint console_memory_records_payload_sha256_check
    check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  add constraint console_memory_records_source_kind_check
    check (source_kind in (
      'legacy', 'validated_plan_candidate', 'explicit_user_update',
      'imported', 'resolved_conflict'
    )),
  add constraint console_memory_records_evidence_count_check
    check (evidence_count between 1 and 1000000),
  add constraint console_memory_records_confidence_check
    check (confidence between 0 and 1),
  add constraint console_memory_records_status_check
    check (status in ('active', 'superseded', 'forgotten', 'expired', 'rejected')),
  add constraint console_memory_records_source_metadata_check
    check (jsonb_typeof(source_metadata) = 'object'),
  add constraint console_memory_records_retrieval_metadata_check
    check (jsonb_typeof(retrieval_metadata) = 'object');

create unique index if not exists console_memory_records_one_active_key_idx
  on public.console_memory_records (
    user_id, tenant_id, organization_id, responsibility_namespace, scope, memory_key
  ) where status = 'active';

create index if not exists console_memory_records_injection_idx
  on public.console_memory_records (
    user_id, tenant_id, organization_id, responsibility_namespace,
    status, scope, confidence desc, last_seen desc
  );

create table if not exists public.console_memory_candidates (
  candidate_id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  tenant_id uuid not null,
  organization_id uuid not null default '00000000-0000-0000-0000-000000000000',
  responsibility_namespace text not null check (responsibility_namespace in (
    'account.shared',
    'optimization.control_tuning',
    'autonomy.mission',
    'asset.qualification',
    'experiment.simulation',
    'workflow.cross_edition',
    'validation.hardware',
    'calibration.system',
    'transfer.sim_to_real',
    'transfer.real_to_sim',
    'operations.field'
  )),
  scope text not null check (scope in (
    'chat_preferences', 'experiment_defaults', 'device_vehicle',
    'metrics_constraints', 'safety_approvals', 'workflow_tools',
    'reports_delivery', 'collaboration_organization', 'files_artifacts'
  )),
  memory_key text not null check (memory_key ~ '^[a-z][a-z0-9_.:-]{2,159}$'),
  memory_kind text not null check (memory_kind in ('structured_state', 'curated_note')),
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  payload_sha256 text not null check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  source_kind text not null check (source_kind in (
    'validated_plan_candidate', 'explicit_user_update', 'imported'
  )),
  source_edition text not null check (source_edition in (
    'universal', 'sim', 'lab', 'field', 'autonomy'
  )),
  source_workspace_id text not null check (
    char_length(source_workspace_id) between 1 and 160
    and source_workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
  ),
  conversation_id uuid not null,
  run_id uuid not null,
  source_receipt_id text not null check (
    char_length(source_receipt_id) between 8 and 200
    and source_receipt_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
  ),
  source_receipt_sha256 text not null check (source_receipt_sha256 ~ '^[0-9a-f]{64}$'),
  source_receipt_verified_at timestamptz not null,
  source_metadata jsonb not null default '{}'::jsonb
    check (jsonb_typeof(source_metadata) = 'object'),
  retrieval_metadata jsonb not null default '{}'::jsonb
    check (jsonb_typeof(retrieval_metadata) = 'object'),
  evidence_sha256 text not null check (evidence_sha256 ~ '^[0-9a-f]{64}$'),
  evidence_count integer not null default 1 check (evidence_count between 1 and 1000000),
  confidence numeric(4, 3) not null check (confidence between 0 and 1),
  status text not null default 'staged'
    check (status in ('staged', 'accepted', 'conflict', 'rejected', 'expired')),
  first_seen timestamptz not null default now(),
  last_seen timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '30 days'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (
    (organization_id = '00000000-0000-0000-0000-000000000000' and tenant_id = user_id)
    or (organization_id <> '00000000-0000-0000-0000-000000000000' and tenant_id = organization_id)
  ),
  unique (
    user_id, tenant_id, organization_id, responsibility_namespace,
    scope, memory_key, run_id
  )
);

create index if not exists console_memory_candidates_session_idx
  on public.console_memory_candidates (
    user_id, tenant_id, organization_id, conversation_id,
    responsibility_namespace, status, last_seen desc
  );

create index if not exists console_memory_candidates_evidence_idx
  on public.console_memory_candidates (
    user_id, tenant_id, organization_id, responsibility_namespace,
    scope, memory_key, payload_sha256, status
  );

alter table public.console_memory_candidates enable row level security;
alter table public.console_memory_candidates force row level security;

drop policy if exists "Users read their staged console memory" on public.console_memory_candidates;
create policy "Users read their staged console memory"
  on public.console_memory_candidates for select to authenticated
  using (
    user_id = auth.uid() and (
      (
        organization_id = '00000000-0000-0000-0000-000000000000'
        and tenant_id = auth.uid()
      )
      or exists (
        select 1 from public.organization_members membership
        where membership.organization_id = console_memory_candidates.organization_id
          and membership.organization_id = console_memory_candidates.tenant_id
          and membership.user_id = auth.uid()
          and membership.status = 'active'
      )
    )
  );

create or replace function public.console_memory_boundary_allowed(
  p_user_id uuid,
  p_tenant_id uuid,
  p_organization_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select p_user_id is not null and p_tenant_id is not null and (
    (
      p_organization_id = '00000000-0000-0000-0000-000000000000'
      and p_tenant_id = p_user_id
    )
    or (
      p_organization_id <> '00000000-0000-0000-0000-000000000000'
      and p_tenant_id = p_organization_id
      and exists (
        select 1 from public.organization_members membership
        where membership.organization_id = p_organization_id
          and membership.user_id = p_user_id
          and membership.status = 'active'
      )
    )
  );
$$;

create or replace function public.console_memory_stage_candidate(
  p_user_id uuid,
  p_tenant_id uuid,
  p_organization_id uuid,
  p_responsibility_namespace text,
  p_scope text,
  p_memory_key text,
  p_memory_kind text,
  p_payload jsonb,
  p_source_kind text,
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
set search_path = public, extensions, pg_temp
as $$
declare
  selected_candidate public.console_memory_candidates%rowtype;
  active_memory public.console_memory_records%rowtype;
  support_count integer;
  support_confidence numeric(4, 3);
  payload_hash text;
  promote_candidate boolean;
begin
  if not public.console_memory_boundary_allowed(
    p_user_id, p_tenant_id, p_organization_id
  ) then
    raise exception using errcode = '42501', message = 'MEMORY_TENANT_MISMATCH';
  end if;
  if p_responsibility_namespace is null or p_responsibility_namespace not in (
      'account.shared', 'optimization.control_tuning', 'autonomy.mission',
      'asset.qualification', 'experiment.simulation', 'workflow.cross_edition',
      'validation.hardware', 'calibration.system', 'transfer.sim_to_real',
      'transfer.real_to_sim', 'operations.field'
    )
    or p_scope is null or p_scope not in (
      'chat_preferences', 'experiment_defaults', 'device_vehicle',
      'metrics_constraints', 'safety_approvals', 'workflow_tools',
      'reports_delivery', 'collaboration_organization', 'files_artifacts'
    )
    or p_memory_key is null or p_memory_key !~ '^[a-z][a-z0-9_.:-]{2,159}$'
    or p_memory_kind is null or p_memory_kind not in ('structured_state', 'curated_note')
    or p_source_kind is null or p_source_kind not in ('validated_plan_candidate', 'explicit_user_update', 'imported')
    or p_source_edition is null or p_source_edition not in ('universal', 'sim', 'lab', 'field', 'autonomy')
    or p_source_workspace_id is null
    or char_length(p_source_workspace_id) not between 1 and 160
    or p_source_workspace_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
    or p_conversation_id is null or p_run_id is null
    or p_source_receipt_id is null
    or char_length(p_source_receipt_id) not between 8 and 200
    or p_source_receipt_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
    or p_source_receipt_sha256 is null
    or p_source_receipt_sha256 !~ '^[0-9a-f]{64}$'
    or p_evidence_sha256 is null or p_evidence_sha256 !~ '^[0-9a-f]{64}$'
    or p_confidence is null or p_confidence < 0 or p_confidence > 1
    or jsonb_typeof(coalesce(p_source_metadata, '{}'::jsonb)) <> 'object'
    or jsonb_typeof(coalesce(p_retrieval_metadata, '{}'::jsonb)) <> 'object'
    or not public.console_memory_payload_is_safe(coalesce(p_source_metadata, '{}'::jsonb))
    or not public.console_memory_payload_is_safe(coalesce(p_retrieval_metadata, '{}'::jsonb))
    or not public.console_memory_payload_is_safe(p_payload)
  then
    raise exception using errcode = '22023', message = 'UNSAFE_MEMORY_CANDIDATE';
  end if;

  payload_hash := encode(digest(convert_to(p_payload::text, 'UTF8'), 'sha256'), 'hex');
  -- Every writer takes the owner/domain lock before the per-key lock. A
  -- domain forget/delete therefore cannot race a promotion without locking
  -- tables shared by other accounts.
  perform pg_advisory_xact_lock(hashtextextended(
    p_user_id::text || ':' || p_tenant_id::text || ':' ||
    p_organization_id::text || ':' || p_responsibility_namespace,
    0
  ));
  perform pg_advisory_xact_lock(hashtextextended(
    p_user_id::text || ':' || p_tenant_id::text || ':' ||
    p_responsibility_namespace || ':' || p_scope || ':' || p_memory_key,
    0
  ));

  insert into public.console_memory_candidates (
    user_id, tenant_id, organization_id, responsibility_namespace, scope,
    memory_key, memory_kind, payload, payload_sha256, source_kind, source_edition,
    source_workspace_id, conversation_id, run_id, source_receipt_id,
    source_receipt_sha256, source_receipt_verified_at, source_metadata,
    retrieval_metadata, evidence_sha256, confidence
  ) values (
    p_user_id, p_tenant_id, p_organization_id, p_responsibility_namespace, p_scope,
    p_memory_key, p_memory_kind, p_payload, payload_hash, p_source_kind, p_source_edition,
    p_source_workspace_id, p_conversation_id, p_run_id, p_source_receipt_id,
    p_source_receipt_sha256, now(),
    coalesce(p_source_metadata, '{}'::jsonb),
    coalesce(p_retrieval_metadata, '{}'::jsonb), p_evidence_sha256, p_confidence
  )
  on conflict (
    user_id, tenant_id, organization_id, responsibility_namespace,
    scope, memory_key, run_id
  ) do update
  set payload = excluded.payload,
      payload_sha256 = excluded.payload_sha256,
      memory_kind = excluded.memory_kind,
      source_kind = excluded.source_kind,
      source_metadata = excluded.source_metadata,
      retrieval_metadata = excluded.retrieval_metadata,
      evidence_sha256 = excluded.evidence_sha256,
      source_receipt_id = excluded.source_receipt_id,
      source_receipt_sha256 = excluded.source_receipt_sha256,
      source_receipt_verified_at = excluded.source_receipt_verified_at,
      confidence = excluded.confidence,
      status = case
        when console_memory_candidates.status = 'accepted'
          and console_memory_candidates.payload_sha256 = excluded.payload_sha256
        then 'accepted'
        else 'staged'
      end,
      last_seen = now(),
      expires_at = now() + interval '30 days',
      updated_at = now()
  returning * into selected_candidate;

  with distinct_evidence as (
    -- A conversation contributes at most one support unit, even if it has
    -- many runs or hashes. Only service-verified source receipts are counted.
    select candidate.conversation_id, max(candidate.confidence) as confidence
    from public.console_memory_candidates candidate
    where candidate.user_id = p_user_id
      and candidate.tenant_id = p_tenant_id
      and candidate.organization_id = p_organization_id
      and candidate.responsibility_namespace = p_responsibility_namespace
      and candidate.scope = p_scope
      and candidate.memory_key = p_memory_key
      and candidate.payload_sha256 = payload_hash
      and candidate.status in ('staged', 'accepted', 'conflict')
      and candidate.expires_at > now()
      and candidate.source_receipt_verified_at is not null
      and candidate.source_receipt_sha256 ~ '^[0-9a-f]{64}$'
    group by candidate.conversation_id
  )
  select count(*)::integer,
         least(
           0.990::numeric,
           avg(evidence.confidence) + least(0.240::numeric, (count(*) - 1) * 0.080)
         )::numeric(4, 3)
  into support_count, support_confidence
  from distinct_evidence evidence;

  select * into active_memory
  from public.console_memory_records memory
  where memory.user_id = p_user_id
    and memory.tenant_id = p_tenant_id
    and memory.organization_id = p_organization_id
    and memory.responsibility_namespace = p_responsibility_namespace
    and memory.scope = p_scope
    and memory.memory_key = p_memory_key
    and memory.status = 'active'
    and memory.expires_at > now()
  for update;

  if not found then
    -- Model-generated plans stay staged regardless of repetition. Only a
    -- receipt explicitly classified as a direct user update may self-promote.
    promote_candidate := (
      p_source_kind = 'explicit_user_update' and support_confidence >= 0.900
    );
    if promote_candidate then
      insert into public.console_memory_records (
        user_id, tenant_id, organization_id, workspace_id, edition,
        conversation_id, responsibility_namespace, scope, memory_key,
        memory_kind, payload, payload_sha256, source_kind, source_metadata, evidence_count,
        confidence, first_seen, last_seen, status, retrieval_metadata, expires_at
      ) values (
        p_user_id, p_tenant_id, p_organization_id, p_source_workspace_id,
        p_source_edition, p_conversation_id, p_responsibility_namespace, p_scope,
        p_memory_key, p_memory_kind, p_payload, payload_hash, p_source_kind,
        coalesce(p_source_metadata, '{}'::jsonb), support_count,
        support_confidence, selected_candidate.first_seen, now(), 'active',
        coalesce(p_retrieval_metadata, '{}'::jsonb), now() + interval '180 days'
      );
      update public.console_memory_candidates candidate
      set status = 'accepted', updated_at = now()
      where candidate.user_id = p_user_id
        and candidate.tenant_id = p_tenant_id
        and candidate.organization_id = p_organization_id
        and candidate.responsibility_namespace = p_responsibility_namespace
        and candidate.scope = p_scope
        and candidate.memory_key = p_memory_key
        and candidate.payload_sha256 = payload_hash
        and candidate.status in ('staged', 'conflict');
      selected_candidate.status := 'accepted';
    end if;
    return selected_candidate;
  end if;

  if active_memory.payload_sha256 = payload_hash then
    update public.console_memory_records
    set evidence_count = greatest(evidence_count, support_count),
        confidence = greatest(confidence, support_confidence),
        source_metadata = coalesce(p_source_metadata, '{}'::jsonb),
        last_seen = now(),
        expires_at = now() + interval '180 days',
        updated_at = now()
    where memory_id = active_memory.memory_id;
    update public.console_memory_candidates
    set status = 'accepted', updated_at = now()
    where candidate_id = selected_candidate.candidate_id;
    selected_candidate.status := 'accepted';
    return selected_candidate;
  end if;

  update public.console_memory_candidates candidate
  set status = 'conflict', updated_at = now()
  where candidate.user_id = p_user_id
    and candidate.tenant_id = p_tenant_id
    and candidate.organization_id = p_organization_id
    and candidate.responsibility_namespace = p_responsibility_namespace
    and candidate.scope = p_scope
    and candidate.memory_key = p_memory_key
    and candidate.payload_sha256 = payload_hash
    and candidate.status = 'staged';
  selected_candidate.status := 'conflict';

  -- An active-value conflict is never automatically replaced. Even an
  -- explicit update remains a conflict until the authenticated resolve RPC
  -- records the user's choice.
  return selected_candidate;
end;
$$;

create or replace function public.console_memory_resolve_candidate(
  p_user_id uuid,
  p_candidate_id uuid,
  p_resolution text
)
returns public.console_memory_candidates
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  candidate public.console_memory_candidates%rowtype;
begin
  select * into candidate from public.console_memory_candidates
  where candidate_id = p_candidate_id and user_id = p_user_id;
  if not found or not public.console_memory_boundary_allowed(
    candidate.user_id, candidate.tenant_id, candidate.organization_id
  ) then
    raise exception using errcode = '42501', message = 'MEMORY_CANDIDATE_NOT_ACCESSIBLE';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(
    candidate.user_id::text || ':' || candidate.tenant_id::text || ':' ||
    candidate.organization_id::text || ':' || candidate.responsibility_namespace,
    0
  ));
  select * into candidate from public.console_memory_candidates
  where candidate_id = p_candidate_id and user_id = p_user_id
  for update;
  if not found then
    raise exception using errcode = '42501', message = 'MEMORY_CANDIDATE_NOT_ACCESSIBLE';
  end if;
  if p_resolution = 'reject' then
    update public.console_memory_candidates
    set status = 'rejected', updated_at = now()
    where candidate_id = candidate.candidate_id returning * into candidate;
    return candidate;
  end if;
  if p_resolution <> 'promote' or candidate.status not in ('staged', 'conflict') then
    raise exception using errcode = '22023', message = 'INVALID_MEMORY_RESOLUTION';
  end if;
  update public.console_memory_records
  set status = 'superseded', last_seen = now(), updated_at = now()
  where user_id = candidate.user_id
    and tenant_id = candidate.tenant_id
    and organization_id = candidate.organization_id
    and responsibility_namespace = candidate.responsibility_namespace
    and scope = candidate.scope
    and memory_key = candidate.memory_key
    and status = 'active';
  insert into public.console_memory_records (
    user_id, tenant_id, organization_id, workspace_id, edition,
    conversation_id, responsibility_namespace, scope, memory_key,
    memory_kind, payload, payload_sha256, source_kind, source_metadata, evidence_count,
    confidence, first_seen, last_seen, status, retrieval_metadata, expires_at
  ) values (
    candidate.user_id, candidate.tenant_id, candidate.organization_id,
    candidate.source_workspace_id, candidate.source_edition, candidate.conversation_id,
    candidate.responsibility_namespace, candidate.scope, candidate.memory_key,
    candidate.memory_kind, candidate.payload, candidate.payload_sha256, 'resolved_conflict',
    candidate.source_metadata || jsonb_build_object('resolution', 'explicit_promote'),
    candidate.evidence_count, greatest(candidate.confidence, 0.950),
    candidate.first_seen, now(), 'active', candidate.retrieval_metadata,
    now() + interval '180 days'
  );
  update public.console_memory_candidates
  set status = 'accepted', updated_at = now()
  where candidate_id = candidate.candidate_id returning * into candidate;
  return candidate;
end;
$$;

create or replace function public.console_memory_forget(
  p_user_id uuid,
  p_tenant_id uuid,
  p_organization_id uuid,
  p_responsibility_namespace text,
  p_memory_key text
)
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  changed integer := 0;
  affected integer := 0;
begin
  if not public.console_memory_boundary_allowed(
    p_user_id, p_tenant_id, p_organization_id
  ) then
    raise exception using errcode = '42501', message = 'MEMORY_TENANT_MISMATCH';
  end if;
  update public.console_memory_records
  set status = 'forgotten', last_seen = now(), updated_at = now()
  where user_id = p_user_id
    and tenant_id = p_tenant_id
    and organization_id = p_organization_id
    and responsibility_namespace = p_responsibility_namespace
    and memory_key = p_memory_key
    and status = 'active';
  get diagnostics changed = row_count;
  update public.console_memory_candidates
  set status = 'rejected', updated_at = now()
  where user_id = p_user_id
    and tenant_id = p_tenant_id
    and organization_id = p_organization_id
    and responsibility_namespace = p_responsibility_namespace
    and memory_key = p_memory_key
    and status in ('staged', 'accepted', 'conflict');
  get diagnostics affected = row_count;
  return changed + affected;
end;
$$;

-- Replace the compatibility trigger with a strict storage contract. Existing
-- scope names remain valid, but new durable records must come through staging.
create or replace function public.console_memory_enforce_contract()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if not public.console_memory_payload_is_safe(new.payload) then
    raise exception using errcode = '22023', message = 'UNSAFE_LONG_TERM_MEMORY';
  end if;
  new.payload_sha256 := encode(
    extensions.digest(convert_to(new.payload::text, 'UTF8'), 'sha256'),
    'hex'
  );
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists console_memory_enforce_contract on public.console_memory_records;
create trigger console_memory_enforce_contract
  before insert or update of payload
  on public.console_memory_records
  for each row execute function public.console_memory_enforce_contract();

revoke insert, update, delete on public.console_memory_records from authenticated;
grant select on public.console_memory_records to authenticated;
revoke all on public.console_memory_candidates from anon, authenticated;
grant all on public.console_memory_candidates to service_role;

revoke all on function public.console_memory_payload_is_safe(jsonb)
  from public, anon, authenticated;
revoke all on function public.console_memory_boundary_allowed(uuid, uuid, uuid)
  from public, anon, authenticated;
revoke all on function public.console_memory_stage_candidate(
  uuid, uuid, uuid, text, text, text, text, jsonb, text, text, text,
  uuid, uuid, text, text, jsonb, jsonb, text, numeric
) from public, anon, authenticated;
revoke all on function public.console_memory_resolve_candidate(uuid, uuid, text)
  from public, anon, authenticated;
revoke all on function public.console_memory_forget(uuid, uuid, uuid, text, text)
  from public, anon, authenticated;

grant execute on function public.console_memory_payload_is_safe(jsonb) to service_role;
grant execute on function public.console_memory_boundary_allowed(uuid, uuid, uuid) to service_role;
grant execute on function public.console_memory_stage_candidate(
  uuid, uuid, uuid, text, text, text, text, jsonb, text, text, text,
  uuid, uuid, text, text, jsonb, jsonb, text, numeric
) to service_role;
grant execute on function public.console_memory_resolve_candidate(uuid, uuid, text) to service_role;
grant execute on function public.console_memory_forget(uuid, uuid, uuid, text, text) to service_role;

comment on table public.console_memory_candidates is
  'Session-scoped structured memory candidates; model drafts remain staged and active-value conflicts require explicit authenticated resolution.';
comment on column public.console_memory_records.status is
  'Only active, unexpired records may be injected. Superseded, forgotten, expired, and rejected rows are retained for audit only.';
