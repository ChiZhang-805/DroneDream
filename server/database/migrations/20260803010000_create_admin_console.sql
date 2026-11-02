-- Server-authorized administration, model policy, and community moderation.
-- All tables in this migration are default-deny to browser clients. Edge
-- Functions use the service role only after validating a user JWT and RBAC.

create table if not exists public.app_admins (
  user_id uuid primary key references auth.users(id) on delete restrict,
  role text not null check (role in ('owner', 'admin')),
  permissions text[] not null default '{}',
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (
    permissions <@ array[
      'dashboard.read', 'models.read', 'models.write', 'users.read',
      'users.export', 'community.read', 'community.remove', 'audit.read'
    ]::text[]
  )
);

create unique index if not exists app_admins_single_owner_idx
  on public.app_admins ((role)) where role = 'owner' and active;

create table if not exists public.admin_audit_log (
  id uuid primary key default gen_random_uuid(),
  actor_user_id uuid not null references auth.users(id) on delete restrict,
  action text not null check (char_length(action) between 3 and 96),
  target_type text not null check (char_length(target_type) between 2 and 64),
  target_id text check (target_id is null or char_length(target_id) <= 160),
  reason text check (reason is null or char_length(reason) between 8 and 500),
  metadata jsonb not null default '{}'::jsonb,
  outcome text not null default 'succeeded'
    check (outcome in ('succeeded', 'failed')),
  created_at timestamptz not null default now(),
  check (jsonb_typeof(metadata) = 'object'),
  check (octet_length(metadata::text) <= 4096)
);

create index if not exists admin_audit_log_created_idx
  on public.admin_audit_log (created_at desc, id desc);

create table if not exists public.model_provider_policies (
  provider text primary key check (provider in ('openai', 'deepseek', 'qwen')),
  enabled boolean not null default false,
  assistant_enabled boolean not null default false,
  job_enabled boolean not null default false,
  version bigint not null default 1 check (version > 0),
  updated_by uuid references auth.users(id) on delete restrict,
  updated_at timestamptz not null default now(),
  check (enabled or (not assistant_enabled and not job_enabled))
);

insert into public.model_provider_policies (
  provider, enabled, assistant_enabled, job_enabled
)
values
  ('openai', false, false, false),
  ('deepseek', false, false, false),
  ('qwen', false, false, false)
on conflict (provider) do nothing;

alter table public.app_admins enable row level security;
alter table public.admin_audit_log enable row level security;
alter table public.model_provider_policies enable row level security;
revoke all on table public.app_admins from anon, authenticated;
revoke all on table public.admin_audit_log from anon, authenticated;
revoke all on table public.model_provider_policies from anon, authenticated;
grant all on table public.app_admins to service_role;
grant all on table public.admin_audit_log to service_role;
grant all on table public.model_provider_policies to service_role;

create or replace function public.admin_audit_append_only()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception using errcode = '42501', message = 'ADMIN_AUDIT_APPEND_ONLY';
end;
$$;

revoke all on function public.admin_audit_append_only() from public;
drop trigger if exists admin_audit_log_append_only on public.admin_audit_log;
create trigger admin_audit_log_append_only
  before update or delete on public.admin_audit_log
  for each row execute function public.admin_audit_append_only();

create or replace function public.admin_bootstrap_owner(p_user_id uuid)
returns public.app_admins
language plpgsql
security definer
set search_path = ''
as $$
declare
  owner_row public.app_admins%rowtype;
begin
  if p_user_id is null or not exists (select 1 from auth.users where id = p_user_id) then
    raise exception using errcode = '22023', message = 'ADMIN_BOOTSTRAP_USER_INVALID';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('dronedream-admin-owner', 0));
  select * into owner_row
  from public.app_admins
  where role = 'owner' and active
  for update;
  if owner_row.user_id is not null and owner_row.user_id <> p_user_id then
    raise exception using errcode = '42501', message = 'ADMIN_OWNER_ALREADY_BOUND';
  end if;
  insert into public.app_admins (user_id, role, permissions, active)
  values (
    p_user_id,
    'owner',
    array[
      'dashboard.read', 'models.read', 'models.write', 'users.read',
      'users.export', 'community.read', 'community.remove', 'audit.read'
    ]::text[],
    true
  )
  on conflict (user_id) do update
  set role = 'owner', permissions = excluded.permissions, active = true,
      updated_at = now()
  returning * into owner_row;
  return owner_row;
