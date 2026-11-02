-- Bind managed grants to one exact provider/model pair and add Kimi safely.

alter table public.model_provider_policies
  drop constraint if exists model_provider_policies_provider_check;
alter table public.model_provider_policies
  add constraint model_provider_policies_provider_check
  check (provider in ('openai', 'deepseek', 'qwen', 'kimi'));

insert into public.model_provider_policies (
  provider, enabled, assistant_enabled, job_enabled
) values ('kimi', true, true, true)
on conflict (provider) do nothing;

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
  if p_provider not in ('openai', 'deepseek', 'qwen', 'kimi')
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

alter table public.model_gateway_grants
  drop constraint if exists model_gateway_grants_provider_check;
alter table public.model_gateway_grants
  add constraint model_gateway_grants_provider_check
  check (provider in ('openai', 'deepseek', 'qwen', 'kimi'));
alter table public.model_gateway_grants
  add column if not exists model text;

update public.model_gateway_grants
set model = case provider
  when 'openai' then 'gpt-4.1'
  when 'deepseek' then 'deepseek-v4-flash'
  when 'qwen' then 'qwen-plus'
  when 'kimi' then 'kimi-k2.6'
end
where model is null;

alter table public.model_gateway_grants
  alter column model set not null;
alter table public.model_gateway_grants
  drop constraint if exists model_gateway_grants_model_check;
alter table public.model_gateway_grants
  add constraint model_gateway_grants_model_check check (
    (provider = 'openai' and model in ('gpt-4.1', 'gpt-5.1', 'gpt-5.4'))
    or (provider = 'deepseek' and model in ('deepseek-v4-flash', 'deepseek-v4-pro'))
    or (provider = 'qwen' and model = 'qwen-plus')
    or (provider = 'kimi' and model in ('kimi-k2.6', 'kimi-k3'))
  );

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
    or grant_row.model <> new.model
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

drop function if exists public.model_gateway_issue_grant(
  uuid, text, text, text, text
);

create function public.model_gateway_issue_grant(
  p_user_id uuid,
  p_token_sha256 text,
  p_scope text,
  p_provider text,
  p_model text,
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
    or p_provider not in ('openai', 'deepseek', 'qwen', 'kimi')
    or not (
      (p_provider = 'openai' and p_model in ('gpt-4.1', 'gpt-5.1', 'gpt-5.4'))
      or (p_provider = 'deepseek' and p_model in ('deepseek-v4-flash', 'deepseek-v4-pro'))
      or (p_provider = 'qwen' and p_model = 'qwen-plus')
      or (p_provider = 'kimi' and p_model in ('kimi-k2.6', 'kimi-k3'))
    )
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
    user_id, token_sha256, scope, provider, model, scope_reference,
    max_calls, expires_at
  ) values (
    p_user_id, p_token_sha256, p_scope, p_provider, p_model, p_scope_reference,
    grant_calls, now() + grant_ttl
  ) returning * into issued_grant;
  return issued_grant;
end;
$$;

revoke all on function public.model_gateway_issue_grant(
  uuid, text, text, text, text, text
) from public;
grant execute on function public.model_gateway_issue_grant(
  uuid, text, text, text, text, text
) to service_role;

notify pgrst, 'reload schema';