end;
$$;

revoke all on function public.admin_bootstrap_owner(uuid) from public;
grant execute on function public.admin_bootstrap_owner(uuid) to service_role;

create or replace function public.admin_update_model_policy(
  p_actor_user_id uuid,
  p_provider text,
  p_enabled boolean,
  p_assistant_enabled boolean,
  p_job_enabled boolean,
  p_expected_version bigint
)
returns public.model_provider_policies
language plpgsql
security definer
set search_path = ''
as $$
declare
  updated_policy public.model_provider_policies%rowtype;
begin
  if p_provider not in ('openai', 'deepseek', 'qwen')
    or p_expected_version is null or p_expected_version <= 0
    or (not p_enabled and (p_assistant_enabled or p_job_enabled))
  then
    raise exception using errcode = '22023', message = 'MODEL_POLICY_INVALID';
  end if;
  update public.model_provider_policies
  set enabled = p_enabled,
      assistant_enabled = p_assistant_enabled,
      job_enabled = p_job_enabled,
      version = version + 1,
      updated_by = p_actor_user_id,
      updated_at = now()
  where provider = p_provider and version = p_expected_version
  returning * into updated_policy;
  if updated_policy.provider is null then
    raise exception using errcode = '40001', message = 'MODEL_POLICY_VERSION_CONFLICT';
  end if;
  insert into public.admin_audit_log (
    actor_user_id, action, target_type, target_id, metadata
  ) values (
    p_actor_user_id,
    'model_policy.updated',
    'model_provider',
    p_provider,
    jsonb_build_object(
      'enabled', p_enabled,
      'assistant_enabled', p_assistant_enabled,
      'job_enabled', p_job_enabled,
      'version', updated_policy.version
    )
  );
  return updated_policy;
end;
$$;

revoke all on function public.admin_update_model_policy(
  uuid, text, boolean, boolean, boolean, bigint
) from public;
grant execute on function public.admin_update_model_policy(
  uuid, text, boolean, boolean, boolean, bigint
) to service_role;

alter table public.community_topics
  add column if not exists hidden_at timestamptz,
  add column if not exists hidden_by uuid references auth.users(id) on delete restrict,
  add column if not exists hidden_reason text
    check (hidden_reason is null or char_length(hidden_reason) between 8 and 500);

drop policy if exists "Community topics are publicly readable"
  on public.community_topics;
create policy "Community topics are publicly readable"
  on public.community_topics
  for select
  using (hidden_at is null);

create or replace function public.community_protect_moderation_fields()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if auth.role() <> 'service_role' and (
    new.hidden_at is distinct from old.hidden_at
    or new.hidden_by is distinct from old.hidden_by
    or new.hidden_reason is distinct from old.hidden_reason
  ) then
    raise exception using errcode = '42501', message = 'COMMUNITY_MODERATION_FORBIDDEN';
  end if;
  return new;
end;
$$;

revoke all on function public.community_protect_moderation_fields() from public;
drop trigger if exists community_topics_protect_moderation
  on public.community_topics;
create trigger community_topics_protect_moderation
  before update of hidden_at, hidden_by, hidden_reason
  on public.community_topics
  for each row execute function public.community_protect_moderation_fields();

create or replace function public.admin_remove_community_topic(
  p_actor_user_id uuid,
  p_topic_id uuid,
  p_reason text
)
returns public.community_topics
language plpgsql
security definer
set search_path = ''
as $$
declare
  topic_row public.community_topics%rowtype;
begin
  if p_topic_id is null or char_length(btrim(coalesce(p_reason, ''))) not between 8 and 500 then
    raise exception using errcode = '22023', message = 'COMMUNITY_REMOVE_REASON_INVALID';
  end if;
  select * into topic_row
  from public.community_topics
  where id = p_topic_id
  for update;
  if topic_row.id is null then
    raise exception using errcode = 'P0002', message = 'COMMUNITY_TOPIC_NOT_FOUND';
  end if;
  if topic_row.hidden_at is null then
    update public.community_topics
    set hidden_at = now(), hidden_by = p_actor_user_id,
        hidden_reason = btrim(p_reason), updated_at = now()
    where id = p_topic_id
    returning * into topic_row;
    insert into public.admin_audit_log (
      actor_user_id, action, target_type, target_id, reason
    ) values (
      p_actor_user_id, 'community.topic_removed', 'community_topic',
      p_topic_id::text, btrim(p_reason)
    );
  end if;
  return topic_row;
end;
$$;

revoke all on function public.admin_remove_community_topic(uuid, uuid, text)
  from public;
grant execute on function public.admin_remove_community_topic(uuid, uuid, text)
  to service_role;

alter table public.model_gateway_grants
  add column if not exists provider text not null default 'openai'
    check (provider in ('openai', 'deepseek', 'qwen'));

create or replace function public.model_enforce_provider_policy()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  grant_row public.model_gateway_grants%rowtype;
  policy_row public.model_provider_policies%rowtype;
begin
  select * into grant_row from public.model_gateway_grants
  where grant_id = new.grant_id;
  select * into policy_row from public.model_provider_policies
  where provider = new.provider;
  if grant_row.grant_id is null
    or grant_row.provider <> new.provider
    or grant_row.scope <> new.purpose
    or policy_row.provider is null
    or not policy_row.enabled
    or (new.purpose = 'assistant' and not policy_row.assistant_enabled)
    or (new.purpose = 'job' and not policy_row.job_enabled)
  then
    raise exception using errcode = 'P0001', message = 'MODEL_PROVIDER_DISABLED';
  end if;
  return new;
end;
$$;

revoke all on function public.model_enforce_provider_policy() from public;
drop trigger if exists model_usage_requests_enforce_provider
  on public.model_usage_requests;
create trigger model_usage_requests_enforce_provider
  before insert on public.model_usage_requests
  for each row execute function public.model_enforce_provider_policy();

revoke all on function public.model_gateway_issue_grant(uuid, text, text, text)
  from public;
drop function if exists public.model_gateway_issue_grant(uuid, text, text, text);

create function public.model_gateway_issue_grant(
  p_user_id uuid,
  p_token_sha256 text,
  p_scope text,
  p_provider text,
  p_scope_reference text default null
)
returns public.model_gateway_grants
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_period public.model_usage_periods%rowtype;
  policy_row public.model_provider_policies%rowtype;
  issued_grant public.model_gateway_grants%rowtype;
  grant_ttl interval;
  grant_calls integer;
begin
  if p_token_sha256 !~ '^[0-9a-f]{64}$'
    or p_scope not in ('assistant', 'job')
    or p_provider not in ('openai', 'deepseek', 'qwen')
    or (p_scope_reference is not null and (
      length(p_scope_reference) not between 1 and 128
      or p_scope_reference !~ '^[A-Za-z0-9_.:-]+$'
    ))
  then
    raise exception using errcode = '22023', message = 'INVALID_MODEL_GRANT';
  end if;
  select * into policy_row from public.model_provider_policies
  where provider = p_provider;
  if policy_row.provider is null or not policy_row.enabled
    or (p_scope = 'assistant' and not policy_row.assistant_enabled)
    or (p_scope = 'job' and not policy_row.job_enabled)
  then
    raise exception using errcode = 'P0001', message = 'MODEL_PROVIDER_DISABLED';
  end if;
  selected_period := public.model_access_ensure_period(p_user_id);
  if selected_period.consumed_ai_credits + selected_period.reserved_ai_credits
      >= selected_period.included_ai_credits then
    raise exception using errcode = 'P0001', message = 'MODEL_QUOTA_EXHAUSTED';
  end if;
  if p_scope = 'assistant' then
    grant_ttl := interval '5 minutes';
    grant_calls := 2;
  else
    grant_ttl := interval '24 hours';
    grant_calls := 256;
  end if;
  insert into public.model_gateway_grants (
    user_id, token_sha256, scope, provider, scope_reference,
    max_calls, expires_at
  ) values (
    p_user_id, p_token_sha256, p_scope, p_provider, p_scope_reference,
    grant_calls, now() + grant_ttl
  ) returning * into issued_grant;
  return issued_grant;
end;
$$;

revoke all on function public.model_gateway_issue_grant(
  uuid, text, text, text, text
) from public;
grant execute on function public.model_gateway_issue_grant(
  uuid, text, text, text, text
) to service_role;

notify pgrst, 'reload schema';
